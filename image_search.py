"""Deep Visual Search and Image Forensics Module with SerpApi Google Lens Integration.

Provides multi-engine reverse search (Google Lens, Yandex, Bing, TinEye),
perceptual hash analysis (dHash), EXIF forensics, and GPS geolocation extraction.
"""

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from PIL import ExifTags, Image

from config import SERPAPI_API_KEY


def calculate_dhash(image_path: str, hash_size: int = 8) -> str:
    """Computes a 64-bit Difference Hash (dHash) to fingerprint image structure."""
    try:
        with Image.open(image_path) as img:
            img = img.convert("L").resize(
                (hash_size + 1, hash_size), Image.Resampling.LANCZOS
            )
            pixels = list(img.getdata())
            diff = []
            for row in range(hash_size):
                for col in range(hash_size):
                    left = pixels[row * (hash_size + 1) + col]
                    right = pixels[row * (hash_size + 1) + col + 1]
                    diff.append(left > right)

            decimal_val = 0
            hex_parts = []
            for i, val in enumerate(diff):
                if val:
                    decimal_val += 2 ** (i % 8)
                if (i % 8) == 7:
                    hex_parts.append(hex(decimal_val)[2:].rjust(2, "0"))
                    decimal_val = 0
            return "".join(hex_parts)
    except Exception:
        return "N/A"


def extract_file_hashes(image_path: str) -> Dict[str, str]:
    """Calculates MD5 and SHA-256 cryptographic hashes."""
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with open(image_path, "rb") as f:
        while chunk := f.read(65536):
            md5.update(chunk)
            sha256.update(chunk)
    return {
        "md5": md5.hexdigest(),
        "sha256": sha256.hexdigest(),
    }


def parse_gps_coordinates(gps_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Converts EXIF GPS coordinate tuples to decimal degrees with Google Maps link."""
    try:
        def to_degrees(val):
            d, m, s = val
            return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)

        lat = to_degrees(gps_data.get("GPSLatitude"))
        if gps_data.get("GPSLatitudeRef") == "S":
            lat = -lat

        lon = to_degrees(gps_data.get("GPSLongitude"))
        if gps_data.get("GPSLongitudeRef") == "W":
            lon = -lon

        return {
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "maps_url": f"https://www.google.com/maps?q={lat},{lon}",
        }
    except Exception:
        return None


def extract_exif_forensics(image_path: str) -> Dict[str, Any]:
    """Extracts camera metadata, software, timestamp, and geolocation."""
    metadata: Dict[str, Any] = {}
    gps_info: Dict[str, Any] = {}

    try:
        with Image.open(image_path) as img:
            exif_raw = img.getexif()
            if not exif_raw:
                return {"tags": {}, "gps": None}

            for tag_id, val in exif_raw.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if tag_name == "GPSInfo":
                    gps_ifd = exif_raw.get_ifd(tag_id)
                    for g_id, g_val in gps_ifd.items():
                        g_name = ExifTags.GPSTAGS.get(g_id, str(g_id))
                        gps_info[g_name] = g_val
                elif isinstance(val, (str, int, float)):
                    metadata[tag_name] = str(val)
                elif isinstance(val, bytes):
                    try:
                        metadata[tag_name] = val.decode("utf-8", errors="ignore").strip()
                    except Exception:
                        pass
    except Exception:
        pass

    gps_coords = parse_gps_coordinates(gps_info) if gps_info else None
    return {"tags": metadata, "gps": gps_coords}


def prepare_image_for_serpapi(file_path: str, max_size_bytes: int = 480_000) -> tuple[io.BytesIO, str]:
    """Optimizes an image to stay safely under SerpApi's 500 KB upload ceiling."""
    path = Path(file_path)
    file_size = path.stat().st_size

    # If within limit and is standard format, read directly
    if file_size <= max_size_bytes and path.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]:
        with open(file_path, "rb") as f:
            buf = io.BytesIO(f.read())
            buf.seek(0)
            mime = f"image/{path.suffix.lower().lstrip('.')}"
            if mime == "image/jpg":
                mime = "image/jpeg"
            return buf, mime

    # Otherwise resize/compress in memory with PIL
    buf = io.BytesIO()
    with Image.open(file_path) as img:
        img_converted = img.convert("RGB")
        # Resize down if very high resolution
        if max(img_converted.size) > 1600:
            img_converted.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        img_converted.save(buf, format="JPEG", quality=85, optimize=True)

    buf.seek(0)
    return buf, "image/jpeg"


