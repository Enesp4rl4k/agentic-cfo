#!/usr/bin/env python3
"""Generate synthetic stress corpus files simulating real-world messy Turkish SME data.

Outputs CSV files with customizable delimiters, UTF-8 BOM, and Turkish edge cases.
Usage:
    python scripts/generate_stress_corpus.py [--out-dir DIR] [--delimiter DELIM] [--no-bom]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend directory to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from tests.fixtures.stress_corpus import generate_stress_corpus


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate messy Turkish SME stress test corpus.")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "backend" / "tests" / "fixtures" / "tr_corpus")
    parser.add_argument("--delimiter", default=";", help="CSV delimiter (e.g. ';' or ',')")
    parser.add_argument("--no-bom", action="store_true", help="Do not include UTF-8 BOM")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic generator seed")
    args = parser.parse_args()

    bundle = generate_stress_corpus(seed=args.seed)
    csv_bytes = bundle.to_csv(
        delimiter=args.delimiter,
        include_bom=not args.no_bom,
        date_format="%d.%m.%Y",
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_file = args.out_dir / f"kobi_stress_seed_{args.seed}.csv"
    out_file.write_bytes(csv_bytes)

    print(f"Generated stress corpus: {out_file} ({len(csv_bytes):,} bytes)")
    print(f"  Invoices: {len(bundle.invoices)}")
    print(f"  Bank lines: {len(bundle.bank_lines)}")
    print(f"  Expected confirmed matches: {bundle.expectations.expected_confirmed_matches}")
    print(f"  Expected proposed matches: {bundle.expectations.expected_proposed_matches}")
    print(f"  Expected unmatched bank lines: {bundle.expectations.expected_unmatched_bank_lines}")


if __name__ == "__main__":
    main()
