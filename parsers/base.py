"""
parsers/base.py — Abstract base parser with shared BOL parsing logic.

Common patterns across all BOL types:
- Address blocks (Ship From, Ship To, etc.)
- Reference numbers
- Date extraction
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from extractors.base import ExtractionResult
from schema import BOLDocument, Party, Address
from utils import (
    parse_address_block,
    extract_field_after_label,
    extract_dates,
    normalize_date,
    ADDRESS_PATTERN,
)
import re


class BaseBOLParser(ABC):
    """
    Abstract base for BOL parsers.
    Provides shared parsing utilities; subclasses implement type-specific logic.
    """

    @abstractmethod
    def parse(self, extraction: ExtractionResult) -> BOLDocument:
        """Parse extracted text into a structured BOLDocument."""
        ...

    def _extract_address_block_between(
        self,
        text: str,
        start_label: str,
        end_label: Optional[str] = None,
    ) -> Optional[Address]:
        """
        Extract an address block between two section labels.
        e.g., text between 'Ship From' and 'Ship To'
        """
        # Build pattern to capture text between labels
        start_pattern = re.compile(
            rf'{re.escape(start_label)}(.*?)(?={re.escape(end_label)}|\Z)' if end_label
            else rf'{re.escape(start_label)}(.*?)(?:\n\n|\Z)',
            re.DOTALL | re.IGNORECASE
        )

        match = start_pattern.search(text)
        if match:
            block_text = match.group(1).strip()
            if block_text:
                return parse_address_block(block_text)

        return None

    def _extract_references(self, text: str, label_patterns: dict[str, list[str]]) -> dict[str, str]:
        """
        Extract reference numbers using label-value patterns.

        Args:
            text: Text to search
            label_patterns: Dict of {ref_name: [possible_labels]}
                e.g., {"bol_number": ["BOL NO", "BOL#", "B/L NO"]}
        """
        refs = {}
        for ref_name, labels in label_patterns.items():
            for label in labels:
                value = extract_field_after_label(text, label)
                if value:
                    # Clean up the value (remove trailing labels/noise)
                    value = re.split(r'\s{2,}', value)[0].strip()
                    refs[ref_name] = value
                    break
        return refs
