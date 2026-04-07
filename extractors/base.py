"""
extractors/base.py — Abstract interface for PDF text extraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ExtractionResult:
    """Result from a PDF text extractor."""
    raw_text: str = ""
    pages: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)  # list of tables, each is rows of cells
    page_count: int = 0
    has_text: bool = False
    method: str = "unknown"
    warnings: list[str] = field(default_factory=list)


class BaseExtractor(ABC):
    """Abstract base class for PDF extractors."""

    @abstractmethod
    def extract(self, file_path: str) -> ExtractionResult:
        """Extract text and structural data from a PDF file."""
        ...
