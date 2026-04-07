"""
extractors/pdfplumber_extractor.py — Primary PDF text extractor using pdfplumber.

Why pdfplumber:
- Preserves spatial layout (critical for form-like documents)
- Built-in table detection and extraction
- Handles both text-based and partially-text PDFs
- Much more reliable than PyPDF2 (which failed on our sample docs)
"""

import pdfplumber
from extractors.base import BaseExtractor, ExtractionResult


# Minimum characters to consider a page as having meaningful text
TEXT_THRESHOLD = 50


class PdfPlumberExtractor(BaseExtractor):
    """Extract text and tables from PDFs using pdfplumber."""

    def extract(self, file_path: str) -> ExtractionResult:
        """
        Extract text from each page + detect/extract tables.
        Returns ExtractionResult with raw text, per-page text, and tables.
        """
        result = ExtractionResult(method="pdfplumber")

        try:
            with pdfplumber.open(file_path) as pdf:
                result.page_count = len(pdf.pages)
                all_text_parts = []

                for i, page in enumerate(pdf.pages):
                    # Extract full page text
                    page_text = page.extract_text() or ""
                    result.pages.append(page_text)
                    all_text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

                    # Extract tables from this page
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            # Clean table cells: replace None with empty string
                            cleaned = [
                                [str(cell).strip() if cell else "" for cell in row]
                                for row in table
                            ]
                            result.tables.append(cleaned)

                result.raw_text = "\n\n".join(all_text_parts)

                # Determine if we got meaningful text
                total_chars = sum(len(p.strip()) for p in result.pages)
                result.has_text = total_chars >= TEXT_THRESHOLD

                if not result.has_text:
                    result.warnings.append(
                        f"Low text content ({total_chars} chars across {result.page_count} pages). "
                        "PDF may be image-based — consider vision LLM fallback."
                    )

        except Exception as e:
            result.warnings.append(f"pdfplumber extraction failed: {str(e)}")
            result.has_text = False

        return result
