import os
import sys
import queue
import threading
from pathlib import Path
from typing import Dict, Any, Optional
import customtkinter as ctk
from tkinter import filedialog, messagebox

from extractor import run_extraction_pipeline
from excel.exporter import export_to_excel
from extractor.logger import logger

# Set initial appearance and theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class AppUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Configure window
        self.title("Karnataka Electoral Roll Extractor")
        self.geometry("900x700")
        self.minsize(800, 600)
        
        # Threading & Communication Queue
        self.update_queue = queue.Queue()
        self.is_running = False
        self.cancel_requested = False
        self.extraction_thread = None
        self.all_extracted_records = []
        
        # UI Layout
        self.setup_ui()
        
        # Start queue polling
        self.poll_queue()
        
    def setup_ui(self):
        # Grid layout
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        
        # 1. Header Frame
        header_frame = ctk.CTkFrame(self, height=70, corner_radius=0, fg_color="#1a1c1e")
        header_frame.grid(row=0, column=0, sticky="ew")
        header_frame.grid_propagate(False)
        
        title_label = ctk.CTkLabel(
            header_frame, 
            text="Karnataka Electoral Roll Extractor", 
            font=ctk.CTkFont(family="Helvetica", size=22, weight="bold"),
            text_color="#ffffff"
        )
        title_label.pack(side="left", padx=20, pady=15)
        
        subtitle_label = ctk.CTkLabel(
            header_frame, 
            text="Text-First + OCR Fallback PDF Extractor", 
            font=ctk.CTkFont(family="Helvetica", size=12, slant="italic"),
            text_color="#a0a5ab"
        )
        subtitle_label.pack(side="right", padx=20, pady=20)
        
        # 2. File Selector Frame
        files_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        files_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=15)
        files_frame.grid_columnconfigure(1, weight=1)
        
        # Row 1: Source PDF
        lbl_pdf = ctk.CTkLabel(files_frame, text="Source PDF File:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_pdf.grid(row=0, column=0, sticky="w", padx=10, pady=5)
        
        self.entry_pdf = ctk.CTkEntry(files_frame, placeholder_text="Select Karnataka Electoral Roll PDF file...")
        self.entry_pdf.grid(row=0, column=1, sticky="ew", padx=10, pady=5)
        
        btn_pdf = ctk.CTkButton(files_frame, text="Browse...", width=100, command=self.browse_pdf)
        btn_pdf.grid(row=0, column=2, sticky="e", padx=10, pady=5)
        
        # Row 2: Excel Template
        lbl_temp = ctk.CTkLabel(files_frame, text="Excel Template:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_temp.grid(row=1, column=0, sticky="w", padx=10, pady=5)
        
        self.entry_temp = ctk.CTkEntry(files_frame, placeholder_text="Select Excel template structure (.xlsx)...")
        self.entry_temp.grid(row=1, column=1, sticky="ew", padx=10, pady=5)
        
        # Check if default template is present in workspace root
        default_template = Path(__file__).resolve().parent.parent / "electoral_roll_template.xlsx"
        if default_template.exists():
            self.entry_temp.insert(0, str(default_template))
            
        btn_temp = ctk.CTkButton(files_frame, text="Browse...", width=100, command=self.browse_template)
        btn_temp.grid(row=1, column=2, sticky="e", padx=10, pady=5)
        
        # Row 3: Output Excel Path
        lbl_out = ctk.CTkLabel(files_frame, text="Output Excel Path:", font=ctk.CTkFont(size=13, weight="bold"))
        lbl_out.grid(row=2, column=0, sticky="w", padx=10, pady=5)
        
        self.entry_out = ctk.CTkEntry(files_frame, placeholder_text="Path where the final Excel file will be exported...")
        self.entry_out.grid(row=2, column=1, sticky="ew", padx=10, pady=5)
        
        btn_out = ctk.CTkButton(files_frame, text="Choose Path...", width=100, command=self.browse_output)
        btn_out.grid(row=2, column=2, sticky="e", padx=10, pady=5)
        
        # 3. Main Logging and Warnings Area (Split Tab/Frame Layout)
        tab_frame = ctk.CTkTabview(self, corner_radius=10)
        tab_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=5)
        
        tab_frame.add("Extraction Process Logs")
        tab_frame.add("Validation Warnings & Errors")
        
        # Log Text Box
        self.log_text = ctk.CTkTextbox(tab_frame.tab("Extraction Process Logs"), font=ctk.CTkFont(family="Courier", size=12))
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text.configure(state="disabled")
        
        # Warning Text Box
        self.warn_text = ctk.CTkTextbox(tab_frame.tab("Validation Warnings & Errors"), font=ctk.CTkFont(family="Courier", size=12), text_color="#ffcc00")
        self.warn_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.warn_text.configure(state="disabled")
        
        # 4. Progress and Execution Control Frame
        control_frame = ctk.CTkFrame(self, height=120, corner_radius=10, fg_color="#1e2022")
        control_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=15)
        control_frame.grid_rowconfigure((0, 1), weight=1)
        control_frame.grid_columnconfigure(0, weight=1)
        
        # Row 1: Status Label and Progress Bar
        status_subframe = ctk.CTkFrame(control_frame, fg_color="transparent")
        status_subframe.grid(row=0, column=0, sticky="ew", padx=15, pady=(10, 5))
        status_subframe.grid_columnconfigure(0, weight=1)
        
        self.lbl_status = ctk.CTkLabel(
            status_subframe, 
            text="Status: Ready to extract.", 
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff"
        )
        self.lbl_status.grid(row=0, column=0, sticky="w")
        
        self.lbl_percentage = ctk.CTkLabel(status_subframe, text="0%", font=ctk.CTkFont(size=13, weight="bold"))
        self.lbl_percentage.grid(row=0, column=1, sticky="e")
        
        self.progress_bar = ctk.CTkProgressBar(control_frame, orientation="horizontal")
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
        self.progress_bar.set(0)
        
        # Row 2: Action Buttons
        btn_subframe = ctk.CTkFrame(control_frame, fg_color="transparent")
        btn_subframe.grid(row=2, column=0, sticky="ew", padx=15, pady=(5, 10))
        
        self.btn_start = ctk.CTkButton(
            btn_subframe, 
            text="Start Extraction", 
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1f538d",
            hover_color="#14375e",
            command=self.toggle_extraction
        )
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_clear = ctk.CTkButton(
            btn_subframe, 
            text="Clear Logs", 
            fg_color="#333333",
            hover_color="#444444",
            command=self.clear_all_logs
        )
        self.btn_clear.pack(side="right", padx=5)
        
    # File dialog handlers
    def browse_pdf(self):
        path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if path:
            self.entry_pdf.delete(0, "end")
            self.entry_pdf.insert(0, path)
            
            # Auto populate output path
            pdf_path = Path(path)
            default_out = pdf_path.parent / f"{pdf_path.stem}_extracted.xlsx"
            self.entry_out.delete(0, "end")
            self.entry_out.insert(0, str(default_out))
            
    def browse_template(self):
        path = filedialog.askopenfilename(filetypes=[("Excel files", "*.xlsx")])
        if path:
            self.entry_temp.delete(0, "end")
            self.entry_temp.insert(0, path)
            
    def browse_output(self):
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel files", "*.xlsx")])
        if path:
            self.entry_out.delete(0, "end")
            self.entry_out.insert(0, path)
            
    # Logging helper methods
    def write_log(self, text: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        
    def write_warn(self, text: str):
        self.warn_text.configure(state="normal")
        self.warn_text.insert("end", text + "\n")
        self.warn_text.see("end")
        self.warn_text.configure(state="disabled")
        
    def clear_all_logs(self):
        if self.is_running:
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("0.0", "end")
        self.log_text.configure(state="disabled")

        self.warn_text.configure(state="normal")
        self.warn_text.delete("0.0", "end")
        self.warn_text.configure(state="disabled")

        self.progress_bar.set(0)
        self.lbl_percentage.configure(text="0%")
        self.lbl_status.configure(text="Status: Ready to extract.", text_color="#ffffff")

    def _start_indeterminate_progress(self):
        """Pulses the progress bar back and forth to signal background activity."""
        self._indeterminate_running = True
        self._indeterminate_value = 0.0
        self._indeterminate_direction = 1
        self._pulse_step()

    def _pulse_step(self):
        if not getattr(self, '_indeterminate_running', False):
            return
        self._indeterminate_value += 0.03 * self._indeterminate_direction
        if self._indeterminate_value >= 1.0:
            self._indeterminate_value = 1.0
            self._indeterminate_direction = -1
        elif self._indeterminate_value <= 0.0:
            self._indeterminate_value = 0.0
            self._indeterminate_direction = 1
        self.progress_bar.set(self._indeterminate_value)
        self.lbl_percentage.configure(text="...")
        self.after(40, self._pulse_step)

    def _stop_indeterminate_progress(self):
        self._indeterminate_running = False

    # Extraction Logic Trigger
    def toggle_extraction(self):
        if self.is_running:
            # Cancel current run
            self.cancel_requested = True
            self.btn_start.configure(state="disabled", text="Cancelling...")
            self.lbl_status.configure(text="Status: Cancelling execution...")
            self.write_log("\n[UI] Cancel requested. Stopping at page boundary...")
        else:
            # Validate input paths
            pdf = self.entry_pdf.get().strip()
            template = self.entry_temp.get().strip()
            out = self.entry_out.get().strip()
            
            if not pdf or not os.path.exists(pdf):
                messagebox.showerror("Error", "Please select a valid source PDF file.")
                return
            if not template or not os.path.exists(template):
                messagebox.showerror("Error", "Please select a valid Excel template file.")
                return
            if not out:
                messagebox.showerror("Error", "Please specify a destination path for the exported Excel sheet.")
                return
                
            # Initialize states
            self.is_running = True
            self.cancel_requested = False
            self.all_extracted_records = []
            self.completed_pages_count = 0
            self.btn_start.configure(text="Cancel Extraction", fg_color="#b32424", hover_color="#8c1c1c")
            self.btn_clear.configure(state="disabled")
            
            self.lbl_status.configure(text="Status: Initializing OCR engine...")
            self.update()  # Force UI redraw
            
            # Pre-warm PaddleOCR on main thread to prevent library load deadlocks on macOS
            try:
                from extractor.ocr_fallback import get_ocr_model
                get_ocr_model()
            except Exception as e:
                logger.error(f"Failed loading OCR on main thread: {e}")
                
            self.lbl_status.configure(text="Status: Starting pipeline...")
            self.clear_all_logs()
            self.write_log(f"[UI] Starting electoral roll parser on file: {pdf}")
            self.write_log(f"[UI] Using Excel template: {template}")
            self.write_log(f"[UI] Final Excel destination: {out}")
            
            # Start background thread
            self.extraction_thread = threading.Thread(
                target=self.run_pipeline_thread,
                args=(pdf, template, out),
                daemon=True
            )
            self.extraction_thread.start()
            
    # Background Thread Target
    def run_pipeline_thread(self, pdf_path: str, template_path: str, output_path: str):
        def pipeline_cb(status_dict: Dict[str, Any]) -> bool:
            # Forward status payload back to the main UI thread via Queue
            self.update_queue.put(status_dict)
            # Return False if cancel requested to abort pipeline execution
            return not self.cancel_requested
            
        try:
            # Run extraction
            records = run_extraction_pipeline(pdf_path, progress_callback=pipeline_cb)
            
            # If aborted midway, skip export
            if self.cancel_requested:
                self.update_queue.put({"status": "aborted"})
                return
                
            # If records extracted, proceed to export
            self.update_queue.put({
                "status": "exporting",
                "message": f"Exporting {len(records)} records to Excel template..."
            })
            
            export_to_excel(records, template_path, output_path)
            
            self.update_queue.put({
                "status": "completed_success",
                "output_file": output_path,
                "total_records": len(records),
                "message": f"Success! Extracted {len(records)} records to Excel."
            })
            
        except Exception as err:
            logger.error(f"Pipeline thread encountered error: {err}", exc_info=True)
            self.update_queue.put({
                "status": "error",
                "message": str(err)
            })

    # Queue Polling Loop (Run on Main UI Thread)
    def poll_queue(self):
        try:
            while True:
                msg = self.update_queue.get_nowait()
                self.handle_queue_msg(msg)
                self.update_queue.task_done()
        except queue.Empty:
            pass
        finally:
            # Check queue again in 100 milliseconds
            self.after(100, self.poll_queue)
            
    def handle_queue_msg(self, msg: Dict[str, Any]):
        status = msg.get("status")
        
        # Log generic messages
        if "message" in msg:
            self.write_log(msg["message"])
            
        elif status == "warming_up":
            self.lbl_status.configure(
                text="⏳ OCR engine loading — first run takes 1-2 min. Please wait...",
                text_color="#ffcc00"
            )
            # Pulse the progress bar to indicate activity
            self._start_indeterminate_progress()

        elif status == "started":
            self.progress_bar.set(0)
            self.lbl_percentage.configure(text="0%")
            self.lbl_status.configure(text="Status: Loading cover page...")
            
        elif status == "metadata_loaded":
            meta = msg.get("metadata", {})
            self.lbl_status.configure(text=f"Status: Assembly Roll '{meta.get('ac_name')}' loaded.")
            self.write_log("\n--- Assembly Metadata Extracted ---")
            self.write_log(f"  Assembly Constituency: {meta.get('ac_no')} - {meta.get('ac_name')}")
            self.write_log(f"  Polling Station: {meta.get('booth_no')} - {meta.get('booth_name')}")
            self.write_log(f"  Town / Village: {meta.get('booth')}")
            self.write_log(f"  Initial Section: {meta.get('section_no')} - {meta.get('village_area')}")
            self.write_log("----------------------------------\n")
            
        elif status == "processing_page":
            self._stop_indeterminate_progress()
            page = msg.get("page", 0)
            total = msg.get("total_pages", 1)
            ratio = page / total
            self.progress_bar.set(ratio)
            self.lbl_percentage.configure(text=f"{int(ratio * 100)}%")
            self.lbl_status.configure(
                text=f"Status: Extracting page {page} of {total}...",
                text_color="#ffffff"
            )
            
        elif status == "page_completed":
            self._stop_indeterminate_progress()
            self.completed_pages_count += 1
            page = msg.get("page", 0)
            total = msg.get("total_pages", 1)
            # Display overall progress based on number of completed pages
            ratio = (self.completed_pages_count + 1) / total # +1 because cover page is already done
            ratio = min(1.0, max(0.0, ratio))
            self.progress_bar.set(ratio)
            self.lbl_percentage.configure(text=f"{int(ratio * 100)}%")
            self.lbl_status.configure(
                text=f"Status: Processed page {page} of {total}...",
                text_color="#ffffff"
            )
            
        elif status == "page_error":
            # Just logs error
            pass
            
        elif status == "exporting":
            self.lbl_status.configure(text="Status: Generating Excel file...")
            
        elif status == "aborted":
            self.is_running = False
            self.btn_start.configure(state="normal", text="Start Extraction", fg_color="#1f538d", hover_color="#14375e")
            self.btn_clear.configure(state="normal")
            self.lbl_status.configure(text="Status: Stopped / Cancelled.")
            self.progress_bar.set(0)
            self.lbl_percentage.configure(text="0%")
            messagebox.showwarning("Cancelled", "The extraction pipeline was stopped.")
            
        elif status == "completed_success":
            self.is_running = False
            self.btn_start.configure(state="normal", text="Start Extraction", fg_color="#1f538d", hover_color="#14375e")
            self.btn_clear.configure(state="normal")
            self.lbl_status.configure(text="Status: Extraction complete!")
            self.progress_bar.set(1.0)
            self.lbl_percentage.configure(text="100%")
            
            out_file = msg.get("output_file", "")
            total_rec = msg.get("total_records", 0)
            
            self.write_log(f"\n[UI] Extraction success! Saved {total_rec} records to:\n  {out_file}")
            messagebox.showinfo("Success", f"Extraction completed successfully!\nExtracted {total_rec} voters to:\n{out_file}")
            
        elif status == "error":
            self.is_running = False
            self.btn_start.configure(state="normal", text="Start Extraction", fg_color="#1f538d", hover_color="#14375e")
            self.btn_clear.configure(state="normal")
            self.lbl_status.configure(text="Status: Error encountered.")
            messagebox.showerror("Error", f"An error occurred during extraction:\n{msg.get('message')}")

def run_gui():
    import logging

    app = AppUI()

    # GuiLogHandler forwards log records into the GUI console via the thread-safe queue.
    # Subclass logging.Handler directly (safe even when no other handlers exist yet).
    class GuiLogHandler(logging.Handler):
        def __init__(self, app_instance):
            super().__init__()
            self.app = app_instance

        def emit(self, record):
            try:
                msg = self.format(record)
                self.app.update_queue.put({"status": "log_record", "message": msg})
                if record.levelname == "WARNING":
                    self.app.update_queue.put({"status": "warn_record", "message": msg})
            except Exception:
                pass

    gui_handler = GuiLogHandler(app)
    gui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s]: %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger("electoral_roll_extractor").addHandler(gui_handler)

    # Patch handle_queue_msg to also process log/warn records from the handler above
    def custom_handle_queue_msg(msg: Dict[str, Any]):
        status = msg.get("status")
        if status == "log_record":
            app.write_log(msg["message"])
        elif status == "warn_record":
            app.write_warn(msg["message"])
        else:
            original_handle(msg)

    original_handle = app.handle_queue_msg
    app.handle_queue_msg = custom_handle_queue_msg

    app.mainloop()

if __name__ == "__main__":
    run_gui()
