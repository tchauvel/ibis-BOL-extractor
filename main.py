"""
main.py — CLI entry point.

Usage:
    python main.py <pdf_file>
    python main.py <pdf_file> --output result.json
    python main.py <pdf_file> --pretty
    python main.py samples/DEN5755177.pdf
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from process_document import process_document


def main():
    parser = argparse.ArgumentParser(
        description="IBIS PDF Extractor — Convert PDFs to structured JSON",
        epilog="Example: python main.py samples/DEN5755177.pdf",
    )
    parser.add_argument(
        "file",
        help="Path to the PDF file to process",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write JSON output to file (default: stdout)",
        default=None,
    )
    parser.add_argument(
        "--pretty", "-p",
        help="Pretty-print JSON output",
        action="store_true",
        default=True,
    )
    parser.add_argument(
        "--verbose", "-v",
        help="Enable verbose logging",
        action="store_true",
    )

    args = parser.parse_args()

    # Set up logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s | %(name)s | %(message)s",
    )

    # Process the document
    result = process_document(args.file)

    # Format output
    indent = 2 if args.pretty else None
    output = json.dumps(result, indent=indent, ensure_ascii=False)

    # Write output
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding='utf-8')
        print(f"✓ Output written to: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
