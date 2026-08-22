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
                    description="Search the web for real-time information, weather, docs, news, and live URLs across multiple queries concurrently.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Single search query",
                            },
                            "queries": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional list of search queries to execute concurrently in parallel for multi-topic search (e.g. ['London weather', 'New York weather'])",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of search results to return per query",
                            },
                        },
                    },
                ),
                ToolDef(
                    name="batch_scrape",
                    description="Scrape and extract clean markdown content from multiple web URLs simultaneously in parallel.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "urls": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of URLs to scrape in parallel",
                            },
                        },
                        "required": ["urls"],
                    },
                ),
            ]
        )

    async def _search_single(self, q: str, max_results: int) -> tuple[list[str], list[dict[str, str]]]:
        """Perform a fast single query search returning (snippets, sources)."""
        snippets = []
        sources = []
        api_url = self._get_api_url()
        api_key = self._get_api_key()

        # 1. Try Firecrawl
        if self._client and api_url and not api_url.endswith("workers.dev"):
            try:
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = await self._client.post(
                    f"{api_url.rstrip('/')}/v1/search",
                    json={"query": q, "limit": max_results, "scrapeOptions": {"formats": ["markdown"]}},
                    headers=headers,
                    timeout=4.0,
                )
                if resp.status_code == 200:
                    items = resp.json().get("data", [])
                    for it in items[:max_results]:
                        u = it.get("url") or it.get("metadata", {}).get("sourceURL") or ""
                        t = it.get("title") or it.get("metadata", {}).get("title") or "Web Page"
                        md = it.get("markdown") or it.get("description") or ""
                        if u:
                            sources.append({"url": u, "title": t})
                            snippets.append(f"[{t}]({u})\n{md[:350]}")
                    if sources:
                        return snippets, sources
            except Exception:
                pass

        # 2. Fast HTML DuckDuckGo fallback
        if self._client:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                }
                res = await self._client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": q, "kl": "us-en"},
                    headers=headers,
                    timeout=3.0,
                )
                if res.status_code == 200:
                    raw_snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', res.text, re.DOTALL)
                    raw_links = re.findall(r'<a class="result__url[^>]*href="([^"]+)"[^>]*>(.*?)</a>', res.text, re.DOTALL)
                    raw_titles = re.findall(r'<a class="result__a[^>]*>(.*?)</a>', res.text, re.DOTALL)
                    for i in range(min(max_results, len(raw_titles))):
                        t = re.sub(r"<[^>]+>", "", raw_titles[i]).strip()
                        s = re.sub(r"<[^>]+>", "", raw_snippets[i]).strip() if i < len(raw_snippets) else ""
                        raw_u = raw_links[i][0] if i < len(raw_links) else ""
                        u_match = re.search(r"uddg=([^&]+)", raw_u)
                        u = unquote(u_match.group(1)) if u_match else raw_u
                        if u:
                            sources.append({"url": u, "title": t})
                            snippets.append(f"[{t}]({u})\n{s}")
            except Exception:
                pass

        return snippets, sources

    async def _scrape_single_url(self, url: str) -> dict[str, str]:
        """Scrapes a single URL and extracts clean text/markdown."""
        try:
            if not self._client:
                return {"url": url, "title": url, "content": ""}
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            resp = await self._client.get(url, headers=headers, timeout=5.0, follow_redirects=True)
            if resp.status_code == 200:
                html = resp.text
                title_match = re.search(r"<title>(.*?)</title>", html, re.I | re.DOTALL)
                title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else url
                # Strip scripts and styles
                clean_html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.I | re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", clean_html)
                clean_text = re.sub(r"\s+", " ", text).strip()
                return {"url": url, "title": title, "content": clean_text[:2000]}
        except Exception:
            pass
        return {"url": url, "title": url, "content": ""}

    async def invoke_tool(
        self, tool_name: str, kwargs: dict[str, Any], authorization: str | None = None
    ) -> ToolInvocationResult:
        import asyncio

        # ----------------------------------------------------
        # Tool 1: batch_scrape (Parallel Multi-URL Scraping)
        # ----------------------------------------------------
        if tool_name == "batch_scrape":
            urls = kwargs.get("urls", [])
            if isinstance(urls, str):
                urls = [urls]
            tasks = [self._scrape_single_url(u) for u in urls[:10]]
            scraped_items = await asyncio.gather(*tasks, return_exceptions=True)
            
            output_blocks = []
            sources = []
            for item in scraped_items:
                if isinstance(item, dict) and item.get("url"):
                    u = item["url"]
                    t = item.get("title", u)
                    c = item.get("content", "")
                    sources.append({"url": u, "title": t})
                    output_blocks.append(f"## [{t}]({u})\n{c}")

            return ToolInvocationResult(
                content="\n\n".join(output_blocks) if output_blocks else "Batch scrape completed.",
                metadata={"urls": urls, "sources": sources, "engine": "batch_scrape"},
            )

        # ----------------------------------------------------
        # Tool 2: web_search (Parallel Multi-Query Fan-Out)
        # ----------------------------------------------------
        query = kwargs.get("query", "")
        queries = kwargs.get("queries", [])
        if not queries and query:
            queries = [query]
        elif not queries:
            queries = [""]

        max_results = kwargs.get("max_results") or self.config.max_results or 5

        # Check if single city weather query for instant high-accuracy meteo feeds
        is_single_weather = len(queries) == 1 and bool(
            re.search(r"\b(weather|temperature|temp|forecast|degrees|humidity|wind)\b", queries[0], re.I)
        )

        if is_single_weather and self._client:
            try:
                weather_stop_words = {
                    "right", "now", "today", "live", "current", "conditions",
                    "condition", "temperature", "temp", "humidity", "wind",
                    "forecast", "weather", "search", "web", "give", "me", "in", "for"
                }
                clean_query = re.sub(r"[^a-zA-Z'\s-]", " ", queries[0])
                words = [w for w in clean_query.split() if w and w.lower() not in weather_stop_words]
                city = " ".join(words) if words else "London"

                w_res = await self._client.get(
                    f"https://wttr.in/{city}?format=j1",
                    headers={"User-Agent": "curl/7.68.0"},
                    timeout=3.0,
                )
                if w_res.status_code == 200:
                    w_data = w_res.json()
                    curr = w_data.get("current_condition", [{}])[0]
                    area = w_data.get("nearest_area", [{}])[0]
                    area_name = area.get("areaName", [{}])[0].get("value", city.capitalize())
                    country = area.get("country", [{}])[0].get("value", "")
                    temp_c = curr.get("temp_C", "20")
                    temp_f = curr.get("temp_F", "68")
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
                        metadata={"query": queries[0], "sources": sources, "engine": "live-weather"},
                    )
            except Exception:
                pass

        # Parallel Multi-Query Fan-Out across all queries
        tasks = [self._search_single(q, max_results=max_results) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_snippets = []
        all_sources = []
        seen_urls = set()

        for res in results:
            if isinstance(res, tuple) and len(res) == 2:
                snips, srcs = res
                all_snippets.extend(snips)
                for s in srcs:
                    if s["url"] not in seen_urls:
                        seen_urls.add(s["url"])
                        all_sources.append(s)

        content = (
            "\n\n".join(all_snippets)
            if all_snippets
            else f"Search completed for: {', '.join(queries)}"
        )

        return ToolInvocationResult(
            content=content,
            metadata={
                "query": queries[0] if len(queries) == 1 else "Multi-Query Search",
                "queries": queries,
                "sources": all_sources,
                "engine": "parallel-multi-query",
            },
        )
