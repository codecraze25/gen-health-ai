"""Measure extraction accuracy on the labelled PDFs in tests/fixtures/eval.

Compares the values the pipeline would SAVE (after validation) with expected.json. Two error kinds
are reported separately because they matter differently:
  wrong  - a value was saved that does not match (the dangerous case: a bad claim)
  missed - nothing was saved where a value was expected (safe: a human fills it in)

Usage: uv run python scripts/eval.py [--model gpt-5.5] [--case name.pdf]
"""

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "tests" / "fixtures" / "eval"
FIELDS = ("patient_first_name", "patient_last_name", "patient_dob", "provider_name", "provider_npi")


def norm(value) -> str | None:
    if value is None:
        return None
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model")
    parser.add_argument("--case", action="append")
    args = parser.parse_args()
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model
    os.environ["NPPES_LOOKUP_ENABLED"] = "false"

    sys.path.insert(0, str(ROOT))
    from app.extraction.llm import OpenAIExtractor
    from app.extraction.service import extract_order

    expected: dict = json.loads((EVAL_DIR / "expected.json").read_text())
    cases = args.case or list(expected)
    extractor = OpenAIExtractor()

    def run(name: str):
        return name, extract_order((EVAL_DIR / name).read_bytes(), extractor)

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = dict(pool.map(run, cases))

    totals = {"correct": 0, "wrong": 0, "missed": 0}
    per_field = {f: 0 for f in FIELDS}
    print(f"Model: {extractor.model}\n")
    for name in cases:
        out = outcomes[name]
        marks = []
        for field in FIELDS:
            want, got = expected[name][field], out.fields[field]
            if norm(want) == norm(got):
                kind = "correct"
                per_field[field] += 1
                marks.append("ok")
            elif got is None:
                kind = "missed"
                marks.append(f"MISSED {field} (want {want!r})")
            else:
                kind = "wrong"
                marks.append(f"WRONG {field}: got {got!r}, want {want!r}")
            totals[kind] += 1
        errors = [m for m in marks if m != "ok"]
        status = "PASS" if not errors else "FAIL"
        ms = out.metadata.get("duration_ms")
        print(f"{status}  {name:28} {ms:>6} ms  issues={len(out.issues)}")
        for e in errors:
            print(f"        {e}")

    n = len(cases)
    total = sum(totals.values())
    print("\nPer-field accuracy:")
    for field in FIELDS:
        print(f"  {field:20} {per_field[field]}/{n}")
    print(
        f"\nOverall: {totals['correct']}/{total} correct "
        f"({100 * totals['correct'] / total:.0f}%), "
        f"{totals['wrong']} wrong saved, {totals['missed']} missed"
    )
    return 0 if totals["wrong"] == 0 and totals["missed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
