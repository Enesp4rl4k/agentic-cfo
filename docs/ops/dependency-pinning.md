# Backend dependency pinning

Every backend environment (CI, `e2e.yml`, `backend/Dockerfile`) installs with

    pip install -r requirements.txt -c constraints.txt

- `backend/requirements.txt` is the human-edited list of **direct** dependencies. Every line is `name==version`.
- `backend/constraints.txt` pins **every** package pip installs, direct and transitive. It is generated, never edited by hand.
- `backend/tests/test_dependency_pins.py` fails when a direct dependency is not an exact pin, when the two files disagree, when an install line in the workflows or the Dockerfile omits `-c constraints.txt`, and (in the Backend CI job, `CHECK_INSTALLED_PINS=1`) when the installed environment differs from the lock in either direction.

Why: this product handles companies' financial data. A numerical library that changes between two runs changes forecasts; a crypto library that changes between two runs changes behaviour. A dependency changes when a person decides it does, in a reviewed diff.

The lock is a plain version list for Python 3.12 on Linux (it includes `uvloop`, for example). It carries no hashes. Hash-pinning (`pip-compile --generate-hashes`, `--require-hashes`) is the next step if the owner wants it.

## Bump one dependency deliberately

1. Read the changelog. Do not take a major version here without a migration plan (Sentry 3.x and LangChain 0.3 are such cases; Pillow 13 and WeasyPrint 70 were taken deliberately in the PDF-parser security PR, see below).
2. Edit the one line in `backend/requirements.txt`.
3. Regenerate the lock on Linux with Python 3.12 (a throwaway `python:3.12-slim` container or a CI job; not a Windows or macOS environment, whose resolution differs). Install **without** `-c`, so pip resolves the new set, then freeze it:

       python -m venv /tmp/lock
       /tmp/lock/bin/pip install -r requirements.txt
       /tmp/lock/bin/pip freeze --all | grep -vi '^pip==' | tr 'A-Z_' 'a-z-' | sort

   (`tr` normalises names to lower case with hyphens; `pip freeze` writes `name==version` lines.) Replace the package lines of `constraints.txt`, keep its header, update the "Origin" line. Only the packages in your diff and their dependencies should change; if dozens of lines move, something floated and needs a look.
4. Run the suite: `pytest tests/`, `mypy --config-file mypy_strict.ini`, `ruff check app/`, and the pins test with `CHECK_INSTALLED_PINS=1`.
5. **Numerical libraries (`numpy`, `scipy`, `scikit-learn`, `statsmodels`, `pandas`, `patsy`, `joblib`):** also re-run the forecast and eval golden tests (`pytest -m eval` and the forecast/anomaly tests) and compare the outputs, not only pass or fail. A change in a forecast figure needs a human to say it is expected.
5b. **PDF libraries (`pdfminer.six`, `pdfplumber`, `pymupdf`, `pillow`):** the suite generates its PDFs and has no real bank-statement fixture, so it cannot see a change in extracted text. Run `backend/scripts/pdf_extraction_snapshot.py` (usage in its docstring) in the old and the new environment and diff the two JSON files; any difference in text, tables or word boxes is a finding to read, not to merge past. For the 0.11.3 -> 0.11.9 / 20231228 -> 20251230 bump the diff was empty on the seven-file synthetic corpus.
6. **Crypto and auth (`cryptography`, `bcrypt`, `passlib`, `python-jose`, `ecdsa`, `rsa`):** confirm login, token issue and verify, and the connector-secret decrypt of an existing ciphertext still work.
7. Commit `requirements.txt` and `constraints.txt` together, one dependency (or one coherent group) per PR.

## Known advisories and why they are, or are not, reachable

Checked against OSV / the GitHub Advisory Database on 2026-11-23 for every version in `constraints.txt`
(`POST https://api.osv.dev/v1/querybatch` with the 137 pins). Re-run it when the lock changes. The first four rows were
reachable from a company's upload and were fixed by upgrading; the rest are open and are listed so that a change
which makes one of them reachable is noticed in review.

