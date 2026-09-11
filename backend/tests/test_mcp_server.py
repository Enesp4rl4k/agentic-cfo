"""The MCP server speaks the protocol, calls the API — and nothing else.

The backend is httpx's MockTransport throughout: every test that reaches the
API records the request, so the tests can say what was sent, with which key,
and — as often — that nothing was sent at all.
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import httpx
import pytest

from app.mcp.server import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SUPPORTED_PROTOCOLS,
    TOOLS,
    UPLOAD_MAX_BYTES,
    Backend,
    Server,
)

JOB = "8b0e8a4e-4a57-4f6a-9d7e-1f2b3c4d5e6f"
CLIENT = "0f1e2d3c-4b5a-4968-8776-655443322110"


def _server(handler=None, *, key: str = "test-key") -> tuple[Server, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if handler is None:
            return httpx.Response(200, json={"data": {}, "error": None})
        return handler(request)

    backend = Backend(base_url="http://csuite.test", api_key=key, transport=httpx.MockTransport(wrapped))
    return Server(backend), seen


def _call(server: Server, name: str, arguments: dict | None = None) -> dict:
    resp = server.handle({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    })
    assert resp is not None
    return resp


# ── Protocol ─────────────────────────────────────────────────────────────────

def test_initialize_agrees_on_a_version_the_client_asked_for() -> None:
    server, _ = _server()
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "t", "version": "0"}}})
    result = resp["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "c-suite"
    assert "onay vermez" in result["instructions"]


def test_an_unknown_version_gets_the_newest_we_speak() -> None:
    server, _ = _server()
    resp = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "1999-01-01"}})
    assert resp["result"]["protocolVersion"] == SUPPORTED_PROTOCOLS[0]


def test_notifications_get_no_reply() -> None:
    server, _ = _server()
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_ping() -> None:
    server, _ = _server()
    assert server.handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})["result"] == {}


def test_unknown_method_is_a_protocol_error() -> None:
    server, _ = _server()
    resp = server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert resp["error"]["code"] == METHOD_NOT_FOUND


def test_the_stdio_loop_answers_line_by_line_and_survives_garbage() -> None:
    server, _ = _server()
    stdin = io.StringIO(
        "not json\n"
        + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    stdout = io.StringIO()
    server.serve(stdin, stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line.get("id") for line in lines] == [None, 1, 2]
    assert lines[0]["error"]["code"] == PARSE_ERROR
    assert len(lines[2]["result"]["tools"]) == len(TOOLS)


# ── The tool list ────────────────────────────────────────────────────────────

def test_the_chain_is_exposed() -> None:
    assert set(TOOLS) == {
        "musteri_paneli", "dosya_yukle", "analiz_durumu", "muhasebe_calistir",
        "onay_kuyrugu", "mizan", "edefter_durumu",
    }


def test_there_is_no_way_to_approve_from_here() -> None:
    """The queue exists so a person decides. An AI client that could approve
    its own chain's output would make the confidence gate a formality."""
    for name, tool in TOOLS.items():
        assert "onayla" not in name and "approve" not in name
        desc = tool.description.lower()
        assert "onayla" not in desc.replace("onaylanır", "")


def test_every_tool_describes_itself_properly() -> None:
    server, _ = _server()
    tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert t["description"] and t["title"]
        assert t["annotations"]["destructiveHint"] is False
    writers = {t["name"] for t in tools if not t["annotations"]["readOnlyHint"]}
    assert writers == {"dosya_yukle", "muhasebe_calistir"}


# ── Calling the API ──────────────────────────────────────────────────────────

