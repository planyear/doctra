#!/usr/bin/env python3
"""
Doctra parser worker — executed as a subprocess with an isolated working directory.

Each request spawns this script in its own temp directory, so the relative
`outputs/{filename}/` paths written by the parsers never collide across
concurrent requests.

Usage:
    python worker.py --file <filename_in_cwd> --type <pdf|docx>
"""
import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Doctra parser worker")
    parser.add_argument("--file", required=True, help="Input filename relative to cwd")
    parser.add_argument("--type", choices=["pdf", "docx"], required=True, help="Document type")
    args = parser.parse_args()

    if args.type == "pdf":
        from doctra.parsers.structured_pdf_parser import StructuredPDFParser
        StructuredPDFParser().parse(args.file)
    elif args.type == "docx":
        from doctra.parsers.structured_docx_parser import StructuredDOCXParser
        StructuredDOCXParser().parse(args.file)


if __name__ == "__main__":
    main()
