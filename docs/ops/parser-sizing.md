# Sizing the file parsers (PDF, spreadsheet, CSV)

Every parser of an uploaded file runs in a **child process** (`app/services/pdf_isolation.py` for PDFs,
`app/services/sheet_isolation.py` for .xlsx and CSV; one mechanism, `pdf_isolation.run_worker`). The child
has an address-space limit (`RLIMIT_AS`, Linux), a CPU limit, a deadline, and its own process group that is
killed whole on timeout. This page says how many of them can exist at once and what that means for memory.

## The bound is per process, not per system

The slots are a semaphore **inside each process**: `PDF_PARSE_CONCURRENCY` children at a time per uvicorn
worker, and per arq worker process. PDF and spreadsheet children share the same slots. The real bound on one
container is therefore

    children at once = PDF_PARSE_CONCURRENCY x processes in the container

In the production compose stack the `backend` container runs `uvicorn --workers 2` (2 processes) and the
`worker` container runs one arq process. Across the stack the worst case is `PDF_PARSE_CONCURRENCY` x
(2 + 1) children. A cross-process bound would need a counting semaphore in Redis; the repo's Redis lock
(`app/core/distributed_lock.py`) is a mutex, not a counter, so none was added: no new infrastructure.

A request that waits for a slot longer than `PARSE_QUEUE_WAIT_SECONDS` (60) is refused with a visible
"Sistem yoğun, tekrar deneyin" message (English underneath), instead of holding a thread forever.

## The sizing rule

For each container that parses files:

    PDF_CHILD_MEMORY_MB (or SHEET_CHILD_MEMORY_MB, the larger)
      x PDF_PARSE_CONCURRENCY
      x PARSE_PROCESS_COUNT
    <=  the container's memory limit (compose `mem_limit`)

`PARSE_PROCESS_COUNT` is the number of API worker processes in that container (`uvicorn --workers`); an arq
worker container has one. It is a setting because the process cannot read the command line it was started with.
Leave room beyond the product: the API process itself (Python, SQLAlchemy, the models loaded) is a few hundred
MB per process, and `RLIMIT_AS` limits *address space*, which is larger than resident memory, so the worst case
above is a ceiling that real PDFs stay well under, not an expectation.

Defaults: `PDF_CHILD_MEMORY_MB=512`, `SHEET_CHILD_MEMORY_MB=512`, `PDF_PARSE_CONCURRENCY=1`,
`PARSE_PROCESS_COUNT=2`. In the 1280 MB `backend` container that is 512 x 1 x 2 = 1024 MB at the very worst,
below the limit. The earlier default of 3072 MB per child was above the container limit, so the kernel's OOM
killer, which may kill the API process itself, was the real limit.

If a legitimate file is refused as unreadable because a child hit its memory limit, raise `PDF_CHILD_MEMORY_MB`
and the container's `mem_limit` together, or lower the concurrency.

## Preflight

At start-up `app/core/preflight.py` reads the container's cgroup limit (v2 `/sys/fs/cgroup/memory.max`, v1
`/sys/fs/cgroup/memory/memory.limit_in_bytes`; nothing is said where the files are absent or unlimited) and:

* logs a **WARNING** `parser_memory_exceeds_container` when child x concurrency x processes is over the limit;
* is **FATAL** (production only) `parser_memory_impossible` when one child alone is as large as the container:
  its own memory limit could never act before the OOM killer.

## Spreadsheet limits

`SHEET_PARSE_TIMEOUT_SECONDS` (90), `SHEET_MAX_UNCOMPRESSED_MB` (128, the total of an .xlsx's zip members,
checked from the zip directory and counted again while members are read), `SHEET_MAX_ZIP_MEMBERS` (500),
`SHEET_MAX_ROWS` (200 000 per sheet), `SHEET_MAX_COLUMNS` (256), `SHEET_MAX_CELLS` (1 000 000 per file),
`SHEET_MAX_CSV_LINE_CHARS` (100 000), and `MAX_UPLOAD_SIZE_MB` for the file itself. Over a limit the file is
refused with a message that names the limit and says what to do; it is never truncated. openpyxl runs with
`read_only=True`, `data_only=True` and `defusedxml` (a file declaring an XML entity or DTD is refused).
