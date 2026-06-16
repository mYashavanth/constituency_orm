import fitz
import numpy as np
import re
from typing import List, Dict, Tuple, Any, Optional
from extractor.logger import logger
from extractor.voter_parser import parse_card_text
from extractor.validators import validate_voter_record, is_record_creatable
from extractor.section_parser import parse_page_header_section

def is_valid_card(cell_lines: List[str]) -> bool:
    """
    Evaluates if a card cell contains a valid voter card rather than blank/photo noise or template elements.
    """
    if len(cell_lines) < 3:
        return False
    has_name = False
    has_epic = False
    has_voter_keyword = False
    for line in cell_lines:
        line_lower = line.lower()
        if "name" in line_lower:
            has_name = True
        if any(k in line_lower for k in ["age", "gender", "sex", "father", "husband", "mother", "wife"]):
            has_voter_keyword = True
        # Match EPIC patterns (alphanumeric, length 8 to 12)
        if re.search(r'\b[A-Z0-9]{8,12}\b', line):
            has_epic = True
            
    return (has_name or has_epic) and has_voter_keyword

def extract_pdf_text_page(
    page: fitz.Page, 
    page_num: int, 
    metadata: Dict[str, str], 
    current_section_no: str, 
    current_village_area: str, 
    expected_sl_no: int
) -> Tuple[Optional[List[Dict[str, Any]]], bool, str, str, int]:
    """
    Attempts to extract voter records directly from searchable PDF text.
    
    Returns: (records, is_voter_page, updated_section_no, updated_village_area, next_expected_sl_no)
    If the page is not searchable (no text blocks), records is None (triggers OCR fallback).
    If the page is searchable but not a voter page, records is [] and is_voter_page is False.
    """
    try:
        text_dict = page.get_text("dict")
    except Exception as e:
        logger.error(f"Failed to get text dict on page {page_num}: {e}")
        return None, False, current_section_no, current_village_area, expected_sl_no

    blocks = text_dict.get("blocks", [])
    
    # Extract lines with their bounding box centers
    lines_with_coords = []
    total_char_count = 0
    for block in blocks:
        # type 0 represents text blocks
        if block.get("type") == 0 and "lines" in block:
            for line in block["lines"]:
                line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if line_text:
                    total_char_count += len(line_text)
                    x0, y0, x1, y1 = line["bbox"]
                    cx = (x0 + x1) / 2.0
                    cy = (y0 + y1) / 2.0
                    lines_with_coords.append((cx, cy, line_text))
                    
    # If the page contains practically no text, it's a scanned page. Fall back to OCR.
    if total_char_count < 100:
        logger.info(f"Page {page_num}: Digital text char count ({total_char_count}) is too low. Flagging for OCR fallback.")
        return None, False, current_section_no, current_village_area, expected_sl_no

    # Detect header and update sections
    rect = page.rect
    w, h = rect.width, rect.height
    
    # Header lines (top 8% of page height)
    header_height_threshold = h * 0.08
    header_lines = [text for cx, cy, text in lines_with_coords if cy < header_height_threshold]
    
    sec_no, sec_name = parse_page_header_section(header_lines)
    if sec_no and sec_name:
        current_section_no = sec_no
        current_village_area = sec_name
        logger.info(f"Page {page_num} (Text): Section updated to '{current_section_no} - {current_village_area}'")

    # Find name coordinates to build rows
    name_ys = []
    for cx, cy, text in lines_with_coords:
        text_lower = text.lower()
        if "name" in text_lower and not any(k in text_lower for k in ["father", "husband", "mother", "wife", "relation"]):
            name_ys.append(cy)
            
    name_ys = sorted(name_ys)
    
    # Group Y coordinates into row clusters (15 pt threshold)
    row_clusters = []
    for y in name_ys:
        added = False
        for cluster in row_clusters:
            if abs(np.mean(cluster) - y) < 15:
                cluster.append(y)
                added = True
                break
        if not added:
            row_clusters.append([y])
            
    row_clusters = sorted(row_clusters, key=lambda c: np.mean(c))
    row_ys = [float(np.mean(c)) for c in row_clusters]
    
    # Reconstruct 10 rows using uniform step size
    steps = []
    for i in range(len(row_ys) - 1):
        steps.append(row_ys[i+1] - row_ys[i])
    median_step = np.median(steps) if steps else 84.0
    if not (75.0 <= median_step <= 95.0):
        median_step = 84.0
        
    if not row_ys:
        # Default starting position for rows
        has_header = any(cy < header_height_threshold for cx, cy, text in lines_with_coords)
        first_y = 100.0 if has_header else 23.0
        row_ys = [first_y + i * median_step for i in range(10)]
    else:
        first_detected_y = row_ys[0]
        start_row_idx = 0
        grid = [None] * 10
        for y in row_ys:
            r_idx = int(round((y - first_detected_y) / median_step)) + start_row_idx
            if 0 <= r_idx < 10:
                grid[r_idx] = y
                
        for r in range(10):
            if grid[r] is None:
                left_neighbor = None
                for l in range(r - 1, -1, -1):
                    if grid[l] is not None:
                        left_neighbor = (l, grid[l])
                        break
                right_neighbor = None
                for rg in range(r + 1, 10):
                    if grid[rg] is not None:
                        right_neighbor = (rg, grid[rg])
                        break
                if left_neighbor:
                    grid[r] = left_neighbor[1] + (r - left_neighbor[0]) * median_step
                elif right_neighbor:
                    grid[r] = right_neighbor[1] - (right_neighbor[0] - r) * median_step
                else:
                    grid[r] = 23.0 + r * median_step
        row_ys = grid

    # Group lines into 10x3 grid
    cards = {}
    for r in range(10):
        for c in range(3):
            cards[(c, r)] = []
            
    col_width = w / 3.0
    
    header_threshold = row_ys[0] - 18
    footer_threshold = row_ys[9] + 68
    
    for cx, cy, text in lines_with_coords:
        col_idx = int(cx / col_width)
        col_idx = max(0, min(2, col_idx))
        
        # Exclude header and footer lines
        if cy < header_threshold or cy > footer_threshold:
            continue
        else:
            row_idx = int(np.argmin([abs(cy - ry) for ry in row_ys]))
            cards[(col_idx, row_idx)].append((cx, cy, text))
            
    # Filter valid card cells
    valid_card_cells = []
    for r in range(10):
        for c in range(3):
            cell_texts = [line[2] for line in sorted(cards[(c, r)], key=lambda l: l[1])]
            if is_valid_card(cell_texts):
                valid_card_cells.append((c, r))
                
    # If the page has digital text but < 3 valid cards, it is a non-voter page (cover, summary, etc.)
    if len(valid_card_cells) < 3:
        logger.info(f"Page {page_num}: Searchable non-voter page detected ({len(valid_card_cells)} valid cells). Skipping.")
        return [], False, current_section_no, current_village_area, expected_sl_no

    # Parse cards
    page_records = []
    for r in range(10):
        for c in range(3):
            if (c, r) not in valid_card_cells:
                continue
                
            cell_lines = sorted(cards[(c, r)], key=lambda l: l[1])
            cell_texts = [line[2] for line in cell_lines]
            
            voter_fields = parse_card_text(cell_texts)
            
            # Combine record with metadata
            full_record = {
                "ac_no": metadata.get("ac_no", ""),
                "ac_name": metadata.get("ac_name", ""),
                "booth_no": metadata.get("booth_no", ""),
                "booth_name": metadata.get("booth_name", ""),
                "booth": metadata.get("booth", ""),
                "section_no": current_section_no,
                "village_area": current_village_area,
                **voter_fields
            }
            
            warnings, sanitized_record = validate_voter_record(full_record, expected_sl_no)
            
            if is_record_creatable(sanitized_record):
                # Update expected_sl_no
                if isinstance(sanitized_record.get("sl_no"), int):
                    expected_sl_no = sanitized_record["sl_no"] + 1
                else:
                    expected_sl_no += 1
                    
                sanitized_record["warnings"] = warnings
                page_records.append(sanitized_record)
                
    logger.info(f"Page {page_num} (Text): Extracted {len(page_records)} voter records.")
    return page_records, True, current_section_no, current_village_area, expected_sl_no
