# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from pydantic import BaseModel, SecretStr

from .config import FirecrawlSearchToolConfig
from .firecrawl_search import FirecrawlSearchToolRuntimeImpl


class FirecrawlSearchToolProviderDataValidator(BaseModel):
    """Validator for Firecrawl Search tool provider data."""

    firecrawl_api_key: SecretStr | None = None
    firecrawl_api_url: str | None = None


async def get_adapter_impl(config: FirecrawlSearchToolConfig, _deps):
    impl = FirecrawlSearchToolRuntimeImpl(config)
    await impl.initialize()
    return impl
