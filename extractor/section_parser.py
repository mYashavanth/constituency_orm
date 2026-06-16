import re
from typing import List, Tuple
from extractor.logger import logger

def parse_page_header_section(header_lines: List[str]) -> Tuple[str, str]:
    """
    Parses voter page header text to extract current page section_no and village_area.
    Example header lines:
      "Section No and Name"
      "1 - Aidalla Kavalu"
    """
    combined_header = " ".join(header_lines)
    
    # Pattern for "1 - Aidalla Kavalu" or "Section No and Name 1 - Aidalla Kavalu"
    patterns = [
        r"Section\s+No\.?\s*(?:and|&)?\s*Name\s*:\s*(\d+)\s*-\s*([A-Za-z0-9\s,.-]+)",
        r"Section\s+No\.?\s*(?:and|&)?\s*Name\s+(\d+)\s*-\s*([A-Za-z0-9\s,.-]+)",
        r"(\d+)\s*-\s*([A-Za-z0-9\s,.-]{3,})"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, combined_header, re.IGNORECASE)
        if match:
            sec_no = match.group(1).strip()
            sec_name = match.group(2).strip()
            
            # Clean up trailing OCR noise, headers, and card leakage (EPIC numbers, Name, etc.)
            sec_name = re.split(
                r'\s*(?:Page|Part|No|Date|Electoral|Name|EPIC|Husband|Father|Mother|Wife|House|\d+\s+[A-Z]{3}|\b[A-Z]{3}\d|\b[A-Z]{3}[A-Z]|$)', 
                sec_name, 
                flags=re.IGNORECASE
            )[0].strip()
            
            # Strip trailing punctuation
            sec_name = re.sub(r'[\s,.-]+$', '', sec_name).strip()
            return sec_no, sec_name
            
    return "", ""
