import fitz  # PyMuPDF
import cv2
import io
import re
import numpy as np
from PIL import Image
from typing import List, Dict, Tuple, Any, Optional
# PaddleOCR is imported lazily inside get_ocr_model() to avoid
# conflicting with Tkinter's C extension on macOS at startup.
from extractor.logger import logger
from extractor.voter_parser import parse_card_text
from extractor.validators import validate_voter_record, is_record_creatable
from extractor.section_parser import parse_page_header_section

# Singleton OCR model
_ocr_model = None

def get_ocr_model():
    """
    Returns the singleton PaddleOCR instance. Lazily imported to avoid
    blocking Tkinter startup on macOS.
    """
    global _ocr_model
    if _ocr_model is None:
        from paddleocr import PaddleOCR  # lazy import
        logger.info("Initializing PaddleOCR model...")
        _ocr_model = PaddleOCR(use_textline_orientation=False, lang="en", cpu_threads=1, show_log=False)
        logger.info("PaddleOCR model loaded successfully (cpu_threads=1).")
    return _ocr_model

def ensure_3_channels(img: np.ndarray) -> np.ndarray:
    """
    Ensures that the input image has 3 channels (BGR) for PaddleOCR compatibility.
    """
    if img is None:
        return img
    if len(img.shape) == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img

def pil_to_cv2(pil_img: Image.Image) -> np.ndarray:
    """
    Converts a PIL Image to a BGR OpenCV NumPy array.
    """
    open_cv_image = np.array(pil_img)
    # Convert RGB to BGR
    if len(open_cv_image.shape) == 3 and open_cv_image.shape[2] == 3:
        return cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
    return open_cv_image

def convert_pdf_page_to_image(pdf_path: str, page_idx: int, dpi: int = 150) -> Image.Image:
    """
    Converts a single PDF page (0-indexed) to a PIL Image.
    Default DPI is 150 — a good balance between OCR accuracy and speed.
    (At 100 DPI card characters are ~5-7px tall; at 150 DPI they're ~10-12px — much cleaner.)
    """
    try:
        with fitz.open(pdf_path) as doc:
            page = doc.load_page(page_idx)
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            return img
    except Exception as e:
        logger.error(f"Error converting PDF page {page_idx + 1} to image: {e}")
        raise

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

def extract_quadrant_crop(card_img: np.ndarray, quad: str) -> np.ndarray:
    """
    Crops specific quadrants of the voter card to run targeted OCR:
    - 'top_left': Target Serial Number
    - 'top_right': Target EPIC Number
    """
    h, w = card_img.shape[:2]
    if quad == "top_left":
        return card_img[0:int(h*0.32), 0:int(w*0.40)]
    elif quad == "top_right":
        return card_img[0:int(h*0.32), int(w*0.40):w]
    return card_img

def extract_sorted_lines_from_ocr_res(ocr_res: Any) -> List[str]:
    """
    Extracts text lines from an OCRResult object, sorted from top to bottom.
    """
    if not ocr_res:
        return []
        
    texts = ocr_res.get('rec_texts', [])
    if not texts:
        return []
        
    boxes = ocr_res.get('rec_boxes', [None] * len(texts))
    paired = []
    for i, text in enumerate(texts):
        box = boxes[i] if i < len(boxes) else None
        if box is not None and len(box) > 0:
            try:
                y = float(box[0][1])
                x = float(box[0][0])
            except Exception:
                y = 0.0
                x = 0.0
        else:
            y = 0.0
            x = 0.0
        paired.append((y, x, text.strip()))
        
    sorted_paired = sorted(paired, key=lambda p: (p[0], p[1]))
    return [p[2] for p in sorted_paired]

def run_quadrant_fallback_ocr(card_img: np.ndarray, quad: str) -> List[str]:
    """
    Runs PaddleOCR on a specific crop quadrant of the card.
    """
    crop = extract_quadrant_crop(card_img, quad)
    ocr = get_ocr_model()
    # Ensure 3 channels
    crop_bgr = ensure_3_channels(crop)
    res = ocr.ocr(crop_bgr)
    if res and len(res) > 0:
        return extract_sorted_lines_from_ocr_res(res[0])
    return []

