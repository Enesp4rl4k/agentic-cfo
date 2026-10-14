"""Scratch helper: list hardcoded UI-copy-looking lines per page (i18n migration aid)."""
import re
import sys

TR = re.compile(u"[\u00e7\u00c7\u011f\u011e\u0131\u0130\u00f6\u00d6\u015f\u015e\u00fc\u00dc]")
# quoted string containing a space, or bare JSX text
PAT = re.compile(r"[\"'`][^\"'`\n]* [^\"'`\n]*[\"'`]|>[^<>{}\n]{3,}<")

for page in sys.argv[1:]:
    path = f"frontend/src/app/(dashboard)/{page}/page.tsx"
    lines = open(path, encoding="utf-8").read().splitlines()
    print(f"##### {page} ({len(lines)} lines) #####")
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        if PAT.search(line):
            mark = "TR" if TR.search(line) else "  "
            print(f"{mark}{i:4}: {s[:160]}")
    print()
