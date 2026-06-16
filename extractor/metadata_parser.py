import re
from pathlib import Path
from typing import List, Dict
from extractor.logger import logger

def parse_page1_metadata(text_lines: List[str], pdf_path: str = "") -> Dict[str, str]:
    """
    Parses Page 1 text lines (cover page) to extract constituency, booth, and town metadata.
    """
    metadata = {
        "ac_no": "",
        "ac_name": "",
        "booth_no": "",
        "booth_name": "",
        "booth": "",
        "section_no": "",
        "village_area": ""
    }
    
    combined_text = " ".join(text_lines)
    logger.info(f"Page 1 combined text size: {len(combined_text)} characters")
    
    # 1. Parse AC Number and AC Name directly from Page 1 text lines
    # Example: "No. Name and Reservation Status of Assembly Constituency : 196 - HASSAN (GEN)"
    # Fallback: "196 - HASSAN (GEN)"
    for line in text_lines:
        line_clean = line.strip()
        
        # Primary check: "Assembly Constituency : 196 - HASSAN (GEN)"
        match = re.search(r'Assembly\s+Constituency\s*:\s*(\d+)\s*-\s*([A-Za-z\s]+)\s*\(', line_clean, re.IGNORECASE)
        if match:
            metadata["ac_no"] = match.group(1).strip()
            metadata["ac_name"] = match.group(2).strip()
            logger.info(f"Extracted AC Details (Primary): No={metadata['ac_no']}, Name={metadata['ac_name']}")
            break
            
        # Fallback check: "196 - HASSAN (GEN)"
        match_fallback = re.search(r'^(\d+)\s*-\s*([A-Za-z\s]+)\s*\((?:GEN|SC|ST)\)$', line_clean, re.IGNORECASE)
        if match_fallback:
            metadata["ac_no"] = match_fallback.group(1).strip()
            metadata["ac_name"] = match_fallback.group(2).strip()
            logger.info(f"Extracted AC Details (Fallback 1): No={metadata['ac_no']}, Name={metadata['ac_name']}")
            break
            
        # Additional Fallback check (simple name only): "HASSAN (GEN)"
        match_name_only = re.match(r'^([A-Z\s]+)\s*\((?:GEN|SC|ST)\)$', line_clean, re.IGNORECASE)
        if match_name_only:
            metadata["ac_name"] = match_name_only.group(1).strip()
            logger.info(f"Extracted AC Name (Name Only): {metadata['ac_name']}")
            
    # 2. Parse AC No from PDF filename as fallback if still empty
    if not metadata["ac_no"] and pdf_path:
        filename = Path(pdf_path).name
        # Match patterns like -196- or -S10-196-
        filename_match = re.search(r'-S\d+-(\d+)-', filename) or re.search(r'-(\d+)-', filename)
        if filename_match:
            metadata["ac_no"] = filename_match.group(1).strip()
            logger.info(f"Extracted AC No from filename fallback: {metadata['ac_no']}")
            
    # 3. Parse Polling Station / Booth details (e.g., "5 - Govt Higher Primary School, Idalla Kaval")
    for line in text_lines:
        line_clean = line.strip()
        # Look for pattern: No - Name
        match = re.match(r'^(\d+)\s*-\s*(.+)$', line_clean)
        if match:
            b_no = match.group(1).strip()
            b_name = match.group(2).strip()
            # Verify if it looks like a polling station name
            if any(k in b_name.lower() for k in ["school", "primary", "govt", "community", "panchayat", "building"]):
                metadata["booth_no"] = b_no
                metadata["booth_name"] = b_name.rstrip(',')
                logger.info(f"Extracted Polling Station: No={metadata['booth_no']}, Name={metadata['booth_name']}")
                break
                
    # 4. Parse Main Town or Village
    # Example: "Main Town or Village : IDALLA KAVALU"
    for i, line in enumerate(text_lines):
        line_lower = line.lower()
        if "main town" in line_lower or "town or village" in line_lower or "town/village" in line_lower:
            if ":" in line:
                val = line.split(":", 1)[1].strip()
                if val:
                    metadata["booth"] = val
                    logger.info(f"Extracted Town/Village (booth) from same line: {metadata['booth']}")
                    break
            if i + 1 < len(text_lines):
                next_line = text_lines[i+1].strip()
                if next_line.startswith(":"):
                    metadata["booth"] = next_line.lstrip(":").strip()
                else:
                    metadata["booth"] = next_line
                logger.info(f"Extracted Town/Village (booth) from next line: {metadata['booth']}")
                break

    # 5. Parse Section Information (e.g. "1-Aidalla Kavalu,")
    for line in text_lines:
        line_clean = line.strip()
        # Match pattern: 1-Aidalla Kavalu,
        match = re.match(r'^(\d+)\s*-\s*([A-Za-z\s,.-]+)$', line_clean)
        if match:
            s_no = match.group(1).strip()
            s_name = match.group(2).strip().rstrip(',')
            # Exclude lines that match booth name or AC name
            if not any(k in s_name.lower() for k in ["school", "primary", "govt"]):
                metadata["section_no"] = s_no
                metadata["village_area"] = s_name
                logger.info(f"Extracted Section Details: No={metadata['section_no']}, Area={metadata['village_area']}")
                break
                
    # Clean up spaces
    for key in metadata:
        metadata[key] = re.sub(r'\s+', ' ', metadata[key]).strip()
        
    return metadata
