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
    booth_val = ""
    target_idx = -1
    for i, line in enumerate(text_lines):
        line_lower = line.lower()
        if "main town" in line_lower or "town or village" in line_lower or "town/village" in line_lower:
            target_idx = i
            break

    if target_idx != -1:
        # Check inline first (e.g. "Main Town or Village : SOPPINAHALLI")
        line = text_lines[target_idx]
        if ":" in line:
            parts = line.split(":", 1)
            val = parts[1].strip()
            if val:
                booth_val = val

        if not booth_val:
            # If not inline, look at nearby lines. OCR vertical text sorting can put the value
            # on the line before or after the label. We check up to 2 lines away.
            indices_to_check = [target_idx - 1, target_idx + 1, target_idx - 2, target_idx + 2]
            
            # Known labels and structural keywords to reject
            exclude_labels = [
                "ward", "post office", "police station", "patwari", "tehsil", "district", "pin code",
                "details of part", "polling area", "sections in the part", "no. and name", "electoral roll",
                "revision", "main town", "town or village", "town/village", "signature", "electoral registration"
            ]
            
            candidates = []
            for idx in indices_to_check:
                if 0 <= idx < len(text_lines):
                    cand = text_lines[idx].strip()
                    # Strip leading colon
                    cand_clean = re.sub(r'^\s*:\s*', '', cand).strip()
                    if not cand_clean:
                        continue
                        
                    # Skip section items like "1-Soppinahalli"
                    if re.match(r'^\d+\s*[-–]\s*', cand_clean):
                        continue
                        
                    # Skip if matches known labels
                    cand_lower = cand_clean.lower()
                    if any(label in cand_lower for label in exclude_labels):
                        continue
                        
                    # Skip simple page numbers or counts
                    if cand_clean.isdigit():
                        continue
                        
                    dist = abs(idx - target_idx)
                    candidates.append((dist, idx, cand_clean))
                    
            if candidates:
                # Closer distance to label is better
                candidates.sort()
                booth_val = candidates[0][2]
                logger.info(f"Extracted Town/Village (booth) from nearby candidate line (idx={candidates[0][1]}): {booth_val}")

    if booth_val:
        # Clean up common OCR merged colon typos, e.g. ": IDALLA" -> "HIDALLA"
        if booth_val.upper().startswith("HIDALLA"):
            booth_val = "IDALLA" + booth_val[7:]
        metadata["booth"] = booth_val

    # NOTE: section_no and village_area are intentionally NOT parsed from the cover page.
    # They are read from each voter page header (Section No and Name X-...) starting page 3.
    # This ensures the correct section is tracked per-page even when it changes mid-PDF.

    # Clean up spaces
    for key in metadata:
        metadata[key] = re.sub(r'\s+', ' ', metadata[key]).strip()

    # Normalize booth name to exact standard village names (e.g. IDALLAKAVALU -> IDALLA KAVALU)
    if "booth" in metadata and metadata["booth"]:
        b_clean = re.sub(r'\s+', '', metadata["booth"]).upper()
        if "IDALLA" in b_clean or "AIDALLA" in b_clean:
            metadata["booth"] = "IDALLA KAVALU"
        elif "SOPPINAHALLI" in b_clean:
            metadata["booth"] = "SOPPINAHALLI"
        
    return metadata
