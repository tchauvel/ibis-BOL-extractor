"""
utils.py — Shared regex patterns and parsing utilities.

Centralizes all pattern matching so parsers stay clean and focused on structure.
"""

from __future__ import annotations

import re
from typing import Optional

from schema import Address


# ─── Regex Patterns ───────────────────────────────────────────────────────────

# US address: City, STATE ZIP
ADDRESS_PATTERN = re.compile(
    r'(?P<city>[A-Za-z\s]+?),?\s+'
    r'(?P<state>[A-Z]{2})\s+'
    r'(?P<zip>\d{5}(?:-\d{4})?)',
    re.IGNORECASE
)

# Date patterns: MM/DD/YYYY, MM-DD-YYYY, YYYY-MM-DD
DATE_PATTERNS = [
    re.compile(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b'),
    re.compile(r'\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b'),
]

# Phone: (XXX) XXX-XXXX or XXX-XXX-XXXX
PHONE_PATTERN = re.compile(r'[\(]?\d{3}[\)]?[-.\s]?\d{3}[-.\s]?\d{4}')

# Reference numbers: alphanumeric sequences of 5+ characters
REF_NUMBER_PATTERN = re.compile(r'\b[A-Z0-9]{5,}\b')

# Weight: number followed by lbs/kg
WEIGHT_PATTERN = re.compile(r'(\d[\d,]*\.?\d*)\s*(lbs?|kg|pounds?|kilograms?)', re.IGNORECASE)

# ZIP code standalone
ZIP_PATTERN = re.compile(r'\b\d{5}(?:-\d{4})?\b')

# US State abbreviations
US_STATES = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC',
}


# ─── Parsing Functions ────────────────────────────────────────────────────────

def parse_address_block(text: str) -> Address:
    """
    Parse a free-text address block into a structured Address.
    Handles multi-line addresses with various formatting.
    """
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    addr = Address()

    if not lines:
        return addr

    # First line is typically the name/company
    addr.name = lines[0]

    # Look for city/state/zip pattern in all lines
    for i, line in enumerate(lines):
        match = ADDRESS_PATTERN.search(line)
        if match:
            addr.city = match.group('city').strip()
            addr.state = match.group('state').upper()
            addr.zip_code = match.group('zip')
            # Address lines are between name and city/state/zip
            addr_lines = [l for l in lines[1:i] if l]
            if addr_lines:
                addr.address_line_1 = addr_lines[0]
                if len(addr_lines) > 1:
                    addr.address_line_2 = addr_lines[1]
            break

    # If no structured match, try to salvage what we can
    if not addr.city and len(lines) > 1:
        addr.address_line_1 = lines[1] if len(lines) > 1 else None

    # Extract phone if present
    phone_match = PHONE_PATTERN.search(text)
    if phone_match:
        addr.phone = phone_match.group()

    return addr


def extract_dates(text: str) -> list[str]:
    """Extract all date-like strings from text."""
    dates = []
    for pattern in DATE_PATTERNS:
        dates.extend(pattern.findall(text))
    return dates


def normalize_date(date_str: str) -> Optional[str]:
    """Try to normalize a date string to YYYY-MM-DD format."""
    from dateutil import parser as date_parser
    try:
        parsed = date_parser.parse(date_str, dayfirst=False)
        return parsed.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return date_str


def extract_weight(text: str) -> Optional[tuple[float, str]]:
    """Extract weight value and unit from text."""
    match = WEIGHT_PATTERN.search(text)
    if match:
        value = float(match.group(1).replace(',', ''))
        unit = 'lbs' if 'lb' in match.group(2).lower() or 'pound' in match.group(2).lower() else 'kg'
        return (value, unit)
    return None


def clean_text(text: str) -> str:
    """Remove excessive whitespace and normalize line endings."""
    text = re.sub(r'\r\n', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def extract_field_after_label(text: str, label: str, multiline: bool = False) -> Optional[str]:
    """
    Extract value after a label like 'BOL NO:' or 'Carrier:'.
    Handles both 'Label: Value' and 'Label\\nValue' patterns.
    Stops at the next label-like pattern to avoid value bleed.
    """
    # Pattern: Label followed by colon/space then value, stopping at next label or EOL
    patterns = [
        re.compile(rf'{re.escape(label)}\s*[:]\s*(.+?)(?:\s{{2,}}[A-Z][a-z]+[\s:]|\n|$)', re.IGNORECASE),
        re.compile(rf'{re.escape(label)}\s*[:]\s*(.+?)(?:\n|$)', re.IGNORECASE),
        re.compile(rf'{re.escape(label)}\s+(.+?)(?:\s{{2,}}[A-Z]|\n|$)', re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            value = match.group(1).strip()
            # Clean trailing punctuation or partial labels
            value = re.sub(r'\s+$', '', value)
            if value and len(value) > 0:
                return value

    return None


def safe_int(value: str) -> Optional[int]:
    """Safely parse an integer from a string."""
    try:
        return int(value.replace(',', '').strip())
    except (ValueError, TypeError, AttributeError):
        return None


def safe_float(value: str) -> Optional[float]:
    """Safely parse a float from a string."""
    try:
        return float(value.replace(',', '').strip())
    except (ValueError, TypeError, AttributeError):
        return None
