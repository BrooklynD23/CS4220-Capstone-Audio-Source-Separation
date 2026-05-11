from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ui.serve_compare_demo import CompareDemoHandler


@pytest.fixture(scope="module")
def demo_server():
    tmpdir = tempfile.mkdtemp()
    handler = partial(CompareDemoHandler, directory=tmpdir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield ("127.0.0.1", port)
    server.shutdown()


def _post(host, port, path, body, headers):
    conn = http.client.HTTPConnection(host, port, timeout=10)
    conn.request("POST", path, body, headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_post_missing_file(demo_server):
    host, port = demo_server
    body = (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="device"\r\n\r\ngpu\r\n'
        b"--boundary--\r\n"
    )
    status, data = _post(host, port, "/api/separate", body, {
        "Content-Type": "multipart/form-data; boundary=boundary",
        "Content-Length": str(len(body)),
    })
    assert status == 400
    payload = json.loads(data)
    assert "error" in payload


def test_post_oversized(demo_server):
    host, port = demo_server
    status, data = _post(host, port, "/api/separate", b"x", {
        "Content-Type": "multipart/form-data; boundary=boundary",
        "Content-Length": str(51 * 1024 * 1024),
    })
    assert status == 413
    payload = json.loads(data)
    assert "error" in payload


def test_post_unknown_path(demo_server):
    host, port = demo_server
    status, data = _post(host, port, "/api/unknown", b"", {
        "Content-Type": "application/json",
        "Content-Length": "0",
    })
    assert status == 404


def test_post_response_is_json(demo_server):
    """Error responses from /api/separate must be valid JSON."""
    host, port = demo_server
    body = b"--b\r\nContent-Disposition: form-data; name=\"x\"\r\n\r\nval\r\n--b--\r\n"
    status, data = _post(host, port, "/api/separate", body, {
        "Content-Type": "multipart/form-data; boundary=b",
        "Content-Length": str(len(body)),
    })
    assert status in (400, 500)
    parsed = json.loads(data)
    assert isinstance(parsed, dict)
