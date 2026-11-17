"""Find Identity web app: `python app.py`, then open http://127.0.0.1:8000"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import webbrowser
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from findid import __version__, config, imaging, jobs, reports, reverse
from findid.platforms import CATEGORIES, PLATFORMS, select
from findid.recon import check_rules, parse_usernames, variants as make_variants

WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="Find Identity", version=__version__, docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https: data: blob:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
    return response


@app.get("/", include_in_schema=False)
async def index():
    # Asset URLs carry a hash of their contents so browsers never run stale JS/CSS.
    digest = hashlib.sha1()
    for name in ("app.js", "app.css"):
        digest.update((WEB_DIR / name).read_bytes())
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("{{v}}", digest.hexdigest()[:10])
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


# ---- info -----------------------------------------------------------------
@app.get("/api/info")
async def info():
    return {
        "version": __version__,
        "lens_enabled": bool(config.SERPAPI_API_KEY),
        "max_images": config.MAX_IMAGES,
        "max_usernames": config.MAX_USERNAMES,
        "max_image_mb": config.MAX_IMAGE_MB,
        "categories": CATEGORIES,
    }


@app.get("/api/platforms")
async def platforms():
    return [
        {"name": p.name, "category": p.category, "method": p.method, "kind": p.kind,
         "example": p.profile_url.format(p.known_user or "username"), "notes": p.notes}
        for p in PLATFORMS
    ]


@app.post("/api/platforms/health")
async def platforms_health():
    return await check_rules()


# ---- scans ----------------------------------------------------------------
async def read_upload(upload: UploadFile) -> bytes:
    limit = config.MAX_IMAGE_MB * 1024 * 1024
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"{upload.filename} is larger than {config.MAX_IMAGE_MB} MB.")
    return data


@app.post("/api/scans")
async def create_scan(
    usernames: str = Form(""),
    include_variants: bool = Form(False),
    categories: str = Form(""),
    image_urls: str = Form(""),
    label: str = Form(""),
    images: List[UploadFile] = File(default=[]),
):
    names, rejected = parse_usernames(usernames)
    if rejected:
        raise HTTPException(422, "Usernames can only use letters, numbers, dots, dashes and "
                                 f"underscores: {', '.join(rejected[:5])}")
    if len(names) > config.MAX_USERNAMES:
        raise HTTPException(422, f"Scan up to {config.MAX_USERNAMES} usernames at a time.")
    cats = [c for c in categories.split(",") if c in CATEGORIES]
    chosen = select(cats or None)
    variant_map = {n: make_variants(n) for n in names} if include_variants else {}
    variant_map = {k: [v for v in vs if v.lower() not in {n.lower() for n in names}]
                   for k, vs in variant_map.items()}

    urls = [u.strip() for u in image_urls.split() if u.strip()]
    uploads = [u for u in images if u.filename]
    if len(urls) + len(uploads) > config.MAX_IMAGES:
        raise HTTPException(422, f"Add up to {config.MAX_IMAGES} images per scan.")
    if not names and not urls and not uploads:
        raise HTTPException(422, "Enter a username or add an image.")

    collected: list[dict] = []
    for upload in uploads:
        data = await read_upload(upload)
        try:
            imaging.open_checked(data)
        except imaging.ImageError as exc:
            raise HTTPException(422, f"{upload.filename}: {exc}")
        collected.append({"filename": Path(upload.filename or "image").name[:120], "data": data})
    for url in urls:
        try:
            data = await reverse.download_image(url)
            imaging.open_checked(data)
        except (ValueError, Exception) as exc:  # noqa: BLE001 - surface any download problem
            raise HTTPException(422, f"{url[:80]}: {exc}")
        name = Path(unquote(urlparse(url).path)).name or "image-from-link"
        collected.append({"filename": name[:120], "data": data, "source_url": url})
    for i, img in enumerate(collected):
        img["index"] = i

    job = jobs.start(names, variant_map, chosen if names else [], collected, cats, label)
    return {"id": job.id, "total": job.total}


@app.get("/api/scans/{report_id}/events")
async def scan_events(report_id: str, request: Request, after: int = -1):
    job = jobs.JOBS.get(report_id)
    if not job:
        raise HTTPException(404, "This scan is no longer running. Open it from History.")
    last = request.headers.get("last-event-id")
    start = int(last) + 1 if last and last.isdigit() else after + 1

    async def stream():
        pos = start
        yield "retry: 2000\n\n"
        while True:
            while pos < len(job.events):
                ev = job.events[pos]
                yield f"id: {ev['seq']}\ndata: {json.dumps(ev)}\n\n"
                pos += 1
                if ev["type"] == "end":
                    return
            if await request.is_disconnected():
                return
            try:
                await asyncio.wait_for(job.changed.wait(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/scans/{report_id}/cancel")
async def cancel_scan(report_id: str):
    return {"cancelled": jobs.cancel(report_id)}


@app.post("/api/scans/{report_id}/retry")
async def retry_scan(report_id: str):
    report = reports.load(report_id)
    if not report:
        raise HTTPException(404, "Report not found.")
    job = jobs.retry_errors(report)
    if not job:
        raise HTTPException(409, "This scan is still running.")
    return {"id": job.id, "total": job.total}


@app.get("/api/scans/{report_id}/images/{index}")
async def scan_image(report_id: str, index: int):
    if not reports.ID_RE.fullmatch(report_id):
        raise HTTPException(404)
    path = config.UPLOADS_DIR / report_id / f"{int(index)}.jpg"
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


# ---- reports --------------------------------------------------------------
@app.get("/api/reports")
async def list_reports():
    items = reports.list_all()
    for item in items:
        if item["status"] == "running" and item["id"] not in jobs.JOBS:
            item["status"] = "interrupted"
    return items


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    job = jobs.JOBS.get(report_id)
    if job and not job.done:
        return job.report
    report = reports.load(report_id)
    if not report:
        raise HTTPException(404, "Report not found.")
    if report.get("status") == "running":  # the server restarted mid-scan
        report["status"] = "interrupted"
        reports.save(report)
    return report


@app.delete("/api/reports/{report_id}")
async def delete_report(report_id: str):
    jobs.cancel(report_id)
    jobs.JOBS.pop(report_id, None)
    if not reports.delete(report_id):
        raise HTTPException(404, "Report not found.")
    return {"deleted": True}


@app.get("/api/reports/{report_id}/export.{fmt}")
async def export_report(report_id: str, fmt: str):
    report = reports.load(report_id)
    if not report:
        raise HTTPException(404, "Report not found.")
    name = f"find-identity-{report_id}"
    headers = lambda ext: {"Content-Disposition": f'attachment; filename="{name}.{ext}"'}  # noqa: E731
    if fmt == "json":
        return JSONResponse(report, headers=headers("json"))
    if fmt == "csv":
        return PlainTextResponse(reports.to_csv(report), media_type="text/csv", headers=headers("csv"))
    if fmt == "md":
        return PlainTextResponse(reports.to_markdown(report), media_type="text/markdown", headers=headers("md"))
    raise HTTPException(404, "Use json, csv or md.")


# ---- image tools ----------------------------------------------------------
@app.post("/api/tools/inspect")
async def inspect_image(image: UploadFile = File(...)):
    data = await read_upload(image)
    try:
        return await asyncio.to_thread(imaging.analyse, data, Path(image.filename or "image").name)
    except imaging.ImageError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/tools/strip")
async def strip_image(image: UploadFile = File(...)):
    data = await read_upload(image)
    try:
        clean, mime, ext = await asyncio.to_thread(imaging.strip_metadata, data)
    except imaging.ImageError as exc:
        raise HTTPException(422, str(exc))
    stem = Path(image.filename or "image").stem[:80] or "image"
    return Response(clean, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{stem}-clean.{ext}"'})


@app.post("/api/tools/compare")
async def compare_images(a: UploadFile = File(...), b: UploadFile = File(...)):
    try:
        ia = await asyncio.to_thread(imaging.analyse, await read_upload(a), a.filename or "A")
        ib = await asyncio.to_thread(imaging.analyse, await read_upload(b), b.filename or "B")
    except imaging.ImageError as exc:
        raise HTTPException(422, str(exc))
    return {
        "similarity": imaging.similarity(ia["dhash"], ib["dhash"]),
        "distance": imaging.hamming(ia["dhash"], ib["dhash"]),
        "identical": ia["sha256"] == ib["sha256"],
        "a": ia, "b": ib,
    }


def main(argv: Optional[list[str]] = None) -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="Run the Find Identity web app.")
    parser.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1 (this computer only)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="open the browser")
    args = parser.parse_args(argv)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print("Warning: the app has no login. Anyone who can reach this address can run scans "
              "and read your reports.")
    config.ensure_dirs()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"Find Identity {__version__} running at {url}")
    if args.open:
        webbrowser.open(url)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
