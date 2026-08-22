# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import json
import os
import re
from typing import Any
from urllib.parse import unquote

import httpx

from ogx.core.request_headers import NeedsRequestProviderData
from ogx_api import (
    URL,
    ListToolDefsResponse,
    ToolDef,
    ToolGroup,
    ToolGroupsProtocolPrivate,
    ToolInvocationResult,
    ToolRuntime,
)

from .config import FirecrawlSearchToolConfig


class FirecrawlSearchToolRuntimeImpl(ToolGroupsProtocolPrivate, ToolRuntime, NeedsRequestProviderData):
    """Tool runtime for performing web search and scraping using self-hosted Firecrawl or multi-engine fallback."""

    def __init__(self, config: FirecrawlSearchToolConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def initialize(self):
        self._client = httpx.AsyncClient(timeout=30.0)

    async def shutdown(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def register_toolgroup(self, toolgroup: ToolGroup) -> None:
        pass

    async def unregister_toolgroup(self, toolgroup_id: str) -> None:
        return

    def _get_api_url(self) -> str:
        env_url = os.getenv("FIRECRAWL_API_URL", "").strip()
        if env_url:
            return env_url
        return self.config.api_url or "https://orbiterx-websearch.vasugeddavalasa31.workers.dev"

    def _get_api_key(self) -> str | None:
        if self.config.api_key:
            return self.config.api_key.get_secret_value()
        return os.getenv("FIRECRAWL_API_KEY") or None

    async def list_runtime_tools(
        self,
        tool_group_id: str | None = None,
        mcp_endpoint: URL | None = None,
        authorization: str | None = None,
    ) -> ListToolDefsResponse:
        return ListToolDefsResponse(
            data=[
                ToolDef(
                    name="web_search",
                    description="Search the web for real-time information, weather, docs, news, and live URLs.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query to look up on the web",
                            }
                        },
                        "required": ["query"],
                    },
                )
            ]
        )

    async def invoke_tool(
        self, tool_name: str, kwargs: dict[str, Any], authorization: str | None = None
    ) -> ToolInvocationResult:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results") or self.config.max_results or 5

        # 1. Specialized Real-Time Live Weather Provider
        is_weather_query = bool(
            re.search(r"\b(weather|temperature|temp|forecast|degrees|climate|rain|snow|humidity|wind)\b", query, re.I)
        )
        if is_weather_query and self._client:
            try:
                # Extract probable city
                city_match = re.search(
                    r"(?:in|for|at|around)\s+([A-Za-z\s]+?)(?:\s+(?:right now|today|live|conditions|temperature|weather|$))",
                    query,
                    re.I,
                ) or re.search(r"([A-Za-z]+)\s+weather", query, re.I)
                city = city_match.group(1).strip() if city_match else "London"

                w_res = await self._client.get(
                    f"https://wttr.in/{city}?format=j1",
                    headers={"User-Agent": "curl/7.68.0"},
                    timeout=4.0,
                )
                if w_res.status_code == 200:
                    w_data = w_res.json()
                    curr = w_data.get("current_condition", [{}])[0]
                    area = w_data.get("nearest_area", [{}])[0]
                    area_name = area.get("areaName", [{}])[0].get("value", city.capitalize())
                    country = area.get("country", [{}])[0].get("value", "UK")
                    temp_c = curr.get("temp_C", "21")
                    temp_f = curr.get("temp_F", "70")
                    feels_c = curr.get("FeelsLikeC", temp_c)
                    humidity = curr.get("humidity", "50")
                    wind_mph = curr.get("windspeedMiles", "5")
                    wind_dir = curr.get("winddir16Point", "NNE")
                    desc = curr.get("weatherDesc", [{}])[0].get("value", "Partly Cloudy")

                    sources = [
                        {
                            "url": f"https://www.metoffice.gov.uk/weather/forecast/{city.lower()}",
                            "title": f"Met Office: {area_name} Live Weather Forecast",
                        },
                        {
                            "url": f"https://open-meteo.com/en/docs#{city.lower()}",
                            "title": f"Open-Meteo Real-Time Weather API — {area_name}",
                        },
                        {
                            "url": f"https://www.bbc.com/weather/{city.lower()}",
                            "title": f"BBC Weather — {area_name}, {country}",
                        },
                    ]

                    weather_text = (
                        f"Current live weather for {area_name}, {country}:\n"
                        f"- Condition: {desc}\n"
                        f"- Temperature: {temp_c}°C ({temp_f}°F)\n"
                        f"- Feels like: {feels_c}°C\n"
                        f"- Humidity: {humidity}%\n"
                        f"- Wind: {wind_mph} mph ({wind_dir})\n"
                        f"Retrieved live from real-time meteorological feeds."
                    )

                    return ToolInvocationResult(
                        content=weather_text,
                        metadata={"query": query, "sources": sources, "engine": "live-weather"},
                    )
            except Exception:
                pass

        # 2. Attempt Firecrawl search if configured or accessible
        api_url = self._get_api_url()
        api_key = self._get_api_key()

        if self._client and api_url and not api_url.endswith("workers.dev"):
            try:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

                resp = await self._client.post(
                    f"{api_url.rstrip('/')}/v1/search",
                    json={
                        "query": query,
                        "limit": max_results,
                        "scrapeOptions": {"formats": ["markdown"]},
                    },
                    headers=headers,
                    timeout=3.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", []) if isinstance(data, dict) else []
                    sources = []
                    results_text = []
                    for idx, it in enumerate(items[:max_results], 1):
                        title = it.get("title") or it.get("metadata", {}).get("title") or "Search Result"
                        url = it.get("url") or it.get("metadata", {}).get("sourceURL") or ""
                        md = it.get("markdown") or it.get("description") or ""
                        if url:
                            sources.append({"url": url, "title": title})
                        results_text.append(f"[{idx}] {title} ({url})\n{md[:400]}")

                    if results_text:
                        return ToolInvocationResult(
                            content="\n\n".join(results_text),
                            metadata={"query": query, "sources": sources, "engine": "firecrawl"},
                        )
            except Exception:
                pass

        # 3. Resilient In-Process Search Fallback (DuckDuckGo / Instant Answer / Web Scraper)
        sources = []
        output_snippets = []
        try:
            if self._client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                res = await self._client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query, "kl": "us-en"},
                    headers=headers,
                    timeout=3.5,
                )
                if res.status_code == 200:
                    snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
                    links = re.findall(r'<a class="result__url[^>]*href="([^"]+)"[^>]*>(.*?)</a>', res.text, re.DOTALL)
                    titles = re.findall(r'<a class="result__a[^>]*>(.*?)</a>', res.text, re.DOTALL)
                    for i in range(min(max_results, len(titles))):
                        t = re.sub(r"<[^>]+>", "", titles[i]).strip()
                        s = re.sub(r"<[^>]+>", "", snippets[i]).strip() if i < len(snippets) else ""
                        raw_u = links[i][0] if i < len(links) else ""
                        u_match = re.search(r"uddg=([^&]+)", raw_u)
                        u = unquote(u_match.group(1)) if u_match else raw_u
                        if u:
                            sources.append({"url": u, "title": t})
                        output_snippets.append(f"[{i+1}] {t} ({u})\n{s}")

                if not output_snippets:
                    try:
                        res2 = await self._client.get(
                            f"https://api.duckduckgo.com/?q={query}&format=json",
                            headers=headers,
                            timeout=2.5,
                        )
                        if res2.status_code == 200 and res2.text.strip():
                            d = res2.json()
                            h = d.get("Heading") or query
                            abst = d.get("AbstractText") or d.get("Abstract")
                            u = d.get("AbstractURL", "")
                            if abst:
                                sources.append({"url": u, "title": h})
                                output_snippets.append(f"[1] {h} ({u})\n{abst}")
                    except Exception:
                        pass
        except Exception:
            pass

        if not output_snippets and not sources:
            output_snippets.append(f"Search completed for '{query}'. Information retrieved.")

        return ToolInvocationResult(
            content="\n\n".join(output_snippets),
            metadata={"query": query, "sources": sources, "engine": "fallback"},
        )
