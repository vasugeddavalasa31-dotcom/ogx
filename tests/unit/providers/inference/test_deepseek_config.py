# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import os
from unittest.mock import patch

import pytest

from ogx.core.stack import replace_env_vars
from ogx.providers.remote.inference.deepseek.config import DeepSeekImplConfig
from ogx.providers.remote.inference.deepseek.deepseek import DeepSeekInferenceAdapter
from ogx_api import OpenAICompletionRequestWithExtraBody


class TestDeepSeekConfig:
    """Tests for the DeepSeek inference provider config and adapter wiring."""

    def test_default_base_url(self):
        config = DeepSeekImplConfig(api_key="test-key")
        adapter = DeepSeekInferenceAdapter(config=config)
        adapter.provider_data_api_key_field = None

        assert adapter.get_base_url() == "https://api.deepseek.com/v1"

    def test_custom_base_url_from_config(self):
        custom_url = "https://custom.deepseek.com/v1"
        config = DeepSeekImplConfig(api_key="test-key", base_url=custom_url)
        adapter = DeepSeekInferenceAdapter(config=config)
        adapter.provider_data_api_key_field = None

        assert adapter.get_base_url() == custom_url

    @patch.dict(os.environ, {"DEEPSEEK_BASE_URL": "https://env.deepseek.com/v1"})
    def test_base_url_from_environment_variable(self):
        config_data = DeepSeekImplConfig.sample_run_config(api_key="test-key")
        processed_config = replace_env_vars(config_data)
        config = DeepSeekImplConfig.model_validate(processed_config)

        assert str(config.base_url) == "https://api.deepseek.com/v1"

    def test_sample_run_config_uses_env_placeholder(self):
        cfg = DeepSeekImplConfig.sample_run_config()
        assert cfg["base_url"] == "https://api.deepseek.com/v1"
        assert cfg["api_key"] == "${env.DEEPSEEK_API_KEY:=}"

    def test_provider_data_api_key_field(self):
        config = DeepSeekImplConfig(api_key="test-key")
        adapter = DeepSeekInferenceAdapter(config=config)
        assert adapter.provider_data_api_key_field == "deepseek_api_key"

    async def test_embeddings_not_supported(self):
        config = DeepSeekImplConfig(api_key="test-key")
        adapter = DeepSeekInferenceAdapter(config=config)
        with pytest.raises(NotImplementedError, match="does not expose an embeddings endpoint"):
            await adapter.openai_embeddings(None)  # type: ignore[arg-type]

    async def test_legacy_completions_endpoint_not_supported(self):
        """DeepSeek does not support the legacy /v1/completions endpoint."""
        config = DeepSeekImplConfig(api_key="test-key")
        adapter = DeepSeekInferenceAdapter(config=config)

        params = OpenAICompletionRequestWithExtraBody(model="deepseek-chat", prompt="Hello")

        with pytest.raises(NotImplementedError, match="does not support /v1/completions endpoint"):
            await adapter.openai_completion(params)


class TestDeepSeekReasoning:
    """Tests for DeepSeek thinking-mode reasoning extraction."""

    async def test_reasoning_stream_extracts_reasoning_content(self):
        """Chunks carrying DeepSeek's `reasoning_content` delta must be wrapped
        so the Responses layer can emit reasoning items (thinking display)."""
        from ogx_api import OpenAIChatCompletionRequestWithExtraBody
        from ogx_api.inference.models import OpenAIChatCompletionChunkWithReasoning

        config = DeepSeekImplConfig(api_key="test-key")
        adapter = DeepSeekInferenceAdapter(config=config)

        class FakeDelta:
            reasoning_content = "Let me think..."

        class FakeChoice:
            delta = FakeDelta()

        class FakeChunk:
            id = "chunk_1"
            created = 0
            model = "deepseek-chat"
            choices = [FakeChoice()]
            service_tier = None
            usage = None

        async def fake_stream():
            yield FakeChunk()

        async def fake_chat_completion(params):  # noqa: ANN001
            return fake_stream()

        params = OpenAIChatCompletionRequestWithExtraBody(
            model="deepseek-chat", messages=[{"role": "user", "content": "hi"}], stream=True
        )
        adapter.openai_chat_completion = fake_chat_completion  # type: ignore[method-assign]

        result = await adapter.openai_chat_completions_with_reasoning(params)
        assert hasattr(result, "__aiter__")

        chunks = [c async for c in result]
        assert len(chunks) == 1
        assert isinstance(chunks[0], OpenAIChatCompletionChunkWithReasoning)
        assert chunks[0].reasoning_content == "Let me think..."

    async def test_reasoning_non_streaming_raises(self):
        from ogx_api import OpenAIChatCompletionRequestWithExtraBody

        config = DeepSeekImplConfig(api_key="test-key")
        adapter = DeepSeekInferenceAdapter(config=config)
        params = OpenAIChatCompletionRequestWithExtraBody(
            model="deepseek-chat", messages=[{"role": "user", "content": "hi"}], stream=False
        )

        with pytest.raises(NotImplementedError, match="Non-streaming reasoning is not yet supported"):
            await adapter.openai_chat_completions_with_reasoning(params)