class VisualSearchEngine:
    """Performs deep multi-engine visual reconnaissance."""

    def __init__(self, api_key: Optional[str] = SERPAPI_API_KEY):
        self.api_key = api_key
        self.upload_endpoint = "https://serpapi.com/image"
        self.search_endpoint = "https://serpapi.com/search.json"

    def get_deep_forensics(self, file_path: str) -> Dict[str, Any]:
        """Gathers local forensic and structural indicators."""
        path = Path(file_path)
        exif = extract_exif_forensics(file_path)
        hashes = extract_file_hashes(file_path)
        dhash = calculate_dhash(file_path)

        with Image.open(file_path) as img:
            w, h = img.size
            fmt = img.format or path.suffix.upper().lstrip(".")
            mode = img.mode

        return {
            "width": w,
            "height": h,
            "aspect_ratio": f"{round(w / h, 2)}:1" if h else "N/A",
            "format": fmt,
            "color_mode": mode,
            "file_size_kb": round(path.stat().st_size / 1024, 2),
            "dhash": dhash,
            "hashes": hashes,
            "exif": exif["tags"],
            "gps": exif["gps"],
        }

    async def search_by_file(self, file_path: str) -> Dict[str, Any]:
        """Uploads the local image to SerpApi Image API, then queries Google Lens."""
        forensics = self.get_deep_forensics(file_path)

        # Multi-engine direct OSINT links
        engine_links = {
            "google_lens": "https://lens.google.com/",
            "yandex": "https://yandex.com/images/search?rpt=imageview",
            "bing": "https://www.bing.com/visualsearch",
            "tineye": "https://tineye.com/",
        }

        if not self.api_key:
            return {
                "notice": "SERPAPI_API_KEY is not configured in .env. Enter a key to query live visual indices.",
                "forensics": forensics,
                "engine_links": engine_links,
                "matches": [],
                "knowledge_graph": None,
            }

        async with httpx.AsyncClient(timeout=35.0) as client:
            try:
                # Step 1: Upload image to SerpApi to get image_id
                img_buf, mime_type = prepare_image_for_serpapi(file_path)
                files = {"image": ("upload.jpg", img_buf, mime_type)}
                upload_res = await client.post(
                    self.upload_endpoint,
                    files=files,
                    params={"api_key": self.api_key},
                )

                if upload_res.status_code != 200:
                    return {
                        "error": f"Image upload to SerpApi failed: HTTP {upload_res.status_code}",
                        "forensics": forensics,
                        "engine_links": engine_links,
                        "matches": [],
                    }

                image_id = upload_res.json().get("image_id")
                if not image_id:
                    return {
                        "error": "Failed to obtain image_id from SerpApi.",
                        "forensics": forensics,
                        "engine_links": engine_links,
                        "matches": [],
                    }

                # Step 2: Query Google Lens with image_id
                lens_params = {
                    "engine": "google_lens",
                    "image_id": image_id,
                    "api_key": self.api_key,
                }
                search_res = await client.get(
                    self.search_endpoint,
                    params=lens_params,
                )

                if search_res.status_code == 200:
                    json_data = search_res.json()
                    matches = self._parse_lens_results(json_data)
                    knowledge = json_data.get("knowledge_graph", {})
                    return {
                        "forensics": forensics,
                        "engine_links": engine_links,
                        "matches": matches,
                        "knowledge_graph": knowledge,
                    }

                return {
                    "error": f"Google Lens search returned HTTP {search_res.status_code}",
                    "forensics": forensics,
                    "engine_links": engine_links,
                    "matches": [],
                }

            except httpx.RequestError as exc:
                return {
                    "error": f"Network error during visual search: {str(exc)}",
                    "forensics": forensics,
                    "engine_links": engine_links,
                    "matches": [],
                }

    def _parse_lens_results(self, data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Parses Google Lens visual matches and organic results."""
        matches: List[Dict[str, str]] = []

        # 1. Visual matches
        for item in data.get("visual_matches", []):
            title = item.get("title", "Visual Match")
            link = item.get("link", "")
            source = item.get("source", "Web")
            thumbnail = item.get("thumbnail", "")
            if link:
                matches.append({
                    "title": title,
                    "url": link,
                    "source": source,
                    "thumbnail": thumbnail,
                })

        # 2. Organic results
        for item in data.get("organic_results", []):
            title = item.get("title", "Organic Result")
            link = item.get("link", "")
            source = item.get("source", "Web")
            thumbnail = item.get("thumbnail", "")
            if link and not any(m["url"] == link for m in matches):
                matches.append({
                    "title": title,
                    "url": link,
                    "source": source,
                    "thumbnail": thumbnail,
                })

        return matches
