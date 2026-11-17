"""Platform registry.

Every platform says how to tell a real profile from a missing one. Four kinds:

* ``status``  - HTTP 200 means found, 404/410 (or ``missing_codes``) means missing.
* ``json``    - the endpoint returns JSON and ``exists(data)`` decides.
* ``marker``  - an HTML page that is 200 either way; text markers decide.
* ``manual``  - the site cannot be checked without logging in or running
                JavaScript, so the scan only gives you the link to open.

Anything else (403, 429, a Cloudflare challenge, a timeout) is reported as an
``error`` instead of "not found", so a blocked check is never mistaken for a
missing account.

``known_user`` is a public account that should exist; ``main.py --check-rules``
uses it to tell you when a site changes and a rule stops working.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

CATEGORIES = {
    "code": "Code & dev",
    "social": "Social",
    "writing": "Writing & community",
    "creative": "Music, video & art",
    "gaming": "Games & hobbies",
}


@dataclass(frozen=True)
class Platform:
    name: str
    category: str
    profile_url: str  # what the user opens; {} is the username
    kind: str = "status"
    check_url: Optional[str] = None  # what the scanner requests, if different
    missing_codes: tuple[int, ...] = (404, 410)
    must_contain: tuple[str, ...] = ()
    not_contains: tuple[str, ...] = ()
    exists: Optional[Callable[[Any], bool]] = None
    pattern: str = r"^[A-Za-z0-9._-]{1,40}$"  # usernames this site can hold
    client: str = "browser"  # "browser" UA for pages, "tool" UA for APIs
    known_user: str = ""
    notes: str = ""

    def accepts(self, username: str) -> bool:
        return re.fullmatch(self.pattern, username) is not None

    @property
    def method(self) -> str:
        return {
            "status": "HTTP status",
            "json": "Public API",
            "marker": "Page markers",
            "manual": "Open manually",
        }[self.kind]


SUBDOMAIN = r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}[A-Za-z0-9]$|^[A-Za-z0-9]$"
NO_DOTS = r"^[A-Za-z0-9_-]{1,40}$"
ALNUM_UNDERSCORE = r"^[A-Za-z0-9_]{1,40}$"


def _list_not_empty(key: str) -> Callable[[Any], bool]:
    return lambda d: isinstance(d, dict) and bool(d.get(key))


PLATFORMS: list[Platform] = [
    # ---- Code & dev -------------------------------------------------------
    Platform("GitHub", "code", "https://github.com/{}", pattern=r"^[A-Za-z0-9-]{1,39}$",
             known_user="torvalds"),
    Platform("GitLab", "code", "https://gitlab.com/{}", kind="json",
             check_url="https://gitlab.com/api/v4/users?username={}",
             exists=lambda d: isinstance(d, list) and len(d) > 0, client="tool",
             known_user="sytses"),
    Platform("Bitbucket", "code", "https://bitbucket.org/{}/",
             check_url="https://api.bitbucket.org/2.0/workspaces/{}", client="tool",
             known_user="atlassian"),
    Platform("Codeberg", "code", "https://codeberg.org/{}",
             check_url="https://codeberg.org/api/v1/users/{}", client="tool",
             known_user="forgejo"),
    Platform("SourceHut", "code", "https://sr.ht/~{}/", client="tool", known_user="sircmpwn"),
    Platform("Docker Hub", "code", "https://hub.docker.com/u/{}",
             check_url="https://hub.docker.com/v2/users/{}/", client="tool",
             known_user="library"),
    Platform("Hugging Face", "code", "https://huggingface.co/{}",
             check_url="https://huggingface.co/api/users/{}/overview", client="tool",
             known_user="julien-c"),
    Platform("npm", "code", "https://www.npmjs.com/~{}", kind="json",
             check_url="https://registry.npmjs.org/-/v1/search?text=maintainer:{}&size=1",
             exists=_list_not_empty("objects"), client="tool",
             known_user="sindresorhus", notes="Only finds people who maintain at least one package."),
    Platform("Dev.to", "code", "https://dev.to/{}",
             check_url="https://dev.to/api/users/by_username?url={}", client="tool",
             known_user="ben"),
    Platform("Replit", "code", "https://replit.com/@{}", known_user="torvalds"),
    Platform("Kaggle", "code", "https://www.kaggle.com/{}", known_user="torvalds"),
    Platform("Codewars", "code", "https://www.codewars.com/users/{}",
             check_url="https://www.codewars.com/api/v1/users/{}", client="tool",
             known_user="jhoffner"),
    Platform("HackerRank", "code", "https://www.hackerrank.com/profile/{}",
             check_url="https://www.hackerrank.com/rest/contests/master/hackers/{}/profile",
             known_user="torvalds"),
    Platform("Keybase", "code", "https://keybase.io/{}", kind="json",
             check_url="https://keybase.io/_/api/1.0/user/lookup.json?usernames={}",
             exists=lambda d: isinstance(d, dict) and any(d.get("them") or []),
             pattern=ALNUM_UNDERSCORE, client="tool", known_user="chris"),
    # ---- Social -----------------------------------------------------------
    Platform("Mastodon (mastodon.social)", "social", "https://mastodon.social/@{}",
             check_url="https://mastodon.social/api/v1/accounts/lookup?acct={}",
             pattern=ALNUM_UNDERSCORE, client="tool", known_user="Gargron"),
    Platform("Bluesky", "social", "https://bsky.app/profile/{}.bsky.social",
             check_url="https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={}.bsky.social",
             missing_codes=(400, 404), pattern=r"^[A-Za-z0-9-]{1,40}$", client="tool",
             known_user="jay"),
    Platform("X (Twitter)", "social", "https://x.com/{}", pattern=r"^[A-Za-z0-9_]{1,15}$",
             known_user="nasa", notes="Only the HTTP status is checked; X sometimes changes this."),
    Platform("Telegram", "social", "https://t.me/{}", kind="marker",
             must_contain=("tgme_page_title",), pattern=r"^[A-Za-z0-9_]{5,32}$",
             known_user="durov"),
    Platform("TikTok", "social", "https://www.tiktok.com/@{}",
             check_url="https://www.tiktok.com/oembed?url=https://www.tiktok.com/@{}",
             missing_codes=(400, 404), pattern=r"^[A-Za-z0-9._]{2,24}$", client="tool",
             known_user="tiktok"),
    Platform("Pinterest", "social", "https://www.pinterest.com/{}/", kind="marker",
             not_contains=("user not found",), pattern=r"^[A-Za-z0-9_]{3,30}$",
             known_user="pinterest"),
    Platform("YouTube", "social", "https://www.youtube.com/@{}", known_user="youtube"),
    Platform("Reddit", "social", "https://www.reddit.com/user/{}", kind="manual",
             pattern=r"^[A-Za-z0-9_-]{3,20}$", notes="Reddit blocks unauthenticated checks."),
    Platform("Instagram", "social", "https://www.instagram.com/{}/", kind="manual",
             pattern=r"^[A-Za-z0-9._]{1,30}$", notes="Needs a logged-in browser."),
    Platform("Threads", "social", "https://www.threads.net/@{}", kind="manual",
             pattern=r"^[A-Za-z0-9._]{1,30}$", notes="Needs a logged-in browser."),
    Platform("Facebook", "social", "https://www.facebook.com/{}", kind="manual",
             pattern=r"^[A-Za-z0-9.]{5,50}$", notes="Needs a logged-in browser."),
    Platform("LinkedIn", "social", "https://www.linkedin.com/in/{}", kind="manual",
             pattern=r"^[A-Za-z0-9-]{3,100}$", notes="Needs a logged-in browser."),
    # ---- Writing & community ---------------------------------------------
    Platform("Medium", "writing", "https://medium.com/@{}",
             check_url="https://medium.com/feed/@{}", known_user="medium"),
    Platform("Substack", "writing", "https://{}.substack.com/", pattern=SUBDOMAIN,
             known_user="platformer"),
    Platform("Hacker News", "writing", "https://news.ycombinator.com/user?id={}", kind="json",
             check_url="https://hacker-news.firebaseio.com/v0/user/{}.json",
             exists=lambda d: isinstance(d, dict) and bool(d.get("id")),
             pattern=r"^[A-Za-z0-9_-]{2,15}$", client="tool", known_user="pg"),
    Platform("Wikipedia", "writing", "https://en.wikipedia.org/wiki/User:{}", kind="json",
             check_url="https://en.wikipedia.org/w/api.php?action=query&list=users&ususers={}&format=json",
             exists=lambda d: any("missing" not in u and "invalid" not in u
                                  for u in d.get("query", {}).get("users", [])),
             client="tool", known_user="Jimbo_Wales"),
    Platform("Patreon", "writing", "https://www.patreon.com/{}", pattern=NO_DOTS,
             known_user="patreon"),
    Platform("Duolingo", "writing", "https://www.duolingo.com/profile/{}", kind="json",
             check_url="https://www.duolingo.com/2017-06-30/users?username={}",
             exists=_list_not_empty("users"), client="tool", known_user="luis"),
    # ---- Music, video & art ----------------------------------------------
    Platform("SoundCloud", "creative", "https://soundcloud.com/{}", known_user="soundcloud"),
    Platform("Vimeo", "creative", "https://vimeo.com/{}", known_user="staff"),
    Platform("Dribbble", "creative", "https://dribbble.com/{}", known_user="dribbble"),
    Platform("Flickr", "creative", "https://www.flickr.com/people/{}/", known_user="flickr"),
    Platform("Twitch", "creative", "https://www.twitch.tv/{}", kind="manual",
             pattern=r"^[A-Za-z0-9_]{4,25}$", notes="Profile pages are rendered with JavaScript."),
    # ---- Games & hobbies --------------------------------------------------
    Platform("Steam", "gaming", "https://steamcommunity.com/id/{}", kind="marker",
             not_contains=("the specified profile could not be found",),
             known_user="gabelogannewell"),
    Platform("Lichess", "gaming", "https://lichess.org/@/{}",
             check_url="https://lichess.org/api/user/{}", client="tool",
             known_user="thibault"),
    Platform("Chess.com", "gaming", "https://www.chess.com/member/{}",
             check_url="https://api.chess.com/pub/player/{}", client="tool",
             known_user="hikaru"),
    Platform("itch.io", "gaming", "https://{}.itch.io/", pattern=SUBDOMAIN, known_user="leafo"),
    Platform("Monkeytype", "gaming", "https://monkeytype.com/profile/{}",
             check_url="https://api.monkeytype.com/users/{}/profile", client="tool",
             known_user="miodec"),
]

BY_NAME = {p.name: p for p in PLATFORMS}


def select(categories: Optional[list[str]] = None, names: Optional[list[str]] = None) -> list[Platform]:
    """Platforms filtered by category keys and/or platform names (case-insensitive)."""
    out = PLATFORMS
    if categories:
        cats = {c.lower() for c in categories}
        out = [p for p in out if p.category in cats]
    if names:
        wanted = {n.lower() for n in names}
        out = [p for p in out if p.name.lower() in wanted]
    return out
