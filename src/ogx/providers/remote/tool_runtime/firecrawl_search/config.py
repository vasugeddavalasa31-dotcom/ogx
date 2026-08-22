# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from typing import Any
from pydantic import Field, SecretStr
from ogx.providers.utils.common.http import BaseToolRuntimeConfig


class FirecrawlSearchToolConfig(BaseToolRuntimeConfig):
    """Configuration for the Firecrawl Search tool runtime."""

    api_url: str = Field(
        default="https://orbiterx-websearch.vasugeddavalasa31.workers.dev",
        description="The base URL of the self-hosted Firecrawl instance or cloud API.",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="The Firecrawl API Key (optional for self-hosted).",
    )
    max_results: int = Field(
        default=5,
        description="The maximum number of results to return",
    )

    @classmethod
    def sample_run_config(cls, __distro_dir__: str) -> dict[str, Any]:
        return {
            "api_url": "${env.FIRECRAWL_API_URL:=https://orbiterx-websearch.vasugeddavalasa31.workers.dev}",
            "api_key": "${env.FIRECRAWL_API_KEY:=}",
            "max_results": 5,
        }
