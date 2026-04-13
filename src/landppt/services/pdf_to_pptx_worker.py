"""
Worker entrypoint to run PDF->PPTX conversion in a separate process.
"""

import argparse
import logging
import sys
from pathlib import Path

from .pdf_to_pptx_converter import PDFToPPTXConverter


def configure_logging(level: int) -> None:
    """Initialise basic logging for the worker."""
    logging.basicConfig(
        level=level,
        format="%(levelname)s:%(name)s:%(message)s"
    )


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Convert PDF to PPTX using Apryse SDK."
    )
    parser.add_argument("--input", required=True, help="Path to the source PDF file.")
    parser.add_argument("--output", help="Path for the output PPTX file.")
    parser.add_argument(
        "--license-key",
        help="Apryse license key to use for conversion."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (default: INFO)."
    )
    args = parser.parse_args()

    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    configure_logging(log_level)

    pdf_path = Path(args.input).expanduser().resolve()
    if not pdf_path.exists():
        print(f"Input PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    if args.output:
        output_path = Path(args.output).expanduser()
        if not output_path.is_absolute():
            output_path = output_path.resolve()
    else:
        output_path = pdf_path.with_suffix(".pptx")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    converter = PDFToPPTXConverter()
    
    # If license key is provided, use it directly (bypasses database lookup)
    if args.license_key:
        converter._cached_license_key = args.license_key
        logging.info("Using license key from command line argument")
    
    success, result = converter.convert_pdf_to_pptx(str(pdf_path), str(output_path))
    if success:
        print(result)
        return 0

    print(result, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
