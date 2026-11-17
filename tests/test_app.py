import time

import pytest
from fastapi.testclient import TestClient

from findid import config
from tests.test_core import make_jpeg


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr("findid.reverse.config.SERPAPI_API_KEY", "")
    import app as app_module
    with TestClient(app_module.app) as c:
        yield c


def wait_done(client, report_id, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(f"/api/reports/{report_id}").json()
        if r["status"] != "running":
            return r
        time.sleep(0.1)
    raise AssertionError("scan did not finish")


def test_index_and_info(client):
    r = client.get("/")
    assert r.status_code == 200 and "Content-Security-Policy" in r.headers
    assert client.get("/api/info").json()["lens_enabled"] is False
    assert len(client.get("/api/platforms").json()) > 30


def test_image_scan_end_to_end(client):
    files = [("images", ("a.jpg", make_jpeg(), "image/jpeg")),
             ("images", ("b.jpg", make_jpeg(gps=False), "image/jpeg"))]
    res = client.post("/api/scans", data={"usernames": ""}, files=files)
    assert res.status_code == 200, res.text
    rid = res.json()["id"]
    report = wait_done(client, rid)
    assert report["status"] == "done"
    assert len(report["images"]) == 2
    assert report["images"][0]["gps"] is not None
    assert report["similar"] and report["similar"][0]["similarity"] >= 95
    assert client.get(f"/api/scans/{rid}/images/0").headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/reports/{rid}/export.md").status_code == 200
    assert client.get(f"/api/reports/{rid}/export.csv").text.startswith("type,")
    assert any(x["id"] == rid for x in client.get("/api/reports").json())
    assert client.delete(f"/api/reports/{rid}").status_code == 200
    assert client.get(f"/api/reports/{rid}").status_code == 404


def test_rejects_bad_input(client):
    assert client.post("/api/scans", data={"usernames": "<img src=x onerror=alert(1)>"}).status_code == 422
    assert client.post("/api/scans", data={"usernames": ""}).status_code == 422
    bad = [("images", ("x.jpg", b"not an image", "image/jpeg"))]
    assert client.post("/api/scans", data={"usernames": ""}, files=bad).status_code == 422
    assert client.post("/api/scans", data={"image_urls": "http://127.0.0.1/x.jpg"}).status_code == 422
    assert client.get("/api/reports/..%2F..%2Fsecret").status_code == 404
    assert client.get("/api/scans/../images/0").status_code == 404


def test_strip_tool(client):
    r = client.post("/api/tools/strip", files={"image": ("me.jpg", make_jpeg(), "image/jpeg")})
    assert r.status_code == 200 and 'me-clean.jpg' in r.headers["content-disposition"]
    r = client.post("/api/tools/inspect", files={"image": ("clean.jpg", r.content, "image/jpeg")})
    assert r.json()["gps"] is None
