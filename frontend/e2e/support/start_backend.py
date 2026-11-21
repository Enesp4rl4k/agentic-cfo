"""Start the real API for the browser test on a fresh SQLite database.

No Docker, no Redis, no LLM key: SQLite builds its tables on startup, and an upload's
analysis runs inline when no broker answers (the product's own fallback for SQLite).
The database lives in `frontend/e2e/.run/` and is deleted first, so every run starts
from an empty company list.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE.parent / ".run"
BACKEND = HERE.parents[2] / "backend"


def wait_for_first_api() -> None:
    import time
    import urllib.request

    deadline = time.time() + 240
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/v1/system/health", timeout=5)
            return
        except Exception:
            time.sleep(2)
    raise SystemExit("the first API never came up")


def main() -> None:
    port = os.environ.get("E2E_API_PORT", "8000")
    env = os.environ
    # The second API (E2E_WITH_MODEL=1) shares the first one's database and folder: it is the same
    # product with a model behind it (the stub), used only by the step that needs one. It waits
    # for the first to have built its database, and never deletes anything.
    with_model = env.get("E2E_WITH_MODEL") == "1"
    if with_model:
        wait_for_first_api()
    else:
        if RUN.exists():
            shutil.rmtree(RUN)  # only this folder, created by this script
        RUN.mkdir(parents=True)
    os.chdir(RUN)
    env.update(
        {
            "USE_SQLITE": "true",
            "LANGGRAPH_CHECKPOINT": "memory",
            "LOG_FORMAT": "plain",
            # No model: the product answers from its templates, as it does without a key.
            "OPENAI_API_KEY": "llm-placeholder-e2e",
            "BACKEND_SECRET_KEY": env.get("BACKEND_SECRET_KEY", "e2e-throwaway-signing-key-0123456789abcdef"),
            "BACKEND_CORS_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
            # Nothing is sent anywhere: no SMTP, so the outbox keeps what would have gone out.
            "SMTP_HOST": "",
            "SMTP_USER": "",
            "PYTHONPATH": str(BACKEND) + os.pathsep + env.get("PYTHONPATH", ""),
        }
    )
    if with_model:
        # A key that is not a placeholder, aimed at the stub (support/llm_stub.py): the stub answers
        # the boardroom's structured calls and refuses every other call with a 503.
        env["OPENAI_API_KEY"] = "e2e-stub-key-not-a-secret"
        env["LLM_BASE_URL"] = f"http://127.0.0.1:{env.get('E2E_LLM_PORT', '8099')}"
    # The API's log goes to a file CI uploads when the run fails.
    with open(RUN / ("api-model.log" if with_model else "api.log"), "w", encoding="utf-8") as log:
        sys.exit(
            subprocess.call(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        )


if __name__ == "__main__":
    main()