| Package (locked) | Advisories | Status |
|---|---|---|
| `pdfminer.six` 20231228 -> **20251230** | GHSA-wf5f-4jwr-ppcp (CVE-2025-64512, HIGH, fixed 20251107); GHSA-f83h-ghpp-7wcc (CVE-2025-70559, HIGH, fixed 20251230) | **Reachable** (pdfplumber runs on uploaded PDFs, `app/services/ocr_service.py` strategy 2). Fixed. The CMap loader now reads JSON, not pickle; `tests/test_pdf_upload_guard.py` fails if `pickle` returns to `pdfminer.cmapdb` or the version drops below 20251230. |
| `pdfplumber` 0.11.3 -> **0.11.9** | none of its own; pins `pdfminer.six==20251230` | 0.11.9 is the first release that pins a fixed pdfminer (0.11.10 and later need Pillow >= 13, also met now). |
| `Pillow` 12.3.0 -> **13.0.0** | 40+ advisories, all fixed in 13.0.0 (5 CRITICAL: GHSA-332p-7hrc-92wf, GHSA-5x8w-8jj5-q52h, GHSA-8g5g-8vmr-9782, GHSA-v9pv-5gc8-w2m6, GHSA-w889-685w-c8fh; the rest HIGH/MODERATE, mostly TIFF/EPS/GIF/PDF-writer codecs) | **Not reachable from user bytes**: users upload pdf/xlsx/csv/xml only (`upload_service.ALLOWED_EXTENSIONS`), no raw image file is accepted, and the only `Image.open` is on the PNG PyMuPDF has just rendered (`ocr_service._try_tesseract_ocr`, `formats=["PNG"]`, pixel ceiling `MAX_RENDER_PIXELS`). Upgraded anyway: the release only removes APIs the repo does not call, and pdfplumber 0.11.10+ requires it. |
| `weasyprint` 69.0 -> **70.0** | GHSA-jf6q-chmf-3h3v (CVE-2026-55073, MODERATE, SSRF through `write_pdf(xmp_metadata=..., stylesheets=...)` ignoring `url_fetcher`); GHSA-r543-q48m-4c9j (CVE-2026-106443, HIGH, EPS images reach Ghostscript) | The first needs those two `write_pdf` arguments, which no caller passes. The second needs Ghostscript, which the backend image does not install. Reachability of fetching in general was real (company names reached HTML unescaped) and is closed independently: every render passes `app/services/pdf_fetch.deny_fetcher()` (`tests/test_report_render_no_fetch.py`). Fixed by upgrade. |
| `python-jose` 3.5.0 | GHSA-3qf3-8w2g-rqmx (CVE-2024-33663, CRITICAL, algorithm confusion with ECDSA/PEM public keys; no fixed release) | **Not reachable today**: the only use is `jwt.decode(token, secret, algorithms=["HS256"])` with a symmetric secret (`app/services/auth.py:27,94`). Becomes reachable if anyone verifies with an asymmetric key or lets the header choose the algorithm. Replacement is a follow-up. |
| `ecdsa` 0.19.2 | GHSA-wj6h-64fc-37mp (CVE-2024-23342, HIGH, Minerva timing side channel; no fixed release) | **Not reachable**: pulled in by python-jose only; nothing here signs with ECDSA. |
| `langchain` 0.2.17 (**removed**), `langchain-core` 0.2.43 -> **1.4.9**, `langchain-text-splitters` 0.2.4 (**removed**), `langsmith` 0.1.147 -> **0.9.8**, `langgraph` 0.1.19 -> **1.2.24**, `langchain-openai` 0.1.25 -> **1.1.9** | 17 distinct advisories on the old set, 8 HIGH/CRITICAL: CVE-2026-45134 (langchain, langsmith), CVE-2026-34070 (`load_prompt` path traversal; langchain-core fixed only in **1.2.22**, the 0.3 line never got it), CVE-2026-44843, CVE-2025-68664 (CRITICAL, `dumps/load` injection), CVE-2025-65106, CVE-2025-6985 (text splitters XXE), GHSA-f4xh-w4cj-qxq8 (langsmith, fixed 0.8.18) | **Fixed by upgrade; none were reachable.** The code imports only `langgraph` (`StateGraph`, `MemorySaver`, `SqliteSaver`, `PostgresSaver`), `langchain_openai` (`ChatOpenAI` in `app/platform/model_gateway.py`, `OpenAIEmbeddings` in `rag_service`) and `langchain_core.messages`; no `langchain` import, prompt template, `load/dumps`, `load_prompt` or splitter, so the `langchain` package and the splitters were dropped. 1.x was unavoidable (0.3.x does not clear CVE-2026-34070). `SqliteSaver` now lives in `langgraph-checkpoint-sqlite` (direct pin). langchain-openai stays on 1.1.x, the newest line that accepts the pinned `openai` 1.109.1; the LOW GHSA-r7w7-9xr2-qq2r (fixed 1.1.14) needs openai 2.x and is a follow-up. langchain-core depends on langsmith, so tracing is locked off in `app/services/telemetry.py`: every tracing switch is forced to `false` at import and `LANGSMITH_ENABLED=true` additionally needs `LANGSMITH_EXTERNAL_TRACING_ACK` (`tests/test_langsmith_lock.py`). |

Defence in depth for uploaded PDFs, independent of any parser version. Every parser of an uploaded PDF's bytes (PyMuPDF text, pdfplumber
tables, the OCR render with Pillow, Tesseract, the e-Belge attachment) runs in a child process (`app/services/pdf_isolation.py`; its code is
`ocr_service.py` and `pdf_embedded.py`, and `tests/test_parser_isolation_fitness.py` fails if any other module imports a parser). The child gets no
secrets, its own process group (killed whole on timeout), `RLIMIT_AS` and `RLIMIT_CPU`, a capped stdout, and a semaphore bounds how many run at once.
Limits are settings: `MAX_UPLOAD_SIZE_MB`, `PDF_MAX_PAGES` (500), `PDF_PARSE_TIMEOUT_SECONDS` (180), `PDF_OCR_SECONDS_PER_PAGE` (30, added per OCR page),
`PDF_CHILD_MEMORY_MB`, `PDF_PARSE_CONCURRENCY`. A refusal, crash or timeout is a visible "PDF okunamadi" that names the limit and what to do, never an empty
success. The XML of an e-Belge is parsed by `app.core.xml_safety` (stdlib parser, DTD and ENTITY refused before parsing; refused again inside the child).

Spreadsheets are the same class of risk: an .xlsx is a zip of XML, so a few kilobytes can inflate to gigabytes or declare entities that expand. openpyxl,
`zipfile` and the csv module read uploaded bytes only in `app/services/sheet_child.py` (child process, started by `sheet_isolation`; same `run_worker`
as the PDF child; `tests/test_parser_isolation_fitness.py` fails if `openpyxl`, `xlrd`, `read_excel` or `load_workbook` appear anywhere else). The child caps
the zip's member count and total uncompressed size (from the zip directory and again while reading), rows, columns and cells, runs openpyxl with
`read_only=True, data_only=True`, and refuses to run unless `defusedxml` is active (`defusedxml==0.7.1`, direct dependency; openpyxl uses it automatically
when importable). Settings and sizing: `docs/ops/parser-sizing.md`.

## Frontend

`frontend/package-lock.json` is committed and every install uses `npm ci`. The ranges in `package.json` (`^`) are resolved by the lock; update with `npm install <pkg>@<version>` and commit both files.
