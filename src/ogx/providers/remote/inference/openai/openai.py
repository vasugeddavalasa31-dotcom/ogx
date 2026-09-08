# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import contextvars
import hashlib
import uuid
import warnings
from collections.abc import AsyncIterator, Iterable
from typing import Any

from ogx.core.request_headers import get_request_headers
from ogx.log import get_logger
from ogx.providers.utils.inference.openai_mixin import OpenAIMixin
from ogx_api import (
    Model,
    ModelType,
    OpenAIChatCompletion,
    OpenAIChatCompletionChunk,
    OpenAIChatCompletionChunkWithReasoning,
    OpenAIChatCompletionRequestWithExtraBody,
    OpenAIChatCompletionWithReasoning,
    OpenAICompletion,
    OpenAICompletionRequestWithExtraBody,
)

from .config import OpenAIConfig

logger = get_logger(name=__name__, category="inference::openai")

# Max output tokens per OpenAI model. OpenAI's /v1/models endpoint does not
# expose this, so we maintain the mapping statically.
_MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "gpt-4.1": 32768,
    "gpt-4.1-mini": 32768,
    "gpt-4.1-nano": 32768,
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
    "gpt-4-turbo": 4096,
    "gpt-4": 8192,
    "o1": 100000,
    "o1-mini": 65536,
    "o1-pro": 100000,
    "o3": 100000,
    "o3-mini": 100000,
    "o3-pro": 100000,
    "o4-mini": 100000,
}

_WARNED_MODELS: set[str] = set()

_CURRENT_OPENCODE_SESSION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_CURRENT_OPENCODE_SESSION_ID", default=None
)


def _derive_session_id(params: Any, raw_headers: dict[str, str]) -> str:
    """Stably derive a session ID for OpenCode Go prompt routing and caching."""
    # 1. Check incoming HTTP headers
    for hk, hv in raw_headers.items():
        if hk.lower() in ("x-opencode-session", "x-session-id") and hv:
            return str(hv).strip()

    if params is not None:
        # 2. Check model_extra or extra_body
        model_extra = getattr(params, "model_extra", None) or {}
        for k in ("x-opencode-session", "opencode_session", "session_id"):
            if k in model_extra and model_extra[k]:
                return str(model_extra[k]).strip()

        # 3. Check prompt_cache_key
        if getattr(params, "prompt_cache_key", None):
            return str(params.prompt_cache_key).strip()

        # 4. Check user identifier
        if getattr(params, "user", None):
            return f"orbiterx-{params.user}".strip()

        # 5. Stable hash of the first user message for multi-turn session stickiness
        messages = getattr(params, "messages", None) or []
        for msg in messages:
            role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
            if role == "user":
                content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
                if content:
                    text = str(content)
                    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
                    return f"orbiterx-{h}"

        # 6. Prompt text if standard completion
        prompt = getattr(params, "prompt", None)
        if prompt:
            text = str(prompt)
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
            return f"orbiterx-{h}"

    return f"orbiterx-{uuid.uuid4().hex[:16]}"


