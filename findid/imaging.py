"""Image forensics: fingerprints, EXIF/GPS, similarity and metadata removal."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Optional

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 80_000_000  # refuse decompression bombs

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF", "MPO"}
EXIF_IFD = 0x8769
GPS_IFD = 0x8825
SKIP_TAGS = {"MakerNote", "UserComment", "PrintImageMatching", "ComponentsConfiguration",
             "ExifOffset", "GPSInfo", "JPEGInterchangeFormat", "JPEGInterchangeFormatLength"}
EDITORS = ("photoshop", "lightroom", "gimp", "snapseed", "picsart", "canva", "facetune",
           "affinity", "pixelmator", "vsco", "meitu", "capcut")


class ImageError(ValueError):
    """The file is not an image we can read."""


def open_checked(data: bytes) -> Image.Image:
    """Open bytes as an image, rejecting non-images and unsupported formats."""
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))  # verify() leaves the object unusable
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise ImageError("Not a readable image (JPEG, PNG, WebP, GIF, BMP or TIFF).") from exc
    if img.format not in ALLOWED_FORMATS:
        raise ImageError(f"{img.format} images are not supported.")
    return img


def dhash(img: Image.Image, size: int = 8) -> str:
    """64-bit difference hash: survives resizing, recompression and small edits."""
    gray = ImageOps.exif_transpose(img).convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    px = gray.load()
    bits = 0
    for y in range(size):
        for x in range(size):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return f"{bits:0{size * size // 4}x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def similarity(a: str, b: str) -> int:
    """0-100 score from two dHashes (100 = same picture)."""
    return round(100 * (1 - hamming(a, b) / (len(a) * 4)))


def _clean(value: Any) -> Optional[str]:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore").strip("\x00 ").strip()
        return text if text and text.isprintable() and len(text) <= 200 else None
    if isinstance(value, (tuple, list)):
        if len(value) > 8:
            return None
        return ", ".join(str(_num(v)) for v in value)
    text = str(_num(value)).strip("\x00 ").strip()
    return text[:200] if text else None


def _num(v: Any) -> Any:
    try:
        f = float(v)
        return int(f) if f.is_integer() else round(f, 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return v


def _degrees(val: Any) -> float:
    d, m, s = (float(x) for x in val)
    return d + m / 60.0 + s / 3600.0


def parse_gps(gps: dict) -> Optional[dict]:
    try:
        lat = _degrees(gps["GPSLatitude"])
        lon = _degrees(gps["GPSLongitude"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if gps.get("GPSLatitudeRef") in ("S", b"S"):
        lat = -lat
    if gps.get("GPSLongitudeRef") in ("W", b"W"):
        lon = -lon
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    out: dict[str, Any] = {
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "maps_url": f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=16/{lat:.6f}/{lon:.6f}",
        "google_maps_url": f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}",
    }
    try:
        alt = float(gps["GPSAltitude"])
        out["altitude_m"] = round(-alt if gps.get("GPSAltitudeRef") in (1, b"\x01") else alt, 1)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    if gps.get("GPSDateStamp"):
        out["timestamp"] = str(gps["GPSDateStamp"])
    return out


def read_exif(img: Image.Image) -> tuple[dict[str, str], Optional[dict]]:
    """All readable EXIF tags (including the Exif sub-IFD) plus parsed GPS."""
    tags: dict[str, str] = {}
    gps_raw: dict[str, Any] = {}
    try:
        exif = img.getexif()
    except Exception:
        return {}, None
    if not exif:
        return {}, None

    def take(items):
        for tag_id, val in items:
            name = ExifTags.TAGS.get(tag_id, f"Tag{tag_id}")
            if name in SKIP_TAGS:
                continue
            cleaned = _clean(val)
            if cleaned:
                tags[name] = cleaned

    take(exif.items())
    try:
        take(exif.get_ifd(EXIF_IFD).items())
    except Exception:
        pass
    try:
        for g_id, g_val in exif.get_ifd(GPS_IFD).items():
            gps_raw[ExifTags.GPSTAGS.get(g_id, str(g_id))] = g_val
    except Exception:
        pass
    return tags, parse_gps(gps_raw) if gps_raw else None


def analyse(data: bytes, filename: str = "") -> dict[str, Any]:
    """Everything we can learn from the file itself, without going online."""
    img = open_checked(data)
    tags, gps = read_exif(img)
    w, h = img.size
    software = tags.get("Software", "")
    camera = " ".join(x for x in (tags.get("Make", ""), tags.get("Model", "")) if x).strip()
    taken = tags.get("DateTimeOriginal") or tags.get("DateTime") or ""

    flags = []
    if gps:
        flags.append("Contains the exact location where the photo was taken.")
    if camera:
        flags.append(f"Identifies the device: {camera}.")
    if any(e in software.lower() for e in EDITORS):
        flags.append(f"Edited with {software}.")
    if not tags:
        flags.append("No EXIF metadata: likely stripped by a social network, screenshot or messenger.")
    if img.info.get("icc_profile") is None and img.format == "JPEG" and not tags:
        flags.append("No colour profile either: typical of images re-saved by a website.")

    return {
        "filename": filename,
        "width": w,
        "height": h,
        "megapixels": round(w * h / 1_000_000, 2),
        "format": img.format,
        "color_mode": img.mode,
        "animated": bool(getattr(img, "is_animated", False)),
        "file_size_kb": round(len(data) / 1024, 1),
        "dhash": dhash(img),
        "md5": hashlib.md5(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "camera": camera,
        "software": software,
        "taken": taken,
        "exif": tags,
        "gps": gps,
        "flags": flags,
    }


def strip_metadata(data: bytes) -> tuple[bytes, str, str]:
    """Return (clean bytes, mime, extension) with EXIF, GPS and text chunks removed.

    The picture is rotated upright first so dropping the Orientation tag does not
    turn it sideways. Colour profiles are kept so colours do not shift.
    """
    img = open_checked(data)
    fmt = img.format
    icc = img.info.get("icc_profile")
    img = ImageOps.exif_transpose(img)
    buf = io.BytesIO()
    if fmt in ("JPEG", "MPO"):
        img.convert("RGB").save(buf, "JPEG", quality=95, optimize=True, icc_profile=icc)
        return buf.getvalue(), "image/jpeg", "jpg"
    if fmt == "WEBP":
        img.save(buf, "WEBP", quality=95, icc_profile=icc)
        return buf.getvalue(), "image/webp", "webp"
    if img.mode not in ("RGB", "RGBA", "L", "LA", "P"):
        img = img.convert("RGBA")
    img.save(buf, "PNG", optimize=True, icc_profile=icc)
    return buf.getvalue(), "image/png", "png"


def for_upload(data: bytes, max_bytes: int = 480_000) -> tuple[bytes, str]:
    """Shrink an image under SerpApi's 500 KB upload limit (JPEG)."""
    img = open_checked(data)
    if len(data) <= max_bytes and img.format in ("JPEG", "PNG", "WEBP"):
        return data, Image.MIME[img.format]
    img = ImageOps.exif_transpose(img).convert("RGB")
    edge = 1600
    while True:
        if max(img.size) > edge:
            img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        for quality in (88, 80, 70, 60):
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=quality, optimize=True)
            if buf.tell() <= max_bytes:
                return buf.getvalue(), "image/jpeg"
        edge = int(edge * 0.75)
        if edge < 200:
            return buf.getvalue(), "image/jpeg"


def thumbnail(data: bytes, edge: int = 480) -> bytes:
    img = ImageOps.exif_transpose(open_checked(data)).convert("RGB")
    img.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def similar_pairs(images: list[dict], threshold: int = 85) -> list[dict]:
    """Pairs of analysed images that look like the same picture."""
    pairs = []
    for i in range(len(images)):
        for j in range(i + 1, len(images)):
            a, b = images[i], images[j]
            if not a.get("dhash") or not b.get("dhash"):
                continue
            score = similarity(a["dhash"], b["dhash"])
            if score >= threshold:
                pairs.append({"a": a["filename"], "b": b["filename"], "similarity": score,
                              "identical": a.get("sha256") == b.get("sha256")})
    return pairs


def read_file(path: str | Path) -> bytes:
    return Path(path).read_bytes()
