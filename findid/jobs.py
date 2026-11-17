"""Background scan jobs.

A scan runs as its own asyncio task and appends events to a list. Browsers read
the list over Server-Sent Events from any position, so a dropped connection
resumes where it left off instead of starting the scan again. When the scan
ends it is saved as a report.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from . import __version__, config, imaging, reports, reverse
from .platforms import BY_NAME, Platform
from .recon import Scanner

MAX_LIVE_JOBS = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Job:
    def __init__(self, report: dict, platforms: list[Platform], checks: list[tuple[Platform, str]],
                 images: list[dict]):
        self.id = report["id"]
        self.report = report
        self.platforms = platforms
        self.checks = checks  # (platform, username) pairs to run
        self.images = images  # {"index", "filename", "data", "source_url"}
        self.events: list[dict] = []
        self.changed = asyncio.Event()
        self.done = False
        self.task: Optional[asyncio.Task] = None
        self.total = len(checks) + len(images)
        self.completed = 0

    def emit(self, kind: str, **data: Any) -> None:
        data.update(type=kind, seq=len(self.events), completed=self.completed, total=self.total)
        self.events.append(data)
        self.changed.set()
        self.changed = asyncio.Event()

    async def run(self) -> None:
        status = "done"
        try:
            self.emit("start", report_id=self.id, query=self.report["query"])
            await self._profiles()
            await self._images()
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception as exc:  # never leave a scan hanging
            status = "error"
            self.emit("problem", message=f"Scan stopped: {exc}")
        finally:
            for img in self.images:
                img.pop("data", None)
            self.report["status"] = status
            self.report["finished"] = _now()
            self.report["similar"] = imaging.similar_pairs(self.report["images"])
            reports.save(self.report)
            self.done = True
            self.emit("end", status=status, summary=self.report["summary"],
                      similar=self.report["similar"])

    async def _profiles(self) -> None:
        if not self.checks:
            return
        scanner = Scanner()
        rows = {(r["platform"], r["username"]): r for r in self.report["profiles"]}
        async with scanner.client() as client:
            tasks = [asyncio.create_task(scanner.check(client, p, u)) for p, u in self.checks]
            try:
                for fut in asyncio.as_completed(tasks):
                    row = await fut
                    rows[(row["platform"], row["username"])] = row
                    self.report["profiles"] = list(rows.values())
                    self.completed += 1
                    self.emit("profile", row=row)
            finally:
                for t in tasks:
                    t.cancel()

    async def _images(self) -> None:
        for img in self.images:
            self.emit("image_start", filename=img["filename"])
            entry: dict[str, Any] = {"index": img["index"], "filename": img["filename"],
                                     "source_url": img.get("source_url")}
            try:
                entry.update(await asyncio.to_thread(imaging.analyse, img["data"], img["filename"]))
                entry["links"] = reverse.engine_links(img.get("source_url"))
                lens = await reverse.google_lens(img["data"], img.get("source_url"))
                entry["matches"] = lens["matches"]
                entry["lens_error"] = lens.get("error")
                entry["lens_used"] = not lens.get("skipped")
            except imaging.ImageError as exc:
                entry["error"] = str(exc)
            self.report["images"].append(entry)
            self.completed += 1
            self.emit("image", image=entry)


JOBS: dict[str, Job] = {}


def _forget_old() -> None:
    finished = [j for j in JOBS.values() if j.done]
    for job in finished[: max(0, len(JOBS) - MAX_LIVE_JOBS)]:
        JOBS.pop(job.id, None)


def start(usernames: list[str], variants: dict[str, list[str]], platforms: list[Platform],
          images: list[dict], categories: list[str], label: str = "") -> Job:
    """Create the report, save uploads, and launch the scan."""
    config.ensure_dirs()
    report_id = secrets.token_hex(6)
    all_names = usernames + [v for vs in variants.values() for v in vs]
    folder = config.UPLOADS_DIR / report_id
    for img in images:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{img['index']}.jpg").write_bytes(imaging.thumbnail(img["data"]))
    report = {
        "id": report_id,
        "version": __version__,
        "created": _now(),
        "status": "running",
        "label": label[:80],
        "query": {
            "usernames": usernames,
            "variants": variants,
            "categories": categories,
            "platforms": [p.name for p in platforms],
            "images": [i["filename"] for i in images],
        },
        "profiles": [],
        "images": [],
        "similar": [],
    }
    job = Job(report, platforms, [(p, u) for u in all_names for p in platforms], images)
    _launch(job)
    return job


def retry_errors(report: dict) -> Optional[Job]:
    """Re-run only the checks that failed last time, updating the same report."""
    if report["id"] in JOBS and not JOBS[report["id"]].done:
        return None
    checks = [(BY_NAME[r["platform"]], r["username"]) for r in report.get("profiles", [])
              if r["status"] == "error" and r["platform"] in BY_NAME]
    report["status"] = "running"
    job = Job(report, [], checks, [])  # no new images: existing image results are kept
    _launch(job)
    return job


def _launch(job: Job) -> None:
    JOBS[job.id] = job
    _forget_old()
    job.task = asyncio.get_running_loop().create_task(job.run())


def cancel(report_id: str) -> bool:
    job = JOBS.get(report_id)
    if job and job.task and not job.done:
        job.task.cancel()
        return True
    return False
