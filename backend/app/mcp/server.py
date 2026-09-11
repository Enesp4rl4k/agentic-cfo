"""C-Suite MCP sunucusu — uyum zinciri, bir yapay zekâ istemcisine araç olarak.

Model Context Protocol over stdio: newline-delimited JSON-RPC 2.0 on stdin and
stdout, logs on stderr. Claude Desktop, Claude Code or any MCP client can then
upload a client's books, follow the analysis, run the accounting chain, and
read the approval queue, the trial balance and how far the e-Defter is from
filing — in one conversation.

It is a *client* of the running C-Suite API, not a second way into the
database. Every call goes over HTTP with the user's own API key, so the same
authentication, organisation scoping, ownership checks and rate limits apply
as for the web app. This module imports nothing from the rest of `app`, and a
test keeps it that way: an MCP tool that reached past the API would be a door
around all of it.

What it deliberately does not offer is approval. The SMMM queue exists so a
person looks at the entries the machine was unsure about; a tool that let an
AI client approve its own chain's output would turn the confidence gate into a
formality. The queue is readable here and decided in the web app.

Usage:

    # 1. create an API key once (web app, or POST /api/v1/auth/api-key)
    # 2. register the server, e.g. with Claude Code:
    claude mcp add c-suite -e CSUITE_URL=http://127.0.0.1:8000 \\
        -e CSUITE_API_KEY=<anahtar> -- python backend/app/mcp/server.py

The protocol is small enough to implement directly (initialize, ping,
tools/list, tools/call), which keeps the server free of new dependencies.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import httpx

logger = logging.getLogger("csuite.mcp")

SERVER_NAME = "c-suite"
SERVER_VERSION = "1.0.0"
# Newest first. A client asking for one of these gets it; anything else gets
# the newest, and the client decides whether it can live with that.
SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

API_PREFIX = "/api/v1"
UPLOAD_EXTENSIONS = frozenset({".pdf", ".xlsx", ".csv"})   # CLAUDE.md law 9
UPLOAD_MAX_BYTES = 10 * 1024 * 1024
# Job and client ids are UUIDs. Checked here because they are interpolated into
# a URL path, and "../auth/api-key" is also a string.
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_DONEM = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

INSTRUCTIONS = (
    "C-Suite: Türk şirketleri ve mali müşavirler için uyum zinciri. Tipik akış: "
    "musteri_paneli → dosya_yukle → analiz_durumu (tamamlanana kadar) → "
    "muhasebe_calistir → onay_kuyrugu / mizan / edefter_durumu. Onay kuyruğundaki "
    "kayıtlar yalnızca insan tarafından web uygulamasında onaylanır; bu sunucu "
    "onay vermez. e-Defter beyan edilebilir değildir — edefter_durumu hangi "
    "adımların eksik olduğunu söyler. Tutarlar kuruş cinsindendir."
)

# ── JSON-RPC ─────────────────────────────────────────────────────────────────

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolFailure(Exception):
    """A tool ran and failed — reported to the model as isError, not as a protocol error."""


# ── The backend ──────────────────────────────────────────────────────────────

@dataclass
class Backend:
    base_url: str
    api_key: str
    transport: httpx.BaseTransport | None = None
    timeout: float = 300.0

    @classmethod
    def from_env(cls) -> Backend:
        return cls(
            base_url=os.environ.get("CSUITE_URL", "http://127.0.0.1:8000").rstrip("/"),
            api_key=os.environ.get("CSUITE_API_KEY", ""),
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        data: dict[str, str] | None = None,
    ) -> Any:
        if not self.api_key:
            raise ToolFailure(
                "CSUITE_API_KEY tanımlı değil. Web uygulamasında (ya da POST "
                "/api/v1/auth/api-key ile) bir API anahtarı oluşturup MCP "
                "sunucusunun ortamına CSUITE_API_KEY olarak ekleyin."
            )
        url = f"{self.base_url}{API_PREFIX}{path}"
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                resp = client.request(
                    method, url, params=params, json=json_body, files=files, data=data,
                    headers={"X-API-Key": self.api_key, "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise ToolFailure(f"C-Suite API'ye ulaşılamadı ({self.base_url}): {exc}") from exc

        try:
            body: Any = resp.json()
        except ValueError:
            body = None
        if resp.status_code >= 400:
            detail = ""
            if isinstance(body, dict):
                detail = str(body.get("error") or body.get("detail") or "")
            raise ToolFailure(
                f"C-Suite API {resp.status_code} döndü: {detail or resp.text[:300]}"
            )
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body


# ── Tools ────────────────────────────────────────────────────────────────────

@dataclass
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    run: Callable[[Backend, dict[str, Any]], Any]
    idempotent: bool = True

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.idempotent,
                "openWorldHint": False,
            },
        }


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_JOB = {"job_id": {"type": "string", "description": "Analiz işinin kimliği (UUID), dosya_yukle döndürür."}}


def _uuid(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not _UUID.match(value):
        raise ToolFailure(f"{key} bir UUID olmalı: {value!r}")
    return value


def _musteri_paneli(api: Backend, args: dict[str, Any]) -> Any:
    return api.request("GET", "/smmm/dashboard")


def _dosya_yukle(api: Backend, args: dict[str, Any]) -> Any:
    path = Path(str(args.get("path") or "")).expanduser()
    if path.suffix.lower() not in UPLOAD_EXTENSIONS:
        raise ToolFailure(f"yalnızca {', '.join(sorted(UPLOAD_EXTENSIONS))} yüklenebilir: {path.name!r}")
    if not path.is_file():
        raise ToolFailure(f"dosya bulunamadı: {path}")
    size = path.stat().st_size
    if size > UPLOAD_MAX_BYTES:
        raise ToolFailure(f"dosya {size} bayt — sınır {UPLOAD_MAX_BYTES} bayt (10 MB)")
    form: dict[str, str] = {}
    if args.get("client_id"):
        form["client_id"] = _uuid(args, "client_id")
    ctype = {".pdf": "application/pdf", ".csv": "text/csv"}.get(
        path.suffix.lower(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    return api.request(
        "POST", "/upload",
        files={"file": (path.name, path.read_bytes(), ctype)},
        data=form or None,
    )


def _analiz_durumu(api: Backend, args: dict[str, Any]) -> Any:
    data = api.request("GET", f"/analysis/{_uuid(args, 'job_id')}")
    if isinstance(data, dict) and isinstance(data.get("logs"), list):
        # The full log can run to hundreds of lines; the model needs the tail.
        logs = data["logs"]
        data = {**data, "logs": logs[-10:], "log_count": len(logs)}
    return data


def _muhasebe_calistir(api: Backend, args: dict[str, Any]) -> Any:
    return api.request("POST", "/muhasebe/analiz", json_body={"job_id": _uuid(args, "job_id")})


def _onay_kuyrugu(api: Backend, args: dict[str, Any]) -> Any:
    data = api.request("GET", f"/smmm/onay/queue/{_uuid(args, 'job_id')}")
    note = "Bu kayıtlar mali müşavirin kararını bekliyor; onay web uygulamasından verilir."
    return {**data, "not": note} if isinstance(data, dict) else {"kayitlar": data, "not": note}


def _mizan(api: Backend, args: dict[str, Any]) -> Any:
    return api.request("GET", f"/muhasebe/mizan/{_uuid(args, 'job_id')}")


def _edefter_durumu(api: Backend, args: dict[str, Any]) -> Any:
    params: dict[str, str] = {}
    if args.get("donem"):
        donem = str(args["donem"])
        if not _DONEM.match(donem):
            raise ToolFailure(f"donem YYYY-AA olmalı: {donem!r}")
        params["donem"] = donem
    return api.request("GET", f"/muhasebe/{_uuid(args, 'job_id')}/e-defter/durum", params=params or None)


TOOLS: dict[str, Tool] = {t.name: t for t in (
    Tool(
        "musteri_paneli", "Müşteri paneli",
        "Mali müşavirin müşterileri ve her birinin zincirdeki yeri: veri yok, analiz edildi, "
        "onay bekliyor, başarısız, mühürlendi. Özet sayılar ve dikkat isteyenler listesiyle. "
        "Bir müşteri için dosya yüklerken gereken client_id buradan alınır.",
        _schema({}, []), True, _musteri_paneli,
    ),
    Tool(
        "dosya_yukle", "Dosya yükle",
        "Banka ekstresi, muhasebe dökümü ya da fatura dosyasını (csv, xlsx, pdf; en fazla 10 MB) "
        "yerel diskten yükler ve analizi başlatır. client_id verilirse iş o müşteriye bağlanır. "
        "Dönen job_id sonraki araçlarda kullanılır.",
        _schema({
            "path": {"type": "string", "description": "Yüklenecek dosyanın yerel yolu."},
            "client_id": {"type": "string", "description": "İsteğe bağlı: musteri_paneli'ndeki müşteri kimliği."},
        }, ["path"]),
        False, _dosya_yukle, idempotent=False,
    ),
    Tool(
        "analiz_durumu", "Analiz durumu",
        "Bir analiz işinin durumu (queued, running, completed, failed, awaiting_review), en düşük "
        "güven skoru ve son günlük satırları. İş tamamlanana kadar aralıklarla sorgulanır.",
        _schema(_JOB, ["job_id"]), True, _analiz_durumu,
    ),
    Tool(
        "muhasebe_calistir", "Muhasebe zincirini çalıştır",
        "Tamamlanmış analizin işlemlerinden THP sınıflandırması ve çift taraflı yevmiye kayıtları "
        "üretir. Emin olunamayan kayıtlar (düşük güven, yüksek tutar, belirsiz tarih, ayrıştırılmamış "
        "KDV) onay kuyruğuna düşer.",
        _schema(_JOB, ["job_id"]), False, _muhasebe_calistir, idempotent=False,
    ),
    Tool(
        "onay_kuyrugu", "Onay kuyruğu",
        "Mali müşavirin onayını bekleyen yevmiye kayıtları ve her birinin gerekçesi. Salt okunur: "
        "onay bu sunucudan verilemez, web uygulamasında insan tarafından verilir.",
        _schema(_JOB, ["job_id"]), True, _onay_kuyrugu,
    ),
    Tool(
        "mizan", "Mizan",
        "Yevmiye kayıtlarından hesap bazında borç, alacak ve bakiye (kuruş).",
        _schema(_JOB, ["job_id"]), True, _mizan,
    ),
    Tool(
        "edefter_durumu", "e-Defter durumu",
        "GİB e-Defter beyanına giden yolun her adımı ve hangilerinin gerçekten yapıldığı: defter, "
        "mali mühür imzası, berat, paket, gönderim. Kayıtlar birden fazla aya yayılıyorsa donem "
        "(YYYY-AA) verilmelidir.",
        _schema({**_JOB, "donem": {"type": "string", "description": "İsteğe bağlı dönem, YYYY-AA."}}, ["job_id"]),
        True, _edefter_durumu,
    ),
)}


# ── The server ───────────────────────────────────────────────────────────────

class Server:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend

    def handle(self, message: Any) -> dict[str, Any] | None:
        """One JSON-RPC message in, one response out (None for a notification)."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "JSON-RPC 2.0 isteği bekleniyordu")
        method = message.get("method")
        msg_id = message.get("id")
        is_notification = "id" not in message
        if not isinstance(method, str):
            # A response from the client (to a request we never send) or junk.
            return None if is_notification else _error(msg_id, INVALID_REQUEST, "method yok")
        try:
            result = self._dispatch(method, message.get("params") or {})
        except RpcError as exc:
            return None if is_notification else _error(msg_id, exc.code, exc.message)
        except Exception as exc:  # pragma: no cover - last resort, logged
            logger.exception("MCP %s failed", method)
            return None if is_notification else _error(msg_id, INTERNAL_ERROR, str(exc))
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            requested = str(params.get("protocolVersion") or "")
            return {
                "protocolVersion": requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "title": "C-Suite", "version": SERVER_VERSION},
                "instructions": INSTRUCTIONS,
            }
        if method.startswith("notifications/"):
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t.describe() for t in TOOLS.values()]}
        if method == "tools/call":
            name = params.get("name")
            tool = TOOLS.get(str(name))
            if tool is None:
                raise RpcError(INVALID_PARAMS, f"bilinmeyen araç: {name!r}")
            args = params.get("arguments") or {}
            if not isinstance(args, dict):
                raise RpcError(INVALID_PARAMS, "arguments bir nesne olmalı")
            unknown = set(args) - set(tool.input_schema["properties"])
            if unknown:
                raise RpcError(INVALID_PARAMS, f"{name} bu argümanları tanımıyor: {sorted(unknown)}")
            return _call(tool, self.backend, args)
        raise RpcError(METHOD_NOT_FOUND, f"desteklenmeyen yöntem: {method}")

    def serve(self, stdin: IO[str], stdout: IO[str]) -> None:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                response: dict[str, Any] | None = _error(None, PARSE_ERROR, "geçersiz JSON")
            else:
                response = self.handle(message)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()


def _call(tool: Tool, backend: Backend, args: dict[str, Any]) -> dict[str, Any]:
    try:
        data = tool.run(backend, args)
    except ToolFailure as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2, default=str)}],
        "isError": False,
    }
    if isinstance(data, dict):
        result["structuredContent"] = data
    return result


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def main() -> None:
    # stdout belongs to the protocol; anything else written there corrupts it.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for stream in (sys.stdin, sys.stdout):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    backend = Backend.from_env()
    if not backend.api_key:
        logger.warning("CSUITE_API_KEY tanımlı değil — araçlar çağrıldığında bunu söyleyecek")
    logger.info("C-Suite MCP sunucusu: %s", backend.base_url)
    Server(backend).serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
