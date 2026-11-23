# Sizing the file parsers (PDF, spreadsheet, CSV)

Every parser of an uploaded file runs in a **child process** (`app/services/pdf_isolation.py` for PDFs,
`app/services/sheet_isolation.py` for .xlsx and CSV; one mechanism, `pdf_isolation.run_worker`). The child
has an address-space limit (`RLIMIT_AS`, Linux), a CPU limit, a deadline, and its own process group that is
killed whole on timeout. This page says how many of them can exist at once, what they were measured to need,
and how the container is sized for that.

## Two different numbers: address space and resident memory

* `RLIMIT_AS` (`PDF_CHILD_MEMORY_MB`, `SHEET_CHILD_MEMORY_MB`) limits **address space**: everything mapped, used
  or not (Python, PyMuPDF, pdfplumber, Pillow, thread stacks, allocator arenas). It is always larger than the
  resident set, and Tesseract (a grandchild) inherits it. It is only a **backstop**: it stops a runaway child
  with a clean `MemoryError`, long before the kernel would step in.
* The **container's cgroup limit** (compose `mem_limit`, Kubernetes `limits.memory`) is the hard wall, and it
  counts **resident** memory. When it is hit the kernel's OOM killer picks the victim, and it may pick the API
  process itself. The container must therefore hold what the children actually use: `PARSE_CHILD_RSS_MB`.

The preflight's sizing rule uses `PARSE_CHILD_RSS_MB`, never `RLIMIT_AS`.

## Measured (Linux, Python 3.12/3.14, PyMuPDF 1.28.2, pdfplumber 0.11.9)

`backend/tests/test_parser_memory_measure.py` (the hardening step of the Backend CI job) generates the documents
with PyMuPDF, runs the real child, and reads `VmPeak` (peak address space) and `VmHWM` (peak resident set) from
the child itself (`@@PEAK@@` line, also logged by the parent at INFO) and from `/proc` for Tesseract. It prints the
numbers into the CI log and the job summary and fails if the defaults lose their headroom.

| Input | Child VmPeak | Child VmHWM | Tesseract VmPeak / VmHWM |
|---|---|---|---|
| 300-page text statement, ruled tables, 42 rows a page | 120 MB | 84 MB | none |
| 300 pages thin enough to go through pdfplumber every page | 140 MB | 101 MB | none |
| 10-page full-colour scan, OCR at 300 dpi (`tur+eng`) | **517 MB** | 256 MB | 205 MB / 137 MB |
| .xlsx, 600 000 cells (2.8 MB file) | 105 MB | 90 MB | none |

These are the CI numbers (Linux, Python 3.12, one run; the 300-page text and OCR rows are in the Backend CI log
as `PARSER MEMORY ...` lines). Two things follow. The 512 MB `RLIMIT_AS` of the first version of this change was
**below** the OCR child's own 517 MB peak: every scanned statement would have failed. And Tesseract itself is
small (205 MB of address space), so the child that renders the page, not Tesseract, sets the limit.

Memory does not grow with the page count: a page is rendered, read and released, so 300 pages cost the same as
3. What grows it is the page *size* (a 300 dpi A4 render is about 26 MB, several copies at once) and, for
spreadsheets, the number of cells (`SHEET_MAX_CELLS` bounds it).

## Defaults, with headroom

| Setting | Default | From |
|---|---|---|
| `PDF_CHILD_MEMORY_MB` (RLIMIT_AS backstop) | 1536 | 517 MB (the OCR child) x 3. The test requires at least x 1.5 |
| `PARSE_CHILD_RSS_MB` (resident budget per child) | 800 | 256 + 137 = 393 MB resident (child + Tesseract) x 2. The test requires at least x 1.25 |
| `SHEET_CHILD_MEMORY_MB` | 512 | 105 MB measured for 600 000 cells (the cap is 1 000 000), about 3x |
| `PDF_PARSE_CONCURRENCY` | 1 | the long statements and scans are the core input: one child gets what it needs |

## The bound is per process, not per system

The slots are a semaphore **inside each process**: `PDF_PARSE_CONCURRENCY` children at a time per uvicorn
worker, and per arq worker process. PDF and spreadsheet children share the slots. In the production compose
stack `backend` runs `uvicorn --workers 2` and `worker` runs one arq process. A cross-process bound would need a
counting semaphore in Redis; the repo's Redis lock (`app/core/distributed_lock.py`) is a mutex, not a counter, so
none was added. A request that waits for a slot longer than `PARSE_QUEUE_WAIT_SECONDS` (60) is refused with a
visible "Sistem yoğun, tekrar deneyin" message.

## The sizing rule

For each container that runs parser children (API and analysis worker; **not** `migrate`, the maintenance
worker or `--db` checks):

    PARSE_CHILD_RSS_MB x PDF_PARSE_CONCURRENCY x (API worker processes, 1 for an arq worker)  <  memory limit

with room for the process itself (about 300 MB per API process). `PARSE_PROCESS_COUNT` is the number of API worker
processes (`uvicorn --workers`). Shipped limits:

| Service | Limit | Why |
|---|---|---|
| `backend` (compose) | 2560m | 2 x 800 for children + 2 x about 350 for the API processes, rounded up. Was 1280m. |
| `worker` (compose) | 2g | 800 for one child + the arq process and its jobs. Was 1280m. |
| `worker-maintenance` (compose) | 768m | parses no uploads: unchanged |
| `migrate` (compose) | 512m | parses nothing: unchanged, and exempt from the rule |
| Kubernetes / Helm | backend 2Gi, worker 4Gi, maintenance 1.5Gi | already hold the rule |

## What a limit looks like to the user

A child that runs out of memory is never an empty page and never "damaged": a `MemoryError` anywhere in the parse
(a page, Tesseract's failed allocation, opening the document), or the kernel ending the child, is the refusal
"dosya bellek sınırını aştı; daha kısa dönemlere bölüp yükleyin" (English underneath), naming the pages that were
not read. A page that yields no text although it has content is listed ("Sayfa N okunamadı") on the ingestion
result and holds it for review.

## Preflight

At start-up `app/core/preflight.py` reads the container's cgroup limit (v2 `/sys/fs/cgroup/memory.max`, v1
`/sys/fs/cgroup/memory/memory.limit_in_bytes`; nothing is said where the files are absent or unlimited) and, **only
for the `api` and `worker` processes**:

* logs a **WARNING** `parser_memory_exceeds_container` when the rule above is not met;
* is **FATAL** (production only) `parser_memory_impossible` when one child's `PARSE_CHILD_RSS_MB` is as large as the
  container.

`tests/test_parser_memory_deploy_matrix.py` runs the rule against every service in `docker-compose.prod.yml`, every
Kubernetes workload and the Helm values, each with its declared limit and the processes it starts, so a default
deploy cannot be stopped by it again.

## Spreadsheet limits

`SHEET_PARSE_TIMEOUT_SECONDS` (90), `SHEET_MAX_UNCOMPRESSED_MB` (128, the total of an .xlsx's zip members,
checked from the zip directory and counted again while members are read), `SHEET_MAX_ZIP_MEMBERS` (500),
`SHEET_MAX_ROWS` (200 000 per sheet), `SHEET_MAX_COLUMNS` (256), `SHEET_MAX_CELLS` (1 000 000 per file),
`SHEET_MAX_CSV_LINE_CHARS` (100 000), and `MAX_UPLOAD_SIZE_MB` for the file itself. Over a limit the file is
refused with a message that names the limit and says what to do; it is never truncated. openpyxl runs with
`read_only=True`, `data_only=True` and `defusedxml` (a file declaring an XML entity or DTD is refused).
