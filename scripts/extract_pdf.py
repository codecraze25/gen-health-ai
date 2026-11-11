"""Run the extraction pipeline on local PDFs without the API or database.

Usage: uv run python scripts/extract_pdf.py file.pdf [more.pdf ...] [--model gpt-5.4]
"""

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--model")
    args = parser.parse_args()
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app.extraction.llm import OpenAIExtractor
    from app.extraction.service import extract_order

    extractor = OpenAIExtractor()
    for pdf in args.pdfs:
        outcome = extract_order(pdf.read_bytes(), extractor)
        print(f"=== {pdf.name} ({extractor.model}, {outcome.metadata.get('duration_ms')} ms)")
        print(
            json.dumps({"fields": outcome.fields, "issues": outcome.issues}, default=str, indent=2)
        )
        if outcome.metadata.get("document_notes"):
            print("notes:", outcome.metadata["document_notes"])


if __name__ == "__main__":
    main()