def extract_ocr_page(
    pdf_path: str, 
    page_idx: int, 
    metadata: Dict[str, str], 
    current_section_no: str, 
    current_village_area: str, 
    expected_sl_no: int
) -> Tuple[List[Dict[str, Any]], bool, str, str, int]:
    """
    Extracts voter records using PaddleOCR layout clustering.
    
    Returns: (records, is_voter_page, updated_section_no, updated_village_area, next_expected_sl_no)
    """
    page_num = page_idx + 1
    
    # 1. Convert page to image
    page_pil = convert_pdf_page_to_image(pdf_path, page_idx)
    page_cv = pil_to_cv2(page_pil)
    
    h, w = page_cv.shape[:2]
    
    # 2. Run PaddleOCR on the page
    ocr = get_ocr_model()
    result = ocr.ocr(page_cv)
    
    if not result or len(result) == 0:
        logger.warning(f"Page {page_num}: No OCR results found.")
        return [], False, current_section_no, current_village_area, expected_sl_no
        
    ocr_res = result[0]
    rec_texts = ocr_res.get('rec_texts', [])
    dt_polys = ocr_res.get('dt_polys', [])
    
    if not rec_texts:
        logger.warning(f"Page {page_num}: OCR recognized no text lines.")
        return [], False, current_section_no, current_village_area, expected_sl_no
        
    # 3. Detect Page Header Section Update (top 8%)
    header_lines = []
    header_height_threshold = h * 0.08
    for i in range(len(rec_texts)):
        box = dt_polys[i]
        cy = sum(pt[1] for pt in box) / 4.0
        if cy < header_height_threshold:
            header_lines.append(rec_texts[i])
            
    sec_no, sec_name = parse_page_header_section(header_lines)
    if sec_no and sec_name:
        current_section_no = sec_no
        current_village_area = sec_name
        logger.info(f"Page {page_num} (OCR): Section updated to '{current_section_no} - {current_village_area}'")
        
    # 4. Group Y-coordinates of voter "Name" fields to dynamically locate rows
    name_ys = []
    for i in range(len(rec_texts)):
        text = rec_texts[i].lower()
        box = dt_polys[i]
        cy = sum(pt[1] for pt in box) / 4.0
        if "name" in text and not any(k in text for k in ["father", "husband", "mother", "wife", "relation"]):
            name_ys.append(cy)
            
    name_ys = sorted(name_ys)
    
    row_clusters = []
    for y in name_ys:
        added = False
        for cluster in row_clusters:
            if abs(np.mean(cluster) - y) < 20: # 20px threshold for 100 DPI
                cluster.append(y)
                added = True
                break
        if not added:
            row_clusters.append([y])
            
    row_clusters = sorted(row_clusters, key=lambda c: np.mean(c))
    row_ys = [float(np.mean(c)) for c in row_clusters]
    
    steps = []
    for i in range(len(row_ys) - 1):
        steps.append(row_ys[i+1] - row_ys[i])
    median_step = np.median(steps) if steps else 116.5
    if not (110.0 <= median_step <= 125.0):
        median_step = 116.5
        
    if not row_ys:
        first_y = 140.0 if header_lines else 32.0
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
                    grid[r] = 32.0 + r * median_step
        row_ys = grid

    # 5. Partition OCR texts into 10x3 grid
    cards = {}
    for r in range(10):
        for c in range(3):
            cards[(c, r)] = []
            
    col_width = w / 3.0
    header_threshold = row_ys[0] - 25
    footer_threshold = row_ys[9] + 95
    
    for i in range(len(rec_texts)):
        box = dt_polys[i]
        text = rec_texts[i]
        cx = sum(pt[0] for pt in box) / 4.0
        cy = sum(pt[1] for pt in box) / 4.0
        
        col_idx = int(cx / col_width)
        col_idx = max(0, min(2, col_idx))
        
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
                
    # If the page contains < 3 valid cards, skip it (non-voter/summary page)
    if len(valid_card_cells) < 3:
        logger.info(f"Page {page_num}: OCR non-voter page detected ({len(valid_card_cells)} valid cells). Skipping.")
        return [], False, current_section_no, current_village_area, expected_sl_no

    # 6. Parse cards
    page_records = []
    for r in range(10):
        for c in range(3):
            if (c, r) not in valid_card_cells:
                continue
                
            cell_lines = sorted(cards[(c, r)], key=lambda l: l[1])
            cell_texts = [line[2] for line in cell_lines]
            
            voter_fields = parse_card_text(cell_texts)
            
            # Crop card image region for quadrant OCR fallback
            x_start = int(c * col_width)
            x_end = int((c + 1) * col_width)
            y_start = int(row_ys[r] - 25)
            y_end = int(row_ys[r] + 95)
            
            card_img = page_cv[max(0, y_start):min(h, y_end), max(0, x_start):min(w, x_end)]
            
            # Fallback for Serial Number
            sl_no = voter_fields.get("sl_no", "")
            if not sl_no or not sl_no.isdigit():
                try:
                    fallback_lines = run_quadrant_fallback_ocr(card_img, "top_left")
                    if fallback_lines:
                        # Extract serial number from fallback lines
                        from extractor.voter_parser import parse_sl_no as parse_sl
                        fallback_sl = parse_sl(fallback_lines)
                        if fallback_sl.isdigit():
                            voter_fields["sl_no"] = fallback_sl
                            logger.info(f"Quadrant serial fallback found: {fallback_sl}")
                except Exception as ex:
                    logger.warning(f"Error in quadrant serial fallback at ({c},{r}): {ex}")
                    
            # Fallback for EPIC Number
            epic_no = voter_fields.get("epic_no", "")
            if not epic_no:
                try:
                    fallback_lines = run_quadrant_fallback_ocr(card_img, "top_right")
                    if fallback_lines:
                        # Extract EPIC number from fallback lines
                        from extractor.voter_parser import parse_epic_no as parse_epic
                        fallback_epic = parse_epic(fallback_lines)
                        if fallback_epic:
                            voter_fields["epic_no"] = fallback_epic
                            logger.info(f"Quadrant EPIC fallback found: {fallback_epic}")
                except Exception as ex:
                    logger.warning(f"Error in quadrant EPIC fallback at ({c},{r}): {ex}")
            
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
                
    logger.info(f"Page {page_num} (OCR): Extracted {len(page_records)} voter records.")
    return page_records, True, current_section_no, current_village_area, expected_sl_no
