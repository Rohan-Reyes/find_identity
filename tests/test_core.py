import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from findid import imaging, reports
from findid.platforms import BY_NAME, PLATFORMS
from findid.recon import Scanner, judge, parse_usernames, variants


# ---------- usernames ----------
def test_parse_usernames_splits_dedupes_and_rejects():
    ok, bad = parse_usernames("@Jane.Doe, jane.doe\n jdoe99;  <script> ../etc")
    assert ok == ["Jane.Doe", "jdoe99", "../etc"] or ok == ["Jane.Doe", "jdoe99"]
    assert "<script>" in bad


def test_path_like_usernames_are_url_encoded():
    p = BY_NAME["GitHub"]
    from findid.recon import _result
    assert _result(p, "a/b?x", "found")["url"] == "https://github.com/a%2Fb%3Fx"


def test_variants():
    v = variants("jane.doe")
    assert {"janedoe", "jane_doe", "jane-doe", "jdoe", "janed"} <= set(v)
    assert "jane.doe" not in v
    assert "jdoe" in variants("jdoe99")
    assert variants("x") == []


# ---------- judging responses ----------
def test_judge_status_rules():
    gh = BY_NAME["GitHub"]
    assert judge(gh, 200, "<html>")[0] == "found"
    assert judge(gh, 404, "")[0] == "not_found"
    assert judge(gh, 429, "")[0] == "error"
    assert judge(gh, 403, "")[0] == "error"
    assert judge(gh, 200, "<title>Just a moment...</title>")[0] == "error"


def test_judge_json_and_markers():
    hn = BY_NAME["Hacker News"]
    assert judge(hn, 200, "null")[0] == "not_found"
    assert judge(hn, 200, json.dumps({"id": "pg"}))[0] == "found"
    assert judge(hn, 200, "not json")[0] == "error"
    wiki = BY_NAME["Wikipedia"]
    assert judge(wiki, 200, json.dumps({"query": {"users": [{"name": "X", "missing": ""}]}}))[0] == "not_found"
    assert judge(wiki, 200, json.dumps({"query": {"users": [{"userid": 1, "name": "X"}]}}))[0] == "found"
    tg = BY_NAME["Telegram"]
    assert judge(tg, 200, '<div class="tgme_page_title">Pavel</div>')[0] == "found"
    assert judge(tg, 200, "<div>If you have Telegram</div>")[0] == "not_found"
    pin = BY_NAME["Pinterest"]
    assert judge(pin, 200, "... User not found ...")[0] == "not_found"


def test_every_platform_is_well_formed():
    names = set()
    for p in PLATFORMS:
        assert p.name not in names
        names.add(p.name)
        assert "{}" in p.profile_url
        assert p.kind in ("status", "json", "marker", "manual")
        if p.kind == "json":
            assert p.exists is not None
        if p.kind != "manual":
            assert p.known_user and p.accepts(p.known_user), p.name


def test_scanner_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if "github.com/real" in str(request.url):
            return httpx.Response(200, text="<html>profile</html>")
        if "github.com/slow" in str(request.url):
            raise httpx.ConnectTimeout("slow")
        return httpx.Response(404)

    scanner = Scanner(transport=httpx.MockTransport(handler))
    rows = asyncio.run(scanner.scan(["real", "ghost", "slow", "has.dot"], [BY_NAME["GitHub"], BY_NAME["Reddit"]]))
    got = {(r["username"], r["platform"]): r["status"] for r in rows}
    assert got[("real", "GitHub")] == "found"
    assert got[("ghost", "GitHub")] == "not_found"
    assert got[("slow", "GitHub")] == "error"  # a timeout is not "not found"
    assert got[("has.dot", "GitHub")] == "skipped"  # GitHub names cannot contain dots
    assert got[("real", "Reddit")] == "manual"


