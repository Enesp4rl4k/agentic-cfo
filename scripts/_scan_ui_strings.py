"""Scratch helper: list hardcoded UI-copy-looking lines per page (i18n migration aid)."""
import re
import sys
from pathlib import Path

TR = re.compile(u"[\u00e7\u00c7\u011f\u011e\u0131\u0130\u00f6\u00d6\u015f\u015e\u00fc\u00dc]")
# quoted string containing a space, or bare JSX text
PAT = re.compile(r"[\"'`][^\"'`\n]* [^\"'`\n]*[\"'`]|>[^<>{}\n]{3,}<")

# Page slugs come from sys.argv and are pasted into a filesystem path: whitelist
# the slug shape and re-check containment so a crafted "../../etc" can never walk
# out of the pages tree (Sonar S8707, path traversal via CLI arguments).
SLUG = re.compile(r"[a-z0-9][a-z0-9-]*")
PAGES_ROOT = Path("frontend/src/app/(dashboard)").resolve()

for page in sys.argv[1:]:
    if not SLUG.fullmatch(page):
        sys.exit(f"invalid page slug: {page!r}")
    target = (PAGES_ROOT / page / "page.tsx").resolve()
    if not target.is_relative_to(PAGES_ROOT):
        sys.exit(f"path escapes the pages root: {page!r}")
    lines = target.read_text(encoding="utf-8").splitlines()
    print(f"##### {page} ({len(lines)} lines) #####")
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        if PAT.search(line):
            mark = "TR" if TR.search(line) else "  "
            print(f"{mark}{i:4}: {s[:160]}")
    print()
