"""Find Identity command line.

Examples:
    python main.py -u torvalds
    python main.py -u jane.doe janedoe99 --variants --only code social
    python main.py -f photo.jpg -i https://example.com/pic.jpg -o report.md
    python main.py --strip photo.jpg            # writes photo-clean.jpg
    python main.py --check-rules
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from findid import __version__, imaging, reports, reverse
from findid.platforms import CATEGORIES, PLATFORMS, select
from findid.recon import Scanner, check_rules, parse_usernames, variants as make_variants

console = Console()
STYLE = {"found": "bold green", "not_found": "dim", "error": "yellow", "manual": "cyan", "skipped": "dim"}
LABEL = {"found": "found", "not_found": "-", "error": "couldn't check", "manual": "check by hand", "skipped": "n/a"}


def list_platforms() -> None:
    t = Table(title=f"{len(PLATFORMS)} platforms")
    for col in ("Platform", "Category", "Method", "Notes"):
        t.add_column(col)
    for p in PLATFORMS:
        t.add_row(p.name, p.category, p.method, p.notes)
    console.print(t)


async def run_check_rules() -> int:
    with console.status("Checking every rule against a known account and a random name..."):
        results = await check_rules()
    t = Table(title="Rule health")
    for col in ("Platform", "Health", "Known account", "Random name", "Detail"):
        t.add_column(col)
    colour = {"ok": "green", "blocked": "yellow", "broken": "red"}
    for r in results:
        t.add_row(r["platform"], f"[{colour[r['health']]}]{r['health']}[/]", f"@{r['known_user']}: {r['known_result']}",
                  r["random_result"], r["detail"])
    console.print(t)
    broken = sum(r["health"] == "broken" for r in results)
    console.print(f"{len(results) - broken} of {len(results)} rules OK or temporarily blocked, {broken} broken.")
    return 1 if broken else 0


async def scan(args) -> dict:
    names, rejected = parse_usernames(" ".join(args.username or []))
    if rejected:
        console.print(f"[yellow]Skipping invalid usernames:[/] {', '.join(rejected)}")
    variant_map = {n: make_variants(n) for n in names} if args.variants else {}
    platforms = select(args.only, args.platform)
    report: dict = {
        "id": "cli",
        "version": __version__,
        "query": {"usernames": names, "variants": variant_map, "categories": args.only or [],
                  "platforms": [p.name for p in platforms],
                  "images": [*(args.image_file or []), *(args.image_url or [])]},
        "created": datetime.now().isoformat(timespec="seconds"),
        "profiles": [], "images": [], "similar": [],
    }

    all_names = names + [v for vs in variant_map.values() for v in vs]
    if all_names:
        total = len(all_names) * len(platforms)
        with console.status(f"Checking {len(all_names)} username(s) on {len(platforms)} platforms...") as status:
            async for row in Scanner().stream(all_names, platforms):
                report["profiles"].append(row)
                status.update(f"Checked {len(report['profiles'])}/{total}")
                if row["status"] == "found":
                    console.print(f"  [green]+[/] {row['platform']:<26} {row['url']}")
        for u in all_names:
            rows = sorted((r for r in report["profiles"] if r["username"] == u),
                          key=lambda r: (r["status"] != "found", r["platform"]))
            show = rows if args.all else [r for r in rows if r["status"] in ("found", "error", "manual")]
            t = Table(title=f"@{u}: {sum(r['status'] == 'found' for r in rows)} found", show_lines=False)
            t.add_column("Platform")
            t.add_column("Result")
            t.add_column("URL / detail", overflow="fold")
            for r in show:
                t.add_row(r["platform"], f"[{STYLE[r['status']]}]{LABEL[r['status']]}[/]",
                          r["url"] if r["status"] in ("found", "manual") else r["detail"])
            console.print(t)

    sources = [(p, None) for p in args.image_file or []] + [(None, u) for u in args.image_url or []]
    for i, (path, url) in enumerate(sources):
        label = path or url
        try:
            data = Path(path).read_bytes() if path else await reverse.download_image(url)
            info = imaging.analyse(data, Path(path).name if path else url)
        except (OSError, ValueError) as exc:
            console.print(f"[red]{label}: {exc}[/]")
            continue
        lens = await reverse.google_lens(data, url)
        info.update(index=i, source_url=url, links=reverse.engine_links(url),
                    matches=lens["matches"], lens_error=lens.get("error"))
        report["images"].append(info)
        print_image(info)

    report["similar"] = imaging.similar_pairs(report["images"])
    for p in report["similar"]:
        console.print(f"[cyan]{p['a']} and {p['b']} look like the same picture ({p['similarity']}%).[/]")
    report["summary"] = reports.summarise(report)
    return report


def print_image(info: dict) -> None:
    t = Table(title=f"Image: {info['filename']}", show_header=False)
    t.add_column(style="magenta")
    t.add_column(overflow="fold")
    t.add_row("Size", f"{info['width']} x {info['height']} {info['format']}, {info['file_size_kb']} KB")
    for key, label in (("camera", "Camera"), ("taken", "Taken"), ("software", "Software")):
        if info.get(key):
            t.add_row(label, info[key])
    t.add_row("dHash", info["dhash"])
    t.add_row("SHA-256", info["sha256"])
    if info.get("gps"):
        g = info["gps"]
        t.add_row("[bold red]GPS[/]", f"{g['latitude']}, {g['longitude']}  {g['maps_url']}")
    for flag in info.get("flags", []):
        t.add_row("Note", flag)
    for link in info["links"]:
        t.add_row(link["engine"], link["url"])
    console.print(t)
    if info.get("lens_error"):
        console.print(f"[yellow]{info['lens_error']}[/]")
    for m in info.get("matches", [])[:10]:
        console.print(f"  [green]•[/] {m['title'][:70]}  [blue]{m['url']}[/]")


def write_report(report: dict, path: str) -> None:
    out = Path(path)
    if out.suffix == ".csv":
        out.write_text(reports.to_csv(report), encoding="utf-8")
    elif out.suffix == ".md":
        out.write_text(reports.to_markdown(report), encoding="utf-8")
    else:
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"[green]Report saved:[/] {out.resolve()}")


def strip(paths: list[str]) -> None:
    for src in paths:
        try:
            clean, _, ext = imaging.strip_metadata(Path(src).read_bytes())
        except (OSError, ValueError) as exc:
            console.print(f"[red]{src}: {exc}[/]")
            continue
        dest = Path(src).with_name(f"{Path(src).stem}-clean.{ext}")
        dest.write_bytes(clean)
        console.print(f"[green]Clean copy:[/] {dest}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Find public profiles by username and analyse images.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("-u", "--username", nargs="+", metavar="NAME", help="one or more usernames")
    ap.add_argument("-f", "--image-file", nargs="+", metavar="PATH", help="local image file(s)")
    ap.add_argument("-i", "--image-url", nargs="+", metavar="URL", help="public image link(s)")
    ap.add_argument("-o", "--output", help="save the report (.json, .csv or .md)")
    ap.add_argument("--variants", action="store_true", help="also try common spellings (jane.doe -> janedoe, jane_doe...)")
    ap.add_argument("--only", nargs="+", choices=list(CATEGORIES), metavar="CATEGORY",
                    help=f"limit to categories: {', '.join(CATEGORIES)}")
    ap.add_argument("--platform", nargs="+", metavar="NAME", help="limit to named platforms")
    ap.add_argument("--all", action="store_true", help="also list platforms where nothing was found")
    ap.add_argument("--list-platforms", action="store_true", help="show every supported platform")
    ap.add_argument("--check-rules", action="store_true", help="test every platform rule against live sites")
    ap.add_argument("--strip", nargs="+", metavar="PATH", help="write copies of images with metadata removed")
    ap.add_argument("--version", action="version", version=f"Find Identity {__version__}")
    args = ap.parse_args(argv)

    if args.list_platforms:
        list_platforms()
        return 0
    if args.check_rules:
        return asyncio.run(run_check_rules())
    if args.strip:
        strip(args.strip)
        return 0
    if not (args.username or args.image_file or args.image_url):
        ap.print_help()
        return 2
    if args.platform and not select(args.only, args.platform):
        console.print("[red]No platform matches --platform/--only.[/] See --list-platforms.")
        return 2
    report = asyncio.run(scan(args))
    s = report["summary"]
    console.print(f"\n[bold]{s['found']} profiles found[/], {s['error']} checks failed, "
                  f"{s['manual']} to check by hand, {s['images']} image(s) analysed.")
    if args.output:
        write_report(report, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
