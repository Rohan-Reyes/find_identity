"""Asynchronous username reconnaissance module with strict false-positive prevention."""

import asyncio
import random
from typing import AsyncGenerator, Dict, List, Optional
import httpx

from config import PLATFORMS, USER_AGENTS, PlatformRule


class UsernameScanner:
    """Scans public platforms asynchronously for existing usernames."""

    def __init__(self, max_concurrency: int = 5, timeout: float = 10.0):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    async def _check_platform(
        self, client: httpx.AsyncClient, username: str, platform: PlatformRule
    ) -> Dict[str, Optional[str | bool]]:
        """Validates if a target username exists on a single platform."""
        profile_url = platform.url_pattern.format(username)
        query_url = (
            platform.check_url_pattern.format(username)
            if platform.check_url_pattern
            else profile_url
        )

        async with self.semaphore:
            await asyncio.sleep(random.uniform(0.1, 0.3))
            try:
                response = await client.get(
                    query_url,
                    headers=self._get_headers(),
                    follow_redirects=True,
                    timeout=self.timeout,
                )

                # 1. Status Code Validation
                if platform.error_type == "status_code":
                    if response.status_code == 200:
                        return {"platform": platform.name, "url": profile_url, "found": True}
                    return {"platform": platform.name, "url": profile_url, "found": False}

                # 2. Negative Marker Filtering (e.g. Pinterest, Wikipedia, HackerNews)
                if platform.error_type == "message":
                    if response.status_code == 200:
                        body_lower = response.text.lower()
                        for marker in platform.not_contains_markers:
                            if marker.lower() in body_lower:
                                return {"platform": platform.name, "url": profile_url, "found": False}
                        return {"platform": platform.name, "url": profile_url, "found": True}
                    return {"platform": platform.name, "url": profile_url, "found": False}

                # 3. Positive & Negative Marker Validation (e.g. Telegram, TikTok)
                if platform.error_type == "contains":
                    if response.status_code == 200:
                        body_lower = response.text.lower()
                        for marker in platform.not_contains_markers:
                            if marker.lower() in body_lower:
                                return {"platform": platform.name, "url": profile_url, "found": False}
                        if platform.must_contain_marker and platform.must_contain_marker.lower() in body_lower:
                            return {"platform": platform.name, "url": profile_url, "found": True}
                    return {"platform": platform.name, "url": profile_url, "found": False}

            except (httpx.TimeoutException, httpx.RequestError):
                pass

        return {"platform": platform.name, "url": profile_url, "found": False}

    async def scan(self, username: str) -> List[Dict[str, str]]:
        """Batch scan for CLI tool."""
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        async with httpx.AsyncClient(limits=limits) as client:
            tasks = [
                self._check_platform(client, username, platform)
                for platform in PLATFORMS
            ]
            results = await asyncio.gather(*tasks)

        return [
            {"platform": str(res["platform"]), "url": str(res["url"]), "status": "Found"}
            for res in results
            if res.get("found")
        ]

    async def stream_scan(self, username: str) -> AsyncGenerator[Dict[str, Optional[str | bool]], None]:
        """Yields results one-by-one as each platform responds (for SSE GUI)."""
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
        async with httpx.AsyncClient(limits=limits) as client:
            tasks = [
                asyncio.create_task(self._check_platform(client, username, platform))
                for platform in PLATFORMS
            ]
            for future in asyncio.as_completed(tasks):
                yield await future
