import fitz
import time
import concurrent.futures
from typing import List, Dict, Any, Callable, Optional
from extractor.logger import logger
from extractor.metadata_parser import parse_page1_metadata
from extractor.ocr_fallback import extract_ocr_page, get_ocr_model, pil_to_cv2, convert_pdf_page_to_image, extract_sorted_lines_from_ocr_res, run_ocr_on_image
from extractor.pdf_text_parser import extract_pdf_text_page
from extractor.validators import validate_voter_record, is_record_creatable

def _process_page_worker(pdf_path: str, p_idx: int, page_num: int, metadata: Dict[str, Any], force_ocr: bool = False) -> Dict[str, Any]:
    """
    Worker function to process a single page in a separate thread.
    Opens its own PyMuPDF document instance for thread safety.
    """
    page_start = time.time()
    ocr_time = 0.0
    
    try:
        doc = fitz.open(pdf_path)
        page = doc[p_idx]
        
        page_records = None
        is_voter = False
        updated_sec_no = ""
        updated_sec_name = ""
        
        if not force_ocr:
            # Try text-first extraction
            page_records, is_voter, updated_sec_no, updated_sec_name, _ = extract_pdf_text_page(
                page, page_num, metadata, "", "", 1
            )
        
        # If force_ocr or text-first extraction returned None (scanned page)
        if page_records is None:
            ocr_start = time.time()
            page_records, is_voter, updated_sec_no, updated_sec_name, _ = extract_ocr_page(
                pdf_path, p_idx, metadata, "", "", 1
            )
            ocr_time = time.time() - ocr_start
            
        doc.close()
        
        total_time = time.time() - page_start
        return {
            "page_num": page_num,
            "success": True,
            "page_records": page_records,
            "is_voter": is_voter,
            "updated_sec_no": updated_sec_no,
            "updated_sec_name": updated_sec_name,
            "total_time": total_time,
            "ocr_time": ocr_time
        }
    except Exception as e:
        logger.error(f"Worker thread error on Page {page_num}: {e}", exc_info=True)
        return {
            "page_num": page_num,
            "success": False,
            "error": str(e)
        }

