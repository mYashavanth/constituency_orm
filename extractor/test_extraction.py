import os
import sys
import openpyxl
from pathlib import Path

# Insert parent dir to path so we can import extractor and excel modules
project_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_dir))

from extractor import run_extraction_pipeline
from excel.exporter import export_to_excel

def test_e2e_extraction():
    pdf_path = project_dir / "2025-EROLLGEN-S10-196-FinalRoll-Revision1-ENG-5-WI.pdf"
    template_path = project_dir / "electoral_roll_template.xlsx"
    output_path = project_dir / "output_test.xlsx"
    
    print("==================================================")
    print("Running end-to-end extraction verification...")
    print(f"Source PDF: {pdf_path}")
    print(f"Excel Template: {template_path}")
    print(f"Output File: {output_path}")
    print("==================================================")
    
    # Progress callback to show step changes in stdout
    def progress_cb(status_dict):
        status = status_dict.get("status")
        message = status_dict.get("message")
        if status == "started":
            print(f"[STATUS] {status.upper()}: {message}")
        elif status == "metadata_loaded":
            print(f"[STATUS] METADATA: {message}")
        elif status == "processing_page":
            print(f"[STATUS] PAGE PROGRESS: Page {status_dict.get('page')}/{status_dict.get('total_pages')}")
        elif status == "completed":
            print(f"[STATUS] COMPLETED: {message}")
        return True
        
    # Run pipeline
    records = run_extraction_pipeline(str(pdf_path), progress_callback=progress_cb)
    
    # Export to Excel
    export_to_excel(records, str(template_path), str(output_path))
    
    # Verify records count
    print("\n--- Verification Results ---")
    print(f"Total extracted records in memory: {len(records)}")
    
    # Read back Excel worksheet to verify counts
    wb = openpyxl.load_workbook(output_path)
    sheet = wb.active
    excel_rows_count = sheet.max_row - 1 # Subtract 1 for the header
    print(f"Total voter rows in generated Excel: {excel_rows_count}")
    
    # Assertion check
    expected_count = 448
    if excel_rows_count == expected_count:
        print(f"SUCCESS: The generated Excel file contains exactly {expected_count} records.")
        sys.exit(0)
    else:
        print(f"ERROR: Expected {expected_count} records, but got {excel_rows_count}.")
        sys.exit(1)

if __name__ == "__main__":
    test_e2e_extraction()
