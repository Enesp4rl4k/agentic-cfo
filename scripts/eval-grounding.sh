#!/usr/bin/env bash
# Offline grounding eval — invented numbers must be caught without calling an LLM.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"
python -m pytest tests/test_agents/test_grounding_eval.py tests/test_agents/test_rag_grounding.py tests/test_agents/test_chat_grounding.py -q --tb=short
