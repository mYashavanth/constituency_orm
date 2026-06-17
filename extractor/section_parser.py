import re
from typing import List, Tuple
from extractor.logger import logger

def parse_page_header_section(header_lines: List[str]) -> Tuple[str, str]:
    """
    Parses voter page header text to extract current page section_no and village_area.

    The header typically has one of these forms:
      "Section No and Name 1-Soppinahalli"
      "Section No and Name 2-Nagenahalli (A)"
      "Section No and Name : 1 - Soppinahalli"

    Returns (section_no, section_name) or ("", "") if not found.
    """
    combined_header = " ".join(header_lines)

    # Ordered from most specific to least specific
    patterns = [
        # "Section No and Name : 1 - Soppinahalli" (with colon)
        r"Section\s+No\.?\s*(?:and|&)?\s*Name\s*:\s*(\d+)\s*[-–]\s*([A-Za-z0-9\s,.()\-]+)",
        # "Section No and Name 1-Soppinahalli" (no colon, dash-separated)
        r"Section\s+No\.?\s*(?:and|&)?\s*Name\s+(\d+)\s*[-–]\s*([A-Za-z0-9\s,.()\-]+)",
        # "Section No and Name 1 Soppinahalli" (space-separated fallback)
        r"Section\s+No\.?\s*(?:and|&)?\s*Name\s+(\d+)\s+([A-Za-z][A-Za-z0-9\s,.()\-]{2,})",
        # Generic: standalone "1-Soppinahalli" at start of a line (only use if Section keyword present nearby)
        r"(\d+)\s*[-–]\s*([A-Za-z][A-Za-z0-9\s,.()\-]{3,})",
    ]

    # Only allow the generic fallback if "Section" appears somewhere in the header
    has_section_keyword = bool(re.search(r'\bsection\b', combined_header, re.IGNORECASE))

    for idx, pattern in enumerate(patterns):
        # Skip generic fallback if no section keyword found
        if idx == len(patterns) - 1 and not has_section_keyword:
            continue

        match = re.search(pattern, combined_header, re.IGNORECASE)
        if match:
            sec_no = match.group(1).strip()
            sec_name = match.group(2).strip()

            # Clean up trailing OCR noise: stop at any EPIC-like token, page markers,
            # or standalone numbers that leaked from the first voter card.
            # Strategy: strip trailing ", NNN" or " NNN" patterns (serial numbers)
            # and field label keywords.
            sec_name = re.split(
                r'(?:'
                r'\s*,\s*\d+\b'              # ", 421" — serial after comma
                r'|\s+\d{2,}\b'              # " 421" — serial after space (2+ digits)
                r'|\s*Page\b|\s*Part\s*No\b|\s*Date\b|\s*Electoral\b'
                r'|\s*EPIC\b|\s*[A-Z]{3}\d'  # EPIC token
                r'|\s+Name\b|\s+Father|\s+Husband|\s+Mother|\s+Wife'  # card labels
                r'|\s+House\b|\s+Age\b|\s+Gender\b|\s+Sex\b'
                r')',
                sec_name,
                flags=re.IGNORECASE
            )[0].strip()

            # Strip trailing punctuation and whitespace
            sec_name = re.sub(r'[\s,.\-]+$', '', sec_name).strip()

            # Sanity check: sec_no must be a small integer, sec_name must be meaningful
            if sec_no.isdigit() and len(sec_name) >= 3:
                logger.debug(f"parse_page_header_section: matched '{sec_no} - {sec_name}'")
                return sec_no, sec_name

    return "", ""