def test_a_call_goes_to_the_api_with_the_users_key() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"job_id": JOB, "status": "completed",
                                                  "logs": [f"l{i}" for i in range(25)]}, "error": None})

    server, seen = _server(handler)
    resp = _call(server, "analiz_durumu", {"job_id": JOB})
    result = resp["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["status"] == "completed"
    assert result["structuredContent"]["logs"] == [f"l{i}" for i in range(15, 25)]
    assert result["structuredContent"]["log_count"] == 25
    assert seen[0].url.path == f"/api/v1/analysis/{JOB}"
    assert seen[0].headers["x-api-key"] == "test-key"


@pytest.mark.parametrize(("tool", "method", "path"), [
    ("musteri_paneli", "GET", "/api/v1/smmm/dashboard"),
    ("muhasebe_calistir", "POST", "/api/v1/muhasebe/analiz"),
    ("onay_kuyrugu", "GET", f"/api/v1/smmm/onay/queue/{JOB}"),
    ("mizan", "GET", f"/api/v1/muhasebe/mizan/{JOB}"),
    ("edefter_durumu", "GET", f"/api/v1/muhasebe/{JOB}/e-defter/durum"),
])
def test_each_tool_hits_its_route(tool: str, method: str, path: str) -> None:
    server, seen = _server()
    args = {} if tool == "musteri_paneli" else {"job_id": JOB}
    assert _call(server, tool, args)["result"]["isError"] is False
    assert (seen[0].method, seen[0].url.path) == (method, path)


def test_running_the_chain_sends_the_job_as_json() -> None:
    server, seen = _server()
    _call(server, "muhasebe_calistir", {"job_id": JOB})
    assert json.loads(seen[0].content) == {"job_id": JOB}


def test_the_queue_says_who_decides() -> None:
    server, _ = _server(lambda r: httpx.Response(200, json={"data": {"kayitlar": []}, "error": None}))
    data = _call(server, "onay_kuyrugu", {"job_id": JOB})["result"]["structuredContent"]
    assert "web uygulamasından" in data["not"]


def test_period_is_passed_and_checked() -> None:
    server, seen = _server()
    _call(server, "edefter_durumu", {"job_id": JOB, "donem": "2024-01"})
    assert seen[0].url.params["donem"] == "2024-01"
    bad = _call(server, "edefter_durumu", {"job_id": JOB, "donem": "2024-13"})
    assert bad["result"]["isError"] and len(seen) == 1


def test_an_api_error_is_a_tool_error_with_the_reason() -> None:
    server, _ = _server(lambda r: httpx.Response(404, json={"detail": "Analiz iş kaydı bulunamadı."}))
    result = _call(server, "mizan", {"job_id": JOB})["result"]
    assert result["isError"] is True
    assert "404" in result["content"][0]["text"]
    assert "bulunamadı" in result["content"][0]["text"]


def test_an_unreachable_api_says_where_it_looked() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    server, _ = _server(down)
    result = _call(server, "musteri_paneli")["result"]
    assert result["isError"] and "csuite.test" in result["content"][0]["text"]


def test_without_a_key_nothing_is_sent_and_the_fix_is_named() -> None:
    server, seen = _server(key="")
    result = _call(server, "musteri_paneli")["result"]
    assert result["isError"] and "CSUITE_API_KEY" in result["content"][0]["text"]
    assert seen == []


@pytest.mark.parametrize("bad", ["../auth/api-key", "", "123", f"{JOB}/../x"])
def test_ids_are_checked_before_they_reach_a_url(bad: str) -> None:
    server, seen = _server()
    result = _call(server, "mizan", {"job_id": bad})["result"]
    assert result["isError"]
    assert seen == []


def test_unknown_tool_and_unknown_argument_are_protocol_errors() -> None:
    server, seen = _server()
    assert _call(server, "kayit_onayla", {"job_id": JOB})["error"]["code"] == INVALID_PARAMS
    assert _call(server, "mizan", {"job_id": JOB, "sql": "drop"})["error"]["code"] == INVALID_PARAMS
    assert seen == []


# ── Upload ───────────────────────────────────────────────────────────────────

def test_upload_sends_the_file_and_the_client(tmp_path: Path) -> None:
    f = tmp_path / "ocak.csv"
    f.write_text("tarih,açıklama,tutar\n2024-01-03,Satış,100\n", encoding="utf-8")
    server, seen = _server(lambda r: httpx.Response(200, json={"data": {"job_id": JOB}, "error": None}))
    result = _call(server, "dosya_yukle", {"path": str(f), "client_id": CLIENT})["result"]
    assert result["structuredContent"]["job_id"] == JOB
    req = seen[0]
    assert (req.method, req.url.path) == ("POST", "/api/v1/upload")
    body = req.content
    assert b'filename="ocak.csv"' in body
    assert b'name="client_id"' in body and CLIENT.encode() in body


@pytest.mark.parametrize("name", ["x.exe", "x.xml", "x"])
def test_upload_refuses_what_the_api_would(tmp_path: Path, name: str) -> None:
    f = tmp_path / name
    f.write_bytes(b"x")
    server, seen = _server()
    assert _call(server, "dosya_yukle", {"path": str(f)})["result"]["isError"]
    assert seen == []


def test_upload_refuses_more_than_ten_megabytes(tmp_path: Path) -> None:
    f = tmp_path / "big.csv"
    f.write_bytes(b"a" * (UPLOAD_MAX_BYTES + 1))
    server, seen = _server()
    result = _call(server, "dosya_yukle", {"path": str(f)})["result"]
    assert result["isError"] and "10 MB" in result["content"][0]["text"]
    assert seen == []


def test_upload_of_a_missing_file(tmp_path: Path) -> None:
    server, seen = _server()
    assert _call(server, "dosya_yukle", {"path": str(tmp_path / "yok.csv")})["result"]["isError"]
    assert seen == []


# ── It is a client of the API and nothing more ───────────────────────────────

def test_the_mcp_package_imports_nothing_from_the_app() -> None:
    """Reaching past the API would skip auth, org scoping and ownership."""
    pkg = Path(__file__).resolve().parents[1] / "app" / "mcp"
    for path in pkg.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app.") or node.module.startswith("app.mcp"), (
                    f"{path.name} imports {node.module}"
                )
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app.") or alias.name.startswith("app.mcp")
