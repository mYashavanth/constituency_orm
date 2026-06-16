import os
# Set single thread environment variables to prevent PaddlePaddle/OpenMP deadlocks on macOS
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

from ui.main_window import run_gui

if __name__ == "__main__":
    run_gui()
