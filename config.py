"""Configuration settings and platform endpoints with strict false-positive prevention."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

# SerpApi Key for visual search (read securely from .env)
SERPAPI_API_KEY: Optional[str] = os.getenv("SERPAPI_API_KEY")

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


@dataclass(frozen=True)
class PlatformRule:
    name: str
    url_pattern: str
    error_type: str = "status_code"  # "status_code" or "message" or "contains"
    check_url_pattern: Optional[str] = None
    not_contains_markers: List[str] = field(default_factory=list)
    must_contain_marker: Optional[str] = None


# Registry of target platforms with robust validation logic
PLATFORMS: List[PlatformRule] = [
    PlatformRule(
        name="GitHub",
        url_pattern="https://github.com/{}",
        error_type="status_code",
    ),
    PlatformRule(
        name="GitLab",
        url_pattern="https://gitlab.com/{}",
        error_type="status_code",
    ),
    PlatformRule(
        name="Medium",
        url_pattern="https://medium.com/@{}",
        check_url_pattern="https://medium.com/feed/@{}",
        error_type="status_code",
    ),
    PlatformRule(
        name="Pinterest",
        url_pattern="https://www.pinterest.com/{}/",
        error_type="message",
        not_contains_markers=[
            "user not found",
            "couldn't find that page",
            "sorry, we couldn't find that page",
        ],
    ),
    PlatformRule(
        name="Wikipedia",
        url_pattern="https://en.wikipedia.org/wiki/User:{}",
        error_type="message",
        not_contains_markers=["does not have a user page"],
    ),
    PlatformRule(
        name="Mastodon Social",
        url_pattern="https://mastodon.social/@{}",
        error_type="status_code",
    ),
    PlatformRule(
        name="Keybase",
        url_pattern="https://keybase.io/{}",
        error_type="status_code",
    ),
    PlatformRule(
        name="Telegram",
        url_pattern="https://t.me/{}",
        error_type="contains",
        must_contain_marker="tgme_page_extra",
    ),
    PlatformRule(
        name="Dev.to",
        url_pattern="https://dev.to/{}",
        error_type="status_code",
    ),
    PlatformRule(
        name="TikTok",
        url_pattern="https://www.tiktok.com/@{}",
        check_url_pattern="https://www.tiktok.com/oembed?url=https://www.tiktok.com/@{}",
        error_type="status_code",
    ),
    PlatformRule(
        name="HackerNews",
        url_pattern="https://news.ycombinator.com/user?id={}",
        error_type="message",
        not_contains_markers=["no such user"],
    ),
]
