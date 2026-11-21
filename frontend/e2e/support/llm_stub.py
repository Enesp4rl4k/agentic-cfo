"""A stand-in for the model provider, at the HTTP boundary the app already abstracts.

The API reads `LLM_BASE_URL` and calls an OpenAI-compatible `/chat/completions`. This server
answers only the boardroom's three structured calls (the one place the journey needs a model: it
is what puts an action in front of the owner) and refuses everything else with a 503, exactly as
an unreachable provider would, so every other screen stays on its deterministic, template path.
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ACTION = "CFO: Mavi Tekstil'den 60.000 TL tahsilat için hatırlatma e-postası gönderilecek"


def arguments_for(name: str, schema: dict) -> dict:
    props = schema.get("properties", {})
    out: dict = {}
    for key, spec in props.items():
        kind = spec.get("type")
        if key == "action_items":
            out[key] = [ACTION]
        elif key == "resolution_status":
            out[key] = "CEO Kararı Bekleniyor"
        elif key == "confidence_score":
            out[key] = 0.9
        elif kind == "number":
            out[key] = 0.9
        elif kind == "array":
            out[key] = ["Tahsilat takibi"]
        else:
            out[key] = f"{key}: tahsilat takibi önceliklidir"
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the test output quiet
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        tools = body.get("tools") or []
        names = [t.get("function", {}).get("name", "") for t in tools]
        if not any(n.startswith("Boardroom") for n in names):
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"e2e stub: no model for this call"}}')
            return
        fn = tools[0]["function"]
        call = {
            "id": "call_e2e",
            "type": "function",
            "function": {"name": fn["name"], "arguments": json.dumps(arguments_for(fn["name"], fn.get("parameters", {})))},
        }
        reply = {
            "id": "chatcmpl-e2e",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", "stub"),
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": None, "tool_calls": [call]}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # readiness probe for the test runner
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


if __name__ == "__main__":
    port = int(os.environ.get("E2E_LLM_PORT", "8099"))
    # Loopback only, a test double: plain HTTP is what the app's provider client speaks to it.
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()  # NOSONAR
    sys.exit(0)