def run_extraction_pipeline(
    pdf_path: str, 
    progress_callback: Optional[Callable[[Dict[str, Any]], bool]] = None
) -> List[Dict[str, Any]]:
    """
    Runs the full extraction pipeline: Cover Page metadata parsing (direct text, fallback to OCR),
    then voter pages extraction in parallel using a thread pool.
    """
    pipeline_start_time = time.time()
    logger.info(f"Starting extraction pipeline for PDF: {pdf_path}")
    
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"Failed to open PDF file {pdf_path}: {e}")
        raise ValueError(f"Could not open PDF file: {e}")
        
    total_pages = len(doc)
    if total_pages == 0:
        logger.error("PDF file has 0 pages.")
        raise ValueError("PDF file has 0 pages.")
        
    # 1. PROCESS PAGE 1 (METADATA)
    if progress_callback:
        if not progress_callback({
            "status": "started",
            "page": 1,
            "total_pages": total_pages,
            "message": "Extracting metadata from cover page..."
        }):
            logger.info("Extraction aborted by user.")
            doc.close()
            return []
            
    page1 = doc[0]
    # Try direct text extraction from cover page
    text_lines = []
    try:
        page1_text = page1.get_text()
        text_lines = [line.strip() for line in page1_text.split("\n") if line.strip()]
    except Exception as e:
        logger.warning(f"Failed to get direct text on page 1: {e}")

    # If cover page has no selectable text (scanned PDF), run OCR to extract metadata.
    # This triggers PaddleOCR initialization on first run — notify UI so it can show
    # a clear "warming up" message instead of appearing frozen at 0%.
    if not text_lines or sum(len(line) for line in text_lines) < 100:
        logger.info("Cover page has no selectable text. Running OCR to extract metadata...")
        if progress_callback:
            progress_callback({
                "status": "warming_up",
                "message": "OCR engine loading (first run may take 1-2 minutes)..."
            })
        try:
            page1_pil = convert_pdf_page_to_image(pdf_path, 0, dpi=100)
            res = run_ocr_on_image(page1_pil)
            text_lines = extract_sorted_lines_from_ocr_res(res)
        except Exception as e:
            logger.error(f"Failed running OCR on cover page: {e}")

    metadata = parse_page1_metadata(text_lines, pdf_path)
    logger.info(f"Page 1 metadata parsed successfully: {metadata}")
    doc.close()  # Close main thread's fitz document
    
    # State tracking for sequential reconstruction
    # section_no and village_area start empty — each voter page header is the authoritative source.
    # booth (main town/village) is permanently from the cover page metadata.
    current_section_no = ""  # Will be set from page 3's header onwards
    current_village_area = ""
    expected_sl_no = 1
    all_records = []
    
    if progress_callback:
        if not progress_callback({
            "status": "metadata_loaded",
            "page": 1,
            "total_pages": total_pages,
            "metadata": metadata,
            "message": f"Metadata loaded. Assembly: {metadata.get('ac_name')}, Polling Station: {metadata.get('booth_name')}"
        }):
            logger.info("Extraction aborted by user.")
            return []
            
    # 2. PRE-WARM PADDLEOCR MODEL SINGLETON
    logger.info("Pre-warming PaddleOCR singleton for threaded pipeline...")
    try:
        get_ocr_model()
    except Exception as e:
        logger.error(f"Failed to pre-warm PaddleOCR: {e}")

    # 3. RUN PARALLEL PAGE PROCESSING
    logger.info("Starting concurrent page processing (max_workers=2)...")
    results = {}
    
    # Determine if PDF is scanned based on cover page text lines
    force_ocr = (not text_lines or sum(len(line) for line in text_lines) < 100)
    if force_ocr:
        logger.info("Cover page analysis indicates scanned PDF. Bypassing digital text check for all pages.")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}
        for p_idx in range(2, total_pages):
            page_num = p_idx + 1
            future = executor.submit(
                _process_page_worker, pdf_path, p_idx, page_num, metadata, force_ocr
            )
            futures[future] = page_num
            
        # Notify progress page processing starts
        if progress_callback:
            progress_callback({
                "status": "processing_page",
                "page": 3,
                "total_pages": total_pages,
                "message": f"Processing Page 3 of {total_pages}..."
            })
            
        next_page_to_process = 3
        cancelled = False

        # As threads finish, store results and perform sequential post-processing
        for future in concurrent.futures.as_completed(futures):
            page_num = futures[future]
            try:
                res = future.result()
                results[page_num] = res
                
                # Check for user cancellation in progress callback
                if progress_callback:
                    p_recs = res.get("page_records") or []
                    is_v = res.get("is_voter", False)
                    t_time = res.get("total_time", 0.0)
                    o_time = res.get("ocr_time", 0.0)
                    ocr_suffix = f" (OCR: {o_time:.2f}s)" if o_time > 0 else ""
                    
                    msg = f"Page {page_num} processed in {t_time:.2f}s{ocr_suffix}. Extracted {len(p_recs)} records."
                    
                    if not progress_callback({
                        "status": "page_completed",
                        "page": page_num,
                        "total_pages": total_pages,
                        "records_count": len(p_recs),
                        "is_voter": is_v,
                        "message": msg
                    }):
                        logger.info("Extraction aborted by user. Shutting down pool...")
                        executor.shutdown(wait=False, cancel_futures=True)
                        cancelled = True
                        break
            except Exception as e:
                logger.error(f"Error retrieving future for page {page_num}: {e}", exc_info=True)
                results[page_num] = {"success": False, "error": str(e)}

            if cancelled:
                break

            # Process ready page results sequentially to maintain section and serial tracking
            while not cancelled and next_page_to_process in results:
                # Notify UI which page we're sequentially processing
                if progress_callback:
                    progress_callback({
                        "status": "processing_page",
                        "page": next_page_to_process,
                        "total_pages": total_pages,
                        "message": f"Processing Page {next_page_to_process} of {total_pages}..."
                    })

                page_res = results[next_page_to_process]
                if page_res.get("success"):
                    if page_res.get("is_voter"):
                        up_sec_no = page_res.get("updated_sec_no")
                        up_sec_name = page_res.get("updated_sec_name")
                        if up_sec_no and up_sec_name:
                            current_section_no = up_sec_no
                            current_village_area = up_sec_name
                            logger.info(f"Sequential processing: Section updated on Page {next_page_to_process} to '{current_section_no} - {current_village_area}'")
                            
                        raw_recs = page_res.get("page_records") or []
                        page_added_count = 0
                        for rec in raw_recs:
                            rec["section_no"] = current_section_no
                            rec["village_area"] = current_village_area

                            # --- SERIAL RECONSTRUCTION ---
                            # Only assign expected_sl_no if the parsed serial number is missing or 0.
                            # We do NOT force sequential reordering of valid non-zero parsed serial numbers
                            # because the serial number is fixed for each citizen, and any gaps should
                            # remain visible to help trace missed cards rather than shifting/corrupting subsequent records.
                            sl_val = rec.get("sl_no", "")
                            try:
                                sl_val_int = int(str(sl_val).strip())
                            except ValueError:
                                sl_val_int = 0

                            if sl_val_int == 0:
                                rec["sl_no"] = str(expected_sl_no)
                            # Validate and check serial sequence with correct expected_sl_no
                            warnings, sanitized_record = validate_voter_record(rec, expected_sl_no)
                            
                            # Log validation warnings so they appear in stdout and GUI warning tab
                            if warnings:
                                for warn in warnings:
                                    logger.warning(
                                        f"Page {next_page_to_process} | SL: {sanitized_record.get('sl_no')} | "
                                        f"EPIC: {sanitized_record.get('epic_no')} | {warn}"
                                    )
                                    
                            if is_record_creatable(sanitized_record):
                                if isinstance(sanitized_record.get("sl_no"), int):
                                    expected_sl_no = sanitized_record["sl_no"] + 1
                                else:
                                    expected_sl_no += 1
                                    
                                sanitized_record["warnings"] = warnings
                                all_records.append(sanitized_record)
                                page_added_count += 1
                                logger.info(
                                    f"  [RECORD] Page {next_page_to_process} | SL: {sanitized_record.get('sl_no')} | "
                                    f"EPIC: {sanitized_record.get('epic_no')} | Name: {sanitized_record.get('name')} | "
                                    f"Rel: {sanitized_record.get('relation_type')} - {sanitized_record.get('relation_name')} | "
                                    f"Age: {sanitized_record.get('age')} | Gender: {sanitized_record.get('gender')}"
                                )
                        
                        t_time = page_res.get("total_time", 0.0)
                        o_time = page_res.get("ocr_time", 0.0)
                        ocr_suffix = f" (OCR: {o_time:.2f}s)" if o_time > 0 else ""
                        logger.info(f"Page {next_page_to_process}: {page_added_count} records in {t_time:.2f}s{ocr_suffix}")
                    else:
                        logger.info(f"Page {next_page_to_process}: Skipped non-voter page.")
                else:
                    err_msg = page_res.get("error", "Unknown thread error")
                    logger.error(f"Sequential processing: Page {next_page_to_process} has error: {err_msg}")
                    
                next_page_to_process += 1

    pipeline_elapsed = time.time() - pipeline_start_time
    logger.info(f"Extraction pipeline completed in {pipeline_elapsed:.2f} seconds.")
    
    if progress_callback:
        progress_callback({
            "status": "completed",
            "page": total_pages,
            "total_pages": total_pages,
            "total_records": len(all_records),
            "message": f"Completed in {pipeline_elapsed:.2f}s. Extracted {len(all_records)} voter records in total."
        })
        
    return all_records
