"""Reverse image search: SerpApi Google Lens, engine links, and safe image download."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlparse

import httpx

from . import config, imaging

SERPAPI_UPLOAD = "https://serpapi.com/image"
SERPAPI_SEARCH = "https://serpapi.com/search.json"


def engine_links(image_url: Optional[str] = None) -> list[dict]:
    """Reverse-search engines. With a public URL the links run the search directly;
    for local files they open the engine's upload page."""
    if image_url:
        u = quote(image_url, safe="")
        return [
            {"engine": "Google Lens", "url": f"https://lens.google.com/uploadbyurl?url={u}", "direct": True},
            {"engine": "Bing Visual Search", "url": f"https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{u}", "direct": True},
            {"engine": "Yandex Images", "url": f"https://yandex.com/images/search?rpt=imageview&url={u}", "direct": True},
            {"engine": "TinEye", "url": f"https://tineye.com/search?url={u}", "direct": True},
        ]
    return [
        {"engine": "Google Lens", "url": "https://lens.google.com/", "direct": False},
        {"engine": "Bing Visual Search", "url": "https://www.bing.com/visualsearch", "direct": False},
        {"engine": "Yandex Images", "url": "https://yandex.com/images/", "direct": False},
        {"engine": "TinEye", "url": "https://tineye.com/", "direct": False},
    ]


def _is_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            return False
    return True


async def download_image(url: str, max_mb: int = config.MAX_IMAGE_MB) -> bytes:
    """Fetch a public image URL. Refuses private/loopback addresses (also after
    redirects) and anything over the size limit."""
    limit = max_mb * 1024 * 1024
    async with httpx.AsyncClient(timeout=20, follow_redirects=False,
                                 headers={"User-Agent": config.BROWSER_UA}) as client:
        for _ in range(5):
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError("Only http(s) image links are supported.")
            if not await asyncio.to_thread(_is_public, parsed.hostname):
                raise ValueError("That address is not a public website.")
            async with client.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                if r.status_code != 200:
                    raise ValueError(f"The link returned HTTP {r.status_code}.")
                if int(r.headers.get("content-length") or 0) > limit:
                    raise ValueError(f"The image is larger than {max_mb} MB.")
                chunks, size = [], 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise ValueError(f"The image is larger than {max_mb} MB.")
                    chunks.append(chunk)
                return b"".join(chunks)
        raise ValueError("Too many redirects.")


def _parse_lens(data: dict) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for key, kind in (("exact_matches", "exact"), ("visual_matches", "visual"), ("organic_results", "page")):
        for item in data.get(key) or []:
            link = item.get("link") or ""
            if not link.startswith(("http://", "https://")) or link in seen:
                continue
            seen.add(link)
            out.append({
                "title": (item.get("title") or "Untitled")[:200],
                "url": link,
                "source": item.get("source") or urlparse(link).hostname or "",
                "thumbnail": item.get("thumbnail") if str(item.get("thumbnail", "")).startswith("https://") else "",
                "kind": kind,
            })
    return out[:60]


async def google_lens(data: bytes, image_url: Optional[str] = None,
                      api_key: str = config.SERPAPI_API_KEY) -> dict[str, Any]:
    """Run a Google Lens search through SerpApi. Returns {matches, error}."""
    if not api_key:
        return {"matches": [], "error": None, "skipped": True}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            params: dict[str, str] = {"engine": "google_lens", "api_key": api_key, "hl": "en"}
            if image_url:
                params["url"] = image_url
            else:
                body, mime = await asyncio.to_thread(imaging.for_upload, data)
                ext = mime.split("/")[1]
                up = await client.post(SERPAPI_UPLOAD, data={"api_key": api_key},
                                       files={"image": (f"image.{ext}", body, mime)})
                if up.status_code != 200 or not up.json().get("image_id"):
                    return {"matches": [], "error": f"SerpApi upload failed (HTTP {up.status_code})."}
                params["image_id"] = up.json()["image_id"]
            res = await client.get(SERPAPI_SEARCH, params=params)
            payload = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            if res.status_code != 200:
                return {"matches": [], "error": payload.get("error") or f"Google Lens returned HTTP {res.status_code}."}
            return {"matches": _parse_lens(payload), "error": None}
    except (httpx.HTTPError, ValueError) as exc:
        return {"matches": [], "error": f"Google Lens search failed: {exc}"}
