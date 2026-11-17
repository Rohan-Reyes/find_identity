"""Username checks across the platform registry."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import AsyncIterator, Iterable, Optional
from urllib.parse import quote

import httpx

from . import config
from .platforms import PLATFORMS, Platform

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
CHALLENGE_MARKERS = ("<title>just a moment...</title>", "cf-challenge", "captcha")


def parse_usernames(text: str) -> tuple[list[str], list[str]]:
    """Split free text into (valid, rejected) usernames, de-duplicated in order."""
    valid: list[str] = []
    rejected: list[str] = []
    for token in re.split(r"[\s,;]+", text or ""):
        token = token.strip().lstrip("@")
        if not token:
            continue
        target = valid if USERNAME_RE.fullmatch(token) else rejected
        if token.lower() not in {t.lower() for t in target}:
            target.append(token)
    return valid, rejected


def variants(username: str, limit: int = 6) -> list[str]:
    """Common spellings of the same handle: john.doe -> johndoe, john_doe, john-doe."""
    parts = [p for p in re.split(r"[._-]+", username) if p]
    out: list[str] = []

    def add(v: str) -> None:
        if v and v.lower() != username.lower() and v.lower() not in {o.lower() for o in out}:
            out.append(v)

    if len(parts) > 1:
        for sep in ("", "_", ".", "-"):
            add(sep.join(parts))
        add(parts[0][0] + "".join(parts[1:]))  # jdoe
        add(parts[0] + parts[-1][0])  # johnd
    stripped = re.sub(r"\d+$", "", username)
    if stripped and stripped != username:
        add(stripped)  # johndoe99 -> johndoe
    if username != username.lower():
        add(username.lower())
    return out[:limit]


def _result(p: Platform, username: str, status: str, detail: str = "", ms: int = 0) -> dict:
    return {
        "platform": p.name,
        "category": p.category,
        "username": username,
        "url": p.profile_url.format(quote(username, safe="")),
        "status": status,  # found | not_found | error | manual | skipped
        "detail": detail,
        "ms": ms,
    }


def judge(p: Platform, status_code: int, body: str) -> tuple[str, str]:
    """Decide found / not_found / error from a response. Pure, so it is unit-tested."""
    low = body.lower()
    if status_code == 429:
        return "error", "Rate limited (HTTP 429)"
    if status_code in (401, 403) or (status_code == 503 and any(m in low for m in CHALLENGE_MARKERS)):
        return "error", f"Blocked by the site (HTTP {status_code})"
    if status_code >= 500:
        return "error", f"Site error (HTTP {status_code})"

    if p.kind == "status":
        if status_code == 200:
            if any(m in low for m in CHALLENGE_MARKERS[:1]):
                return "error", "Bot challenge page"
            return "found", ""
        if status_code in p.missing_codes:
            return "not_found", ""
        return "error", f"Unexpected HTTP {status_code}"

    if p.kind == "json":
        if status_code in p.missing_codes:
            return "not_found", ""
        if status_code != 200:
            return "error", f"Unexpected HTTP {status_code}"
        try:
            data = json.loads(body)
        except ValueError:
            return "error", "Response was not JSON"
        try:
            return ("found", "") if p.exists and p.exists(data) else ("not_found", "")
        except Exception:  # an API changed shape
            return "error", "Unexpected API response"

    if p.kind == "marker":
        if status_code in p.missing_codes:
            return "not_found", ""
        if status_code != 200:
            return "error", f"Unexpected HTTP {status_code}"
        if any(m in low for m in CHALLENGE_MARKERS[:1]):
            return "error", "Bot challenge page"
        if any(m.lower() in low for m in p.not_contains):
            return "not_found", ""
        if p.must_contain and not all(m.lower() in low for m in p.must_contain):
            return "not_found", ""
        return "found", ""

    return "manual", p.notes


class Scanner:
    def __init__(self, concurrency: int = config.CONCURRENCY, timeout: float = config.TIMEOUT,
                 transport: Optional[httpx.AsyncBaseTransport] = None):
        self.semaphore = asyncio.Semaphore(concurrency)
        self.timeout = timeout
        self.transport = transport  # tests inject httpx.MockTransport

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            limits=httpx.Limits(max_connections=max(10, config.CONCURRENCY * 2)),
            follow_redirects=True,
            timeout=self.timeout,
        )

    async def check(self, client: httpx.AsyncClient, p: Platform, username: str) -> dict:
        if not p.accepts(username):
            return _result(p, username, "skipped", "Not a valid username on this site")
        if p.kind == "manual":
            return _result(p, username, "manual", p.notes)

        url = (p.check_url or p.profile_url).format(quote(username, safe=""))
        headers = {
            "User-Agent": config.BROWSER_UA if p.client == "browser" else config.TOOL_UA,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "application/json" if p.client == "tool"
            else "text/html,application/xhtml+xml,*/*;q=0.8",
        }
        async with self.semaphore:
            start = time.perf_counter()
            last_error = ""
            for attempt in range(2):  # one retry for network blips
                try:
                    r = await client.get(url, headers=headers)
                    status, detail = judge(p, r.status_code, r.text)
                    return _result(p, username, status, detail, int((time.perf_counter() - start) * 1000))
                except httpx.TimeoutException:
                    last_error = "Timed out"
                except httpx.HTTPError as exc:
                    last_error = f"Network error: {type(exc).__name__}"
                if attempt == 0:
                    await asyncio.sleep(0.6)
            return _result(p, username, "error", last_error, int((time.perf_counter() - start) * 1000))

    async def stream(self, usernames: Iterable[str],
                     platforms: Optional[list[Platform]] = None) -> AsyncIterator[dict]:
        """Yield each result as soon as it arrives."""
        platforms = platforms or PLATFORMS
        async with self.client() as client:
            tasks = [asyncio.create_task(self.check(client, p, u)) for u in usernames for p in platforms]
            try:
                for fut in asyncio.as_completed(tasks):
                    yield await fut
            finally:
                for t in tasks:
                    t.cancel()

    async def scan(self, usernames: Iterable[str], platforms: Optional[list[Platform]] = None) -> list[dict]:
        return [r async for r in self.stream(usernames, platforms)]


async def check_rules(platforms: Optional[list[Platform]] = None, transport=None) -> list[dict]:
    """Health check: each rule's known account must be found and a random name must not."""
    import secrets

    platforms = [p for p in (platforms or PLATFORMS) if p.kind != "manual" and p.known_user]
    fake = "zq" + secrets.token_hex(6)
    scanner = Scanner(transport=transport)
    async with scanner.client() as client:
        real = await asyncio.gather(*[scanner.check(client, p, p.known_user) for p in platforms])
        miss = await asyncio.gather(*[scanner.check(client, p, fake) for p in platforms])
    out = []
    for p, a, b in zip(platforms, real, miss):
        if a["status"] == "error" or b["status"] == "error":
            health = "blocked"
        elif a["status"] == "found" and b["status"] == "not_found":
            health = "ok"
        else:
            health = "broken"
        out.append({
            "platform": p.name,
            "health": health,
            "known_user": p.known_user,
            "known_result": a["status"],
            "random_result": b["status"],
            "detail": a["detail"] or b["detail"],
        })
    return out
