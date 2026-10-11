"""Main CLI orchestrator for public profile reconnaissance and deep visual search."""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table

from username_recon import UsernameScanner
from image_search import VisualSearchEngine

console = Console()


async def run(
    username: str,
    image_url: Optional[str],
    image_file: Optional[str],
    output_file: str,
) -> None:
    results: dict = {
        "query": {
            "username": username,
            "image_url": image_url,
            "image_file": image_file,
        },
        "username_matches": [],
        "visual_matches": [],
        "forensics": {},
    }

    # 1. Execute Username Reconnaissance
    console.print(f"[bold cyan][*] Scanning platforms for username:[/bold cyan] {username}")
    scanner = UsernameScanner(max_concurrency=5)
    username_results = await scanner.scan(username)
    results["username_matches"] = username_results

    # Display Username Results Table
    if username_results:
        table = Table(title=f"Verified Public Profiles for @{username}", show_lines=True)
        table.add_column("Platform", style="green", no_wrap=True)
        table.add_column("Profile URL", style="blue")

        for entry in username_results:
            table.add_row(entry["platform"], entry["url"])
        console.print(table)
    else:
        console.print("[yellow][-] No matching profiles identified on target platforms.[/yellow]")

    # 2. Execute Visual Search if image provided
    visual_engine = VisualSearchEngine()

    if image_file:
        console.print(f"\n[bold cyan][*] Performing deep forensics and visual search for local file:[/bold cyan] {image_file}")
        visual_data = await visual_engine.search_by_file(image_file)
        results["forensics"] = visual_data.get("forensics", {})
        results["visual_matches"] = visual_data.get("matches", [])

        # Display Forensics
        fn = visual_data.get("forensics", {})
        if fn:
            f_table = Table(title="Image Forensics & Metadata", show_lines=True)
            f_table.add_column("Attribute", style="magenta")
            f_table.add_column("Value", style="cyan")
            f_table.add_row("Resolution", f"{fn.get('width', 0)} x {fn.get('height', 0)}")
            f_table.add_row("Format / Mode", f"{fn.get('format', 'N/A')} ({fn.get('color_mode', 'N/A')})")
            f_table.add_row("File Size", f"{fn.get('file_size_kb', 0)} KB")
            f_table.add_row("dHash (Structural)", str(fn.get("dhash", "N/A")))
            f_table.add_row("MD5", str(fn.get("hashes", {}).get("md5", "N/A")))

            gps = fn.get("gps")
            if gps:
                f_table.add_row("GPS Geolocation", f"{gps.get('latitude')}, {gps.get('longitude')} ({gps.get('maps_url')})")

            console.print(f_table)

        matches = visual_data.get("matches", [])
        if matches:
            v_table = Table(title="Visual Matches Found", show_lines=True)
            v_table.add_column("Source / Title", style="green")
            v_table.add_column("Matched URL", style="blue")
            for match in matches[:10]:
                v_table.add_row(match.get("title", "N/A"), match.get("url", "N/A"))
            console.print(v_table)
        elif visual_data.get("notice"):
            console.print(f"[yellow][!] Visual Notice:[/yellow] {visual_data['notice']}")

    elif image_url:
        console.print(f"\n[bold cyan][*] Performing reverse visual search for image URL:[/bold cyan] {image_url}")
        visual_data = await visual_engine.search_by_file(image_url) if Path(image_url).is_file() else await visual_engine.search_by_file(image_url)
        matches = visual_data.get("matches", [])
        results["visual_matches"] = matches
        if matches:
            v_table = Table(title="Visual Matches Found", show_lines=True)
            v_table.add_column("Source / Title", style="green")
            v_table.add_column("Matched URL", style="blue")
            for match in matches[:10]:
                v_table.add_row(match.get("title", "N/A"), match.get("url", "N/A"))
            console.print(v_table)

    # 3. Export to JSON
    output_path = Path(output_file)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    console.print(f"\n[bold green][✔] Finished. Results saved to:[/bold green] {output_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Public profile locator and deep reverse visual search tool."
    )
    parser.add_argument(
        "-u", "--username", required=True, help="Target username to query."
    )
    parser.add_argument(
        "-i", "--image-url", required=False, help="Public image URL for reverse search."
    )
    parser.add_argument(
        "-f", "--image-file", required=False, help="Local image file path for deep forensic & visual search."
    )
    parser.add_argument(
        "-o", "--output", default="results.json", help="Path to write the results JSON."
    )

    args = parser.parse_args()
    asyncio.run(run(args.username, args.image_url, args.image_file, args.output))


if __name__ == "__main__":
    main()
