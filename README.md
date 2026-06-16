# Karnataka Electoral Roll Extractor

A production-grade local desktop application that extracts voter records from Karnataka Electoral Roll PDFs (either searchable text PDFs or scanned image PDFs) and exports the structured data into an Excel spreadsheet.

## Key Features

1. **Text-First Processing**: The engine automatically inspects the PDF structure. If native text is selectable, it processes the entire page in milliseconds without expensive OCR.
2. **Robust OCR Fallback**: If a page has no selectable text (scanned PDF), it renders the page and uses the high-performance PaddleOCR model to perform layout analysis and character recognition.
3. **Identical Coordinate-Based Clustering**: Both searchable text and OCR lines are processed through the same geometric cell grouping engine, ensuring layout extraction accuracy.
4. **Voter Record Validation**: It ignores empty/corrupted card segments. A voter record is appended to Excel **only** if it contains a valid Serial Number (non-empty) and a valid EPIC Number.
5. **Real-Time Log & Warning Panel**: View progress percentage, extraction steps, and format validation warnings (e.g. EPIC structure, age bounds) as they happen.
6. **Windows Standalone Packaging**: Builds into a single `.exe` that can be run on Windows machines without any Python installation.

---

## Installation & Setup

### 1. Prerequisites
- Python 3.8 to 3.12 installed on your machine.
- Pip (Python Package Manager).

### 2. Install Dependencies
Open a command prompt in the project root directory and run:
```bash
pip install -r requirements.txt
```

---

## Running the Application

### 1. Run the GUI locally:
```bash
python app.py
```

### 2. Build the Standalone Windows Executable:
If you are on Windows, simply double-click the `build_exe.bat` file. Alternatively, run:
```bash
pyinstaller --onefile --windowed --name="Karnataka_Electoral_Roll_Extractor" --add-data "electoral_roll_template.xlsx;." --collect-data customtkinter app.py
```
This produces a single standalone file `Karnataka_Electoral_Roll_Extractor.exe` inside the `dist/` directory.

---

## How it Works (Under the Hood)

1. **Cover Page Metadata Parsing**: The application processes the first page of the PDF to extract the Assembly Constituency (AC) number/name, Polling Station/Booth number/name, Village/Town, and initial section.
2. **Page Section Updates**: On subsequent pages, the top 8% header region is checked. If it matches a new section pattern (e.g. `Section No and Name : 2 - Nagenahalli`), the section number and name are updated.
3. **Geometric Row Grid Clustering**:
   - The engine searches for fields containing "Name" to determine the horizontal center coordinate of the 10 rows.
   - It clusters the Y coordinates of these "Name" lines to determine row boundaries.
   - If rows are missing, it uses a uniform row step size (typically ~116.5 pixels or ~84 points) to reconstruct a perfect 10-row grid.
4. **Grid Mapping**: All text blocks on the page are assigned to columns (0, 1, or 2 based on page width divisions) and rows (closest row cluster).
5. **Card Field Parser**:
   - Individual cells are validated (requires text lines count >= 3, name/EPIC keyword, and voter keywords).
   - Valid cells are parsed line-by-line using regular expressions to extract Serial Number, EPIC, Name, Relation Type, Relative Name, House Number, Age, and Gender.
   - **Quadrant Fallback OCR**: If a cell is processed via OCR but its Serial Number or EPIC is missing or corrupted, the engine crops the top-left (for Serial) or top-right (for EPIC) quadrant of the card image and runs high-precision targeted OCR on just that crop.
6. **Excel Integration**: Appends records to the user-provided Excel template, dynamically mapping columns based on header titles.
# constituency_orm
