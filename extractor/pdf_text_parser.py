import fitz
import numpy as np
import re
import io
from PIL import Image
from typing import List, Dict, Tuple, Any, Optional
from extractor.logger import logger
from extractor.voter_parser import parse_card_text, DELETED_RE
from extractor.validators import validate_voter_record, is_record_creatable
from extractor.section_parser import parse_page_header_section
from extractor.ocr_fallback import run_ocr_on_image, check_card_deleted, pil_to_cv2

def detect_page_deleted_stamps(page: fitz.Page) -> List[fitz.Rect]:
    """
    Renders the entire page, runs OCR, and returns a list of bounding boxes
    where the word "DELETED" (or common OCR typos of it) was found.
    Coordinates are scaled back to standard PDF points (72 DPI).
    """
    deleted_rects = []
    try:
        # Render page at 150 DPI
        zoom = 150.0 / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_data = pix.tobytes("png")
        
        img = Image.open(io.BytesIO(img_data))
        ocr_res = run_ocr_on_image(img)
        
        rec_texts = ocr_res.get('rec_texts', [])
        dt_polys = ocr_res.get('dt_polys', [])
        
        for i, text in enumerate(rec_texts):
            if DELETED_RE.search(text):
                poly = dt_polys[i]
                xs = [pt[0] for pt in poly]
                ys = [pt[1] for pt in poly]
                # Scale back to standard 72 DPI
                x0 = min(xs) / zoom
                y0 = min(ys) / zoom
                x1 = max(xs) / zoom
                y1 = max(ys) / zoom
                deleted_rects.append(fitz.Rect(x0, y0, x1, y1))
    except Exception as e:
        logger.warning(f"Failed to detect deleted stamps on page: {e}")
    return deleted_rects

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
    
    # Header lines (top 10% of page height)
    header_height_threshold = h * 0.10
    header_lines = [text for cx, cy, text in lines_with_coords if cy < header_height_threshold]
    
    sec_no, sec_name = parse_page_header_section(header_lines)
    if sec_no and sec_name:
        current_section_no = sec_no
        current_village_area = sec_name
        logger.info(f"Page {page_num} (Text): Section updated to '{current_section_no} - {current_village_area}'")

    # Find name coordinates to build rows
    name_ys = []
    name_exclude_keywords = [
        "father", "fath", "fater", "tather", "ather",
        "husband", "husb", "husoand", "nusoand", "hushand", "husban", "usband", "isband", "tusband",
        "mother", "moth", "moter", "nother",
        "wife", "wfe", "wiife",
        "other", "othr", "relation",
        "assembly", "constituency", "part", "section"
    ]
    for cx, cy, text in lines_with_coords:
        text_lower = text.lower()
        has_name_prefix = any(n in text_lower for n in ["name", "nane", "nmae", "neme", "nama", "vame", "wame", "mane"])
        is_relation = (
            any(k in text_lower for k in name_exclude_keywords) or 
            re.search(r'\b(?:gurus?|guardian|gurdian)\b', text_lower)
        )
        if has_name_prefix and not is_relation:
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
                
    # If the page has digital text but < 1 valid cards, it is a non-voter page (cover, summary, etc.)
    if len(valid_card_cells) < 1:
        logger.info(f"Page {page_num}: Searchable non-voter page detected ({len(valid_card_cells)} valid cells). Skipping.")
        return [], False, current_section_no, current_village_area, expected_sl_no

    # Render page at 150 DPI for visual deleted stamp check
    zoom = 150.0 / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img_data = pix.tobytes("png")
    page_pil = Image.open(io.BytesIO(img_data))
    page_cv = pil_to_cv2(page_pil)

    # Parse cards
    page_records = []
    for r in range(10):
        for c in range(3):
            if (c, r) not in valid_card_cells:
                continue
                
            cell_lines = sorted(cards[(c, r)], key=lambda l: l[1])
            cell_texts = [line[2] for line in cell_lines]
            
            voter_fields = parse_card_text(cell_texts)
            
            # Pre-validate to check if card has any issues or warning signs
            temp_record = {
                "ac_no": metadata.get("ac_no", ""),
                "ac_name": metadata.get("ac_name", ""),
                "booth_no": metadata.get("booth_no", ""),
                "booth_name": metadata.get("booth_name", ""),
                "booth": metadata.get("booth", ""),
                "section_no": current_section_no,
                "village_area": current_village_area,
                **voter_fields
            }
            temp_warnings, _ = validate_voter_record(temp_record, expected_sl_no)

            # Check for graphical "DELETED" stamp overlay on searchable PDF page
            is_deleted = voter_fields.get("is_deleted", False)
            if not is_deleted:
                # Only perform multi-rotation stamp check if the card has warnings or low line count
                if len(temp_warnings) > 0 or len(cell_texts) < 7:
                    # Crop a more generous region vertically to ensure diagonal "DELETED" stamps are not cut off
                    x_start = int(c * col_width * zoom)
                    x_end = int((c + 1) * col_width * zoom)
                    y_start_stamp = int((row_ys[r] - 55) * zoom)
                    y_end_stamp = int((row_ys[r] + 95) * zoom)
                    
                    stamp_card_img = page_cv[max(0, y_start_stamp):min(page_cv.shape[0], y_end_stamp), max(0, x_start):min(page_cv.shape[1], x_end)]
                    is_deleted = check_card_deleted(stamp_card_img)
            voter_fields["is_deleted"] = is_deleted
            
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