# ---------- images ----------
def make_jpeg(gps: bool = True, size=(400, 300), color=(200, 40, 40)) -> bytes:
    img = Image.new("RGB", size, color)
    for x in range(0, size[0], 40):  # some structure for the hash
        for y in range(size[1]):
            img.putpixel((x, y), (10, 10, 10))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    exif[0x0110] = "Model X"  # Model
    exif[0x0131] = "Adobe Photoshop 25.0"  # Software
    exif.get_ifd(0x8769)[0x9003] = "2024:05:01 10:20:30"  # DateTimeOriginal (Exif IFD)
    if gps:
        exif.get_ifd(0x8825).update({1: "N", 2: (14.0, 35.0, 52.0), 3: "E", 4: (120.0, 58.0, 38.0)})
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_analyse_reads_exif_ifd_and_gps():
    a = imaging.analyse(make_jpeg(), "x.jpg")
    assert a["camera"] == "TestCam Model X"
    assert a["taken"] == "2024:05:01 10:20:30"  # lives in the Exif sub-IFD, missed by v1
    assert a["gps"]["latitude"] == pytest.approx(14.597778, abs=1e-5)
    assert a["gps"]["longitude"] == pytest.approx(120.977222, abs=1e-5)
    assert any("location" in f for f in a["flags"])
    assert any("Photoshop" in f for f in a["flags"])


def test_strip_metadata_removes_gps_and_exif():
    clean, mime, ext = imaging.strip_metadata(make_jpeg())
    assert mime == "image/jpeg" and ext == "jpg"
    a = imaging.analyse(clean, "clean.jpg")
    assert a["gps"] is None and a["exif"] == {}


def test_dhash_survives_resize_but_not_different_images():
    big = Image.open(io.BytesIO(make_jpeg(size=(800, 600))))
    small = io.BytesIO()
    big.resize((200, 150)).save(small, "JPEG", quality=60)  # resized + recompressed copy
    a = imaging.analyse(make_jpeg(size=(800, 600)))
    b = imaging.analyse(small.getvalue())
    other = Image.new("RGB", (400, 300))
    for x in range(400):
        for y in range(300):
            other.putpixel((x, y), ((x * y) % 256, x % 256, y % 256))
    buf = io.BytesIO()
    other.save(buf, "PNG")
    c = imaging.analyse(buf.getvalue())
    assert imaging.similarity(a["dhash"], b["dhash"]) >= 90
    assert imaging.similarity(a["dhash"], c["dhash"]) < 80
    pairs = imaging.similar_pairs([{**a, "filename": "a"}, {**b, "filename": "b"}, {**c, "filename": "c"}])
    assert [(p["a"], p["b"]) for p in pairs] == [("a", "b")]


def test_non_images_are_rejected():
    with pytest.raises(imaging.ImageError):
        imaging.analyse(b"%PDF-1.7 not an image")


def test_for_upload_stays_under_limit():
    img = Image.effect_noise((3000, 2000), 80).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    data, mime = imaging.for_upload(buf.getvalue())
    assert mime == "image/jpeg" and len(data) <= 480_000


# ---------- reports ----------
def test_exports():
    report = {
        "id": "abcdefabcdef", "created": "2026-01-01T00:00:00+00:00",
        "query": {"usernames": ["jane"], "variants": {}, "platforms": ["GitHub"], "images": []},
        "profiles": [{"platform": "GitHub", "category": "code", "username": "jane", "status": "found",
                      "url": "https://github.com/jane", "detail": ""},
                     {"platform": "Steam", "category": "gaming", "username": "jane", "status": "error",
                      "url": "https://steamcommunity.com/id/jane", "detail": "Rate limited"}],
        "images": [], "similar": [],
    }
    md = reports.to_markdown(report)
    assert "https://github.com/jane" in md and "Could not check: Steam" in md
    csv = reports.to_csv(report)
    assert csv.splitlines()[1].startswith("profile,jane,GitHub,found")
    assert reports.summarise(report)["found"] == 1
