"""
extractors/pdfplumber_extractor.py — Primary PDF text extractor using pdfplumber.

Why pdfplumber:
- Preserves spatial layout (critical for form-like documents)
- Built-in table detection and extraction
- Handles both text-based and partially-text PDFs
- Much more reliable than PyPDF2 (which failed on our sample docs)

Enhanced with:
- Zone-based coordinate extraction for layout-aware parsing
- Optimized table_settings for logistics grids (bordered + unbordered)
- Word-level bounding boxes for precise field mapping
"""

import pdfplumber
from extractors.base import BaseExtractor, ExtractionResult


# Minimum characters to consider a page as having meaningful text
TEXT_THRESHOLD = 50

# Optimized table detection settings for logistics documents
# These handle both heavy-bordered (FedEx Freight) and light-bordered (Ocean BOL) grids
LOGISTICS_TABLE_SETTINGS = {
    "vertical_strategy": "lines_strict",
    "horizontal_strategy": "lines_strict",
    "snap_tolerance": 5,
    "join_tolerance": 5,
    "edge_min_length": 10,
    "min_words_vertical": 2,
    "min_words_horizontal": 2,
}

# Fallback: more permissive settings for tables without visible borders
FALLBACK_TABLE_SETTINGS = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 8,
    "join_tolerance": 8,
}


class PdfPlumberExtractor(BaseExtractor):
    """Extract text and tables from PDFs using pdfplumber."""

    def extract(self, file_path: str) -> ExtractionResult:
        """
        Extract text from each page + detect/extract tables.
        Returns ExtractionResult with raw text, per-page text, tables,
        word positions, and page dimensions for zone-based parsing.
        """
        result = ExtractionResult(method="pdfplumber")

        try:
            with pdfplumber.open(file_path) as pdf:
                result.page_count = len(pdf.pages)
                all_text_parts = []

                for i, page in enumerate(pdf.pages):
                    # Store page dimensions for zone calculations
                    result.page_dimensions.append((page.width, page.height))

                    # Extract full page text
                    page_text = page.extract_text() or ""
                    result.pages.append(page_text)
                    all_text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

                    # ── Word-Level Bounding Boxes ──
                    # Each word dict has: text, x0, top, x1, bottom, fontname, size
                    try:
                        words = page.extract_words(
                            x_tolerance=3,
                            y_tolerance=3,
                            keep_blank_chars=False,
                            extra_attrs=["fontname", "size"],
                        )
                        result.word_positions.append(words)
                    except Exception:
                        result.word_positions.append([])

                    # ── Table Extraction (Two-Pass Strategy) ──
                    tables = []
                    # Pass 1: Strict line-based detection (bordered tables)
                    try:
                        strict_tables = page.extract_tables(table_settings=LOGISTICS_TABLE_SETTINGS)
                        if strict_tables:
                            tables.extend(strict_tables)
                    except Exception:
                        pass

                    # Pass 2: If no tables found, try permissive text-based detection
                    if not tables:
                        try:
                            text_tables = page.extract_tables(table_settings=FALLBACK_TABLE_SETTINGS)
                            if text_tables:
                                tables.extend(text_tables)
                        except Exception:
                            pass

                    # Pass 3: Ultimate fallback — default settings
                    if not tables:
                        try:
                            default_tables = page.extract_tables()
                            if default_tables:
                                tables.extend(default_tables)
                        except Exception:
                            pass

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

    # ── Zone-Based Extraction Helpers ──

    @staticmethod
    def extract_text_from_zone(
        word_positions: list[dict],
        page_width: float,
        page_height: float,
        x_range: tuple[float, float] = (0.0, 1.0),
        y_range: tuple[float, float] = (0.0, 1.0),
    ) -> str:
        """
        Extract text from a rectangular zone defined as fractions of page dimensions.

        Args:
            word_positions: Word dicts from pdfplumber (with x0, top, x1, bottom).
            page_width: Width of the page in points.
            page_height: Height of the page in points.
            x_range: (left_fraction, right_fraction) of page width, e.g. (0.0, 0.5) = left half.
            y_range: (top_fraction, bottom_fraction) of page height, e.g. (0.0, 0.3) = top 30%.

        Returns:
            Extracted text from the zone, reconstructed line-by-line.
        """
        x_min = page_width * x_range[0]
        x_max = page_width * x_range[1]
        y_min = page_height * y_range[0]
        y_max = page_height * y_range[1]

        # Filter words that fall within the zone
        zone_words = [
            w for w in word_positions
            if w['x0'] >= x_min and w['x1'] <= x_max
            and w['top'] >= y_min and w['bottom'] <= y_max
        ]

        if not zone_words:
            return ""

        # Sort by vertical position (top), then horizontal (x0)
        zone_words.sort(key=lambda w: (w['top'], w['x0']))

        # Reconstruct lines: group words within ~5pt vertical tolerance
        lines = []
        current_line = [zone_words[0]]
        for word in zone_words[1:]:
            if abs(word['top'] - current_line[-1]['top']) < 5:
                current_line.append(word)
            else:
                line_text = " ".join(w['text'] for w in sorted(current_line, key=lambda w: w['x0']))
                lines.append(line_text)
                current_line = [word]
        # Don't forget the last line
        if current_line:
            line_text = " ".join(w['text'] for w in sorted(current_line, key=lambda w: w['x0']))
            lines.append(line_text)

        return "\n".join(lines)