#
# This OpenAI adapter implements Inference methods using OpenAIMixin
#
class OpenAIInferenceAdapter(OpenAIMixin):
    """
    OpenAI Inference Adapter for OGX.
    """

    config: OpenAIConfig

    provider_data_api_key_field: str = "openai_api_key"

    supports_tokenized_embeddings_input: bool = True

    embedding_model_metadata: dict[str, dict[str, int]] = {
        "text-embedding-ada-002": {"embedding_dimension": 1536, "context_length": 8192},
        "text-embedding-3-small": {"embedding_dimension": 1536, "context_length": 8192},
        "text-embedding-3-large": {"embedding_dimension": 3072, "context_length": 8192},
    }

    def _get_max_output_tokens(self, model: str) -> int | None:
        if model in _MODEL_MAX_OUTPUT_TOKENS:
            return _MODEL_MAX_OUTPUT_TOKENS[model]

        # Try prefix matching for dated snapshot variants (e.g. gpt-4o-2024-08-06)
        for base_model, limit in sorted(
            _MODEL_MAX_OUTPUT_TOKENS.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if model.startswith(f"{base_model}-"):
                return limit

        if model not in _WARNED_MODELS:
            _WARNED_MODELS.add(model)
            logger.warning(
                "Unknown max_output_tokens for model, requests will not be clamped",
                model=model,
            )
        return None

    async def list_provider_model_ids(self) -> Iterable[str]:
        """
        Filter out realtime & audio models.
        """
        ids = []
        for m in await super().list_provider_model_ids():
            for excluded in {"whisper", "tts", "realtime", "audio"}:
                if excluded in m:
                    break
            else:
                ids.append(m)
        return ids

    def construct_model_from_identifier(self, identifier: str) -> Model:
        model = super().construct_model_from_identifier(identifier)

        # Add max_output_tokens metadata for LLM models
        if model.model_type == ModelType.llm:
            max_output_tokens = self._get_max_output_tokens(identifier)
            if max_output_tokens is not None:
                metadata = dict(model.metadata or {})
                metadata["max_output_tokens"] = max_output_tokens
                model = model.model_copy(update={"metadata": metadata})

    def _is_opencode_go(self) -> bool:
        base_url = str(self.config.base_url or "").lower()
        provider_id = getattr(self, "__provider_id__", "")
        return "opencode.ai" in base_url or provider_id == "opencode-go"

    def get_extra_client_params(self) -> dict[str, Any]:
        params = dict(super().get_extra_client_params())
        if self._is_opencode_go():
            default_headers = dict(params.get("default_headers") or {})
            default_headers.setdefault("User-Agent", "OrbiterX/1.0")
            default_headers.setdefault("x-opencode-session", f"orbiterx-default-{uuid.uuid4().hex[:12]}")
            params["default_headers"] = default_headers
        return params

    def _get_extra_request_headers(self) -> dict[str, str] | None:
        headers = dict(super()._get_extra_request_headers() or {})
        if self._is_opencode_go():
            session_id = _CURRENT_OPENCODE_SESSION_ID.get()
            if not session_id:
                session_id = _derive_session_id(None, get_request_headers())
            headers["x-opencode-session"] = session_id
            headers.setdefault("User-Agent", "OrbiterX/1.0")
        return headers or None

    async def openai_completion(
        self,
        params: OpenAICompletionRequestWithExtraBody,
    ) -> OpenAICompletion | AsyncIterator[OpenAICompletion]:
        if self._is_opencode_go():
            session_id = _derive_session_id(params, get_request_headers())
            token = _CURRENT_OPENCODE_SESSION_ID.set(session_id)
            try:
                return await super().openai_completion(params)
            finally:
                _CURRENT_OPENCODE_SESSION_ID.reset(token)
        return await super().openai_completion(params)

    async def openai_chat_completion(
        self,
        params: OpenAIChatCompletionRequestWithExtraBody,
    ) -> OpenAIChatCompletion | AsyncIterator[OpenAIChatCompletionChunk]:
        # OpenAI is deprecating max_tokens in favor of max_completion_tokens.
        # Reasoning models (o1/o3/o4) and gpt-5+ reject max_tokens outright.
        # Translate unconditionally since all OpenAI models accept max_completion_tokens.
        if params.max_tokens is not None and params.max_completion_tokens is None:
            warnings.warn(
                "max_tokens is deprecated by OpenAI and will be removed in a future release. "
                "Use max_completion_tokens instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            params = params.model_copy()
            params.max_completion_tokens = params.max_tokens
            params.max_tokens = None

        max_output_tokens = self._get_max_output_tokens(params.model)
        if max_output_tokens is not None:
            updated_params = params
            if params.max_tokens is not None and params.max_tokens > max_output_tokens:
                updated_params = updated_params.model_copy()
                updated_params.max_tokens = max_output_tokens
            if params.max_completion_tokens is not None and params.max_completion_tokens > max_output_tokens:
                if updated_params is params:
                    updated_params = updated_params.model_copy()
                updated_params.max_completion_tokens = max_output_tokens
            params = updated_params

        if self._is_opencode_go():
            session_id = _derive_session_id(params, get_request_headers())
            token = _CURRENT_OPENCODE_SESSION_ID.set(session_id)
            try:
                return await super().openai_chat_completion(params)
            finally:
                _CURRENT_OPENCODE_SESSION_ID.reset(token)

        return await super().openai_chat_completion(params)

    async def openai_chat_completions_with_reasoning(
        self,
        params: OpenAIChatCompletionRequestWithExtraBody,
    ) -> OpenAIChatCompletionWithReasoning | AsyncIterator[OpenAIChatCompletionChunkWithReasoning]:
        """Chat completion with reasoning support for the OpenAI-compatible path.

        OpenAI-compatible providers (including DeepSeek, which this adapter is
        commonly pointed at) stream thinking text in the non-standard
        ``reasoning_content`` chunk delta. The OpenAI SDK keeps that field in
        the delta's extra attributes, so extract it here and wrap each chunk in
        OpenAIChatCompletionChunkWithReasoning for the Responses layer to emit
        as a reasoning item.
        """
        if not params.stream:
            raise NotImplementedError("Non-streaming reasoning is not yet supported")

        result = await self.openai_chat_completion(params)
        if not isinstance(result, AsyncIterator):
            raise RuntimeError("Expected streaming response for reasoning, but got non-streaming result")

        async def _wrap_chunks() -> AsyncIterator[OpenAIChatCompletionChunkWithReasoning]:
            async for chunk in result:
                reasoning = None
                for choice in chunk.choices or []:
                    reasoning = getattr(choice.delta, "reasoning_content", None)
                yield OpenAIChatCompletionChunkWithReasoning(
                    chunk=chunk,
                    reasoning_content=reasoning,
                )

        return _wrap_chunks()

    def get_base_url(self) -> str:
        """
        Get the OpenAI API base URL.

        Returns the OpenAI API base URL from the configuration.
        """
        return str(self.config.base_url)
