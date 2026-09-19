"""Fetch the Revenue Administration's own published document packages.

Every fixture in `backend/tests/fixtures/tr_corpus/` was written by hand, and
each one was written to match the parser it exercises — the bank statement
fixtures are literally shaped around the regexes, so they can only ever confirm
what the regex already believed. Fixtures like that cannot fail.

GİB publishes the real thing: 43 sample documents covering every invoice type
code it issues, and the e-Defter package carrying the actual XBRL GL schemas a
ledger is validated against before it can be filed. Those are the inputs the
product claims to handle, written by the authority that defines them.

The packages are ~8 MB and GİB versions them, so they are downloaded rather
than vendored — a copy in the tree would drift silently from the standard, and
drifting from the standard is the failure mode this corpus exists to catch.

    python scripts/fetch_gib_corpus.py

Tests that need the corpus skip when it is absent, so a plain checkout still
runs green; CI fetches first. Re-running is cheap: existing packages are kept
unless --force is given.
"""
from __future__ import annotations

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

# The Windows console defaults to cp1254 here; the messages are Turkish.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "backend" / "tests" / "fixtures" / "gib_corpus"

# Both URLs are linked from GİB's own mevzuat pages.
PACKAGES = {
    "ubl_tr": (
        "https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/UBL-TR1.2.1_Paketi.zip",
        "e-Fatura / e-Arşiv UBL-TR 1.2.1 — 43 örnek belge",
    ),
    "e_defter": (
        "https://www.edefter.gov.tr/dosyalar/paketler/e-Defter_Paketi.zip",
        "e-Defter paketi — XBRL GL şemaları ve GİB'in kendi yevmiye/kebir/berat örnekleri",
    ),
    "e_arsiv": (
        "https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/earsiv_paket_v1.1_8.zip",
        "e-Arşiv paketi — rapor şemaları (EArsiv.xsd, eArsivVeri.xsd), schematron, WSDL",
    ),
}


def fetch(name: str, url: str, label: str, *, force: bool) -> bool:
    target = DEST / name
    if target.is_dir() and any(target.rglob("*.xsd")) or (
        target.is_dir() and any(target.rglob("*.xml"))
    ):
        if not force:
            print(f"  {name}: mevcut, atlandı ({label})")
            return True
    print(f"  {name}: indiriliyor — {label}")
    try:
        with urllib.request.urlopen(url, timeout=180) as resp:  # noqa: S310
            payload = resp.read()
    except Exception as exc:  # noqa: BLE001
        print(f"  {name}: BAŞARISIZ — {exc}", file=sys.stderr)
        return False

    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        zf.extractall(target)
    count = sum(1 for _ in target.rglob("*") if _.is_file())
    print(f"  {name}: {len(payload) // 1024} KB, {count} dosya -> {target.relative_to(ROOT)}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="var olan paketi yeniden indir")
    args = ap.parse_args()

    print("GİB resmî belge paketleri alınıyor:")
    ok = all(
        fetch(name, url, label, force=args.force)
        for name, (url, label) in PACKAGES.items()
    )
    if not ok:
        print("\nEn az bir paket alınamadı.", file=sys.stderr)
        return 1
    print("\nHazır. Korpusa bağlı testler artık koşar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
