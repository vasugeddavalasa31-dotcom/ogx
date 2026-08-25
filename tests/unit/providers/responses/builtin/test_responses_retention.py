# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""Unit tests for the durable responses retention worker.

Exercises `ResponsesStore.purge_old_responses` against a real SQLite backend
to confirm:

- Responses older than the retention window are deleted.
- Responses newer than the retention window are kept.
- An incremental child is materialized before its parent is deleted, so the
  chain still reconstructs for the surviving child.
- A second pass with the same cutoff is a no-op (idempotency).
- A non-positive retention window is rejected.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ogx.core.access_control.access_control import default_policy
from ogx.core.storage.datatypes import (
    ResponsesStoreReference,
    SqliteSqlStoreConfig,
)
from ogx.core.storage.sqlstore.sqlstore import register_sqlstore_backends
from ogx.providers.utils.responses.responses_store import (
    ResponsesStore,
    _OpenAIResponseObjectWithInputAndMessages,
)
from ogx_api import OpenAIResponseInput, OpenAIResponseMessage, OpenAIResponseObject
from ogx_api.inference import (
    OpenAIChatCompletionContentPartTextParam,
    OpenAIUserMessageParam,
)


@pytest.fixture
async def sqlite_responses_store() -> AsyncIterator[ResponsesStore]:
    """A ResponsesStore backed by a real (temp-file) SQLite DB.

    Uses the actual `authorized_sqlstore` + SQLAlchemy path so the retention
    code under test sees the same SQL semantics it sees in production.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "retention_test.db"
        backend_name = "sql_retention_test"
        register_sqlstore_backends(
            {backend_name: SqliteSqlStoreConfig(db_path=str(db_path))}
        )
        store = ResponsesStore(
            ResponsesStoreReference(backend=backend_name, table_name="responses"),
            policy=default_policy(),
        )
        await store.initialize()
        try:
            yield store
        finally:
            await store.shutdown()


def _make_response(
    response_id: str,
    created_at: int,
    input_text: str = "hi",
    previous_response_id: str | None = None,
) -> OpenAIResponseObject:
    """Build a minimal `OpenAIResponseObject` suitable for storage.

    `store=True` is required by the public model and matches our retention
    target (only `store=true` rows are eligible for retention).
    """
    return OpenAIResponseObject(
        id=response_id,
        model="test-model",
        created_at=created_at,
        status="completed",
        output=[],
        previous_response_id=previous_response_id,
        store=True,
    )


def _make_input_message(response_id: str, text: str) -> OpenAIResponseMessage:
    return OpenAIResponseMessage(role="user", content=text, id=f"msg_{response_id}")


def _user_message(text: str) -> OpenAIUserMessageParam:
    return OpenAIUserMessageParam(
        content=[OpenAIChatCompletionContentPartTextParam(text=text)]
    )


async def test_purge_old_responses_deletes_only_old_rows(sqlite_responses_store):
    store = sqlite_responses_store
    # Anchor to wall-clock so the retention cutoff is meaningful: the worker
    # computes `now() - retention_seconds`, not a fixed timestamp.
    now = int(time.time())

    # Insert three rows: two old, one new.
    await store.store_response_object(
        response_object=_make_response("resp_old_1", created_at=now - 100_000),
        input=[],
        messages=[_user_message("old 1")],
    )
    await store.store_response_object(
        response_object=_make_response("resp_old_2", created_at=now - 50_000),
        input=[],
        messages=[_user_message("old 2")],
    )
    await store.store_response_object(
        response_object=_make_response("resp_new", created_at=now - 10),
        input=[],
        messages=[_user_message("new")],
    )

    deleted = await store.purge_old_responses(
        retention_seconds=60 * 60,  # 1 hour
        batch_size=10,
    )
    assert deleted == 2

    # Old rows are gone; new row survives.
    with pytest.raises(Exception):
        await store.get_response_object("resp_old_1")
    with pytest.raises(Exception):
        await store.get_response_object("resp_old_2")
    surviving = await store.get_response_object("resp_new")
    assert surviving.id == "resp_new"


async def test_purge_old_responses_is_idempotent(sqlite_responses_store):
    store = sqlite_responses_store
    now = int(time.time())
    await store.store_response_object(
        response_object=_make_response("resp_old", created_at=now - 100_000),
        input=[],
        messages=[_user_message("old")],
    )

    first = await store.purge_old_responses(retention_seconds=60)
    second = await store.purge_old_responses(retention_seconds=60)
    assert first == 1
    assert second == 0


async def test_purge_old_responses_materializes_incremental_child_before_delete(
    sqlite_responses_store,
):
    """The critical safety case: deleting a parent that has an incremental
    child must rewrite the child to be a self-contained snapshot first,
    otherwise the child's `previous_response_id` dangles and the chain
    breaks for the surviving child.
    """
    store = sqlite_responses_store
    now = int(time.time())
    # Retention window: anything older than 60s is eligible for deletion.
    retention_seconds = 60
    # Parent is well outside the window; child is just inside it, so the
    # child survives but its `previous_response_id` dangles without
    # materialization.
    await store.store_response_object(
        response_object=_make_response("resp_parent", created_at=now - 3600),
        input=[],
        messages=[_user_message("parent turn")],
    )

    await store.upsert_response_object(
        response_object=_make_response(
            "resp_child",
            created_at=now - 5,  # just inside the retention window
            input_text="child turn",
            previous_response_id="resp_parent",
        ),
        input=[_make_input_message("resp_child", "child turn")],
        messages=[_user_message("child turn")],
        incremental_input=True,
    )

    # Sanity: child is incremental with a parent pointer.
    child_before = await store.get_response_object("resp_child")
    assert child_before.input_storage_mode == "incremental"
    assert child_before.previous_response_id == "resp_parent"

    # Purge old responses. The parent is deleted; the child survives only
    # because it was rewritten to a self-contained snapshot.
    deleted = await store.purge_old_responses(retention_seconds=retention_seconds)
    assert deleted == 1  # only the parent

    with pytest.raises(Exception):
        await store.get_response_object("resp_parent")

    child_after = await store.get_response_object("resp_child")
    # Materialization must clear the dangling pointer and snapshot the
    # full input so the child no longer depends on the (now-missing) parent.
    assert child_after.previous_response_id is None
    assert child_after.input_storage_mode is None
    assert len(child_after.input) >= 1


async def test_purge_old_responses_rejects_non_positive_window(sqlite_responses_store):
    store = sqlite_responses_store
    with pytest.raises(ValueError):
        await store.purge_old_responses(retention_seconds=0)
    with pytest.raises(ValueError):
        await store.purge_old_responses(retention_seconds=-1)


async def test_purge_old_responses_tolerates_per_row_failure(sqlite_responses_store):
    """If one row's delete raises, the sweep should log + continue rather
    than poisoning the rest of the batch. The failed row is retried in the
    same call (the outer while loop re-fetches until empty) so the call
    eventually returns `len(rows)` for a transient failure.
    """
    store = sqlite_responses_store
    now = int(time.time())

    for i in range(3):
        await store.store_response_object(
            response_object=_make_response(f"resp_{i}", created_at=now - 100_000),
            input=[],
            messages=[_user_message(f"row {i}")],
        )

    # Force the first delete call to raise once. The retry inside the same
    # `purge_old_responses` call will succeed for the previously-failed row.
    real_delete = store.sql_store.delete
    calls = {"n": 0}

    async def flaky_delete(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic delete failure")
        await real_delete(*args, **kwargs)

    store.sql_store.delete = flaky_delete  # type: ignore[assignment]
    deleted = await store.purge_old_responses(retention_seconds=60, batch_size=10)

    # All three rows are eventually deleted: the first one failed once and
    # was retried by the outer while loop, then succeeded.
    assert deleted == 3
    # The flaky patch saw exactly one failure.
    assert calls["n"] >= 4  # at least 3 successful + 1 failed = 4
    store.sql_store.delete = real_delete  # restore
