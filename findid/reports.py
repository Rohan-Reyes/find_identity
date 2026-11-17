"""Saved scan reports (one JSON file each) and exports."""

from __future__ import annotations

import csv
import io
import json
import re
import shutil
from typing import Any, Optional

from . import config

ID_RE = re.compile(r"^[a-f0-9]{12}$")
STATUSES = ("found", "not_found", "error", "manual", "skipped")


def _path(report_id: str):
    if not ID_RE.fullmatch(report_id):
        raise KeyError(report_id)
    return config.REPORTS_DIR / f"{report_id}.json"


def summarise(report: dict) -> dict:
    counts = {s: 0 for s in STATUSES}
    for row in report.get("profiles", []):
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    counts["images"] = len(report.get("images", []))
    counts["visual_matches"] = sum(len(i.get("matches", [])) for i in report.get("images", []))
    counts["with_gps"] = sum(1 for i in report.get("images", []) if i.get("gps"))
    return counts


def save(report: dict) -> None:
    config.ensure_dirs()
    report["summary"] = summarise(report)
    tmp = _path(report["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_path(report["id"]))


def load(report_id: str) -> Optional[dict]:
    try:
        return json.loads(_path(report_id).read_text(encoding="utf-8"))
    except (KeyError, OSError, ValueError):
        return None


def list_all() -> list[dict]:
    config.ensure_dirs()
    items = []
    for f in config.REPORTS_DIR.glob("*.json"):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items.append({
            "id": r["id"],
            "created": r.get("created"),
            "status": r.get("status"),
            "label": r.get("label") or "",
            "usernames": r.get("query", {}).get("usernames", []),
            "images": [i.get("filename") for i in r.get("images", [])],
            "summary": r.get("summary") or summarise(r),
        })
    return sorted(items, key=lambda x: x.get("created") or "", reverse=True)


def delete(report_id: str) -> bool:
    try:
        path = _path(report_id)
    except KeyError:
        return False
    existed = path.exists()
    path.unlink(missing_ok=True)
    shutil.rmtree(config.UPLOADS_DIR / report_id, ignore_errors=True)
    return existed


def to_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["type", "username_or_file", "platform_or_engine", "status", "url", "detail"])
    for r in sorted(report.get("profiles", []), key=lambda x: (x["username"].lower(), x["status"] != "found", x["platform"])):
        w.writerow(["profile", r["username"], r["platform"], r["status"], r["url"], r.get("detail", "")])
    for img in report.get("images", []):
        if img.get("gps"):
            w.writerow(["gps", img["filename"], "EXIF", "found", img["gps"]["maps_url"],
                        f'{img["gps"]["latitude"]}, {img["gps"]["longitude"]}'])
        for m in img.get("matches", []):
            w.writerow(["image_match", img["filename"], m.get("source", ""), m.get("kind", ""), m["url"], m.get("title", "")])
    return buf.getvalue()


def _md(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(report: dict) -> str:
    s = report.get("summary") or summarise(report)
    q = report.get("query", {})
    lines = [
        f"# Find Identity report {report['id']}",
        "",
        f"- **Created:** {report.get('created', '')}",
        f"- **Usernames:** {', '.join(q.get('usernames', [])) or '-'}",
        f"- **Images:** {len(report.get('images', []))}",
        f"- **Result:** {s['found']} profiles found, {s['error']} checks failed, {s['manual']} to check by hand",
        "",
    ]
    users = sorted({r["username"] for r in report.get("profiles", [])}, key=str.lower)
    for u in users:
        rows = [r for r in report["profiles"] if r["username"] == u]
        found = [r for r in rows if r["status"] == "found"]
        lines += [f"## @{u}", "", f"{len(found)} of {len(rows)} platforms.", ""]
        if found:
            lines += ["| Platform | Profile |", "|---|---|"]
            lines += [f"| {_md(r['platform'])} | <{r['url']}> |" for r in sorted(found, key=lambda r: r["platform"])]
            lines.append("")
        manual = [r for r in rows if r["status"] == "manual"]
        if manual:
            lines.append("Check by hand: " + ", ".join(f"[{r['platform']}]({r['url']})" for r in manual))
            lines.append("")
        errors = [r for r in rows if r["status"] == "error"]
        if errors:
            lines.append("Could not check: " + ", ".join(f"{r['platform']} ({r['detail']})" for r in errors))
            lines.append("")
    for img in report.get("images", []):
        lines += [f"## Image: {_md(img['filename'])}", ""]
        lines.append(f"{img.get('width')}x{img.get('height')} {img.get('format')}, {img.get('file_size_kb')} KB, dHash `{img.get('dhash')}`, SHA-256 `{img.get('sha256')}`")
        lines.append("")
        for flag in img.get("flags", []):
            lines.append(f"- {flag}")
        if img.get("gps"):
            g = img["gps"]
            lines.append(f"- GPS: {g['latitude']}, {g['longitude']} ({g['maps_url']})")
        if img.get("matches"):
            lines += ["", "| Match | Source |", "|---|---|"]
            lines += [f"| [{_md(m['title'])}]({m['url']}) | {_md(m.get('source', ''))} |" for m in img["matches"][:25]]
        lines.append("")
    if report.get("similar"):
        lines += ["## Similar images", ""]
        lines += [f"- {p['a']} and {p['b']}: {p['similarity']}% similar" for p in report["similar"]]
        lines.append("")
    return "\n".join(lines)
