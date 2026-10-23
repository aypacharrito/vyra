"""Compatibility entry point; use the same worker as the desktop installer."""
import importlib.util
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
# Preserve existing source-launcher data instead of moving/deleting it.
os.environ.setdefault('VYRA_CLIPS_DATA_DIR', str(ROOT))
sys.path.insert(0, str(ROOT / 'clips-worker'))
spec = importlib.util.spec_from_file_location('vyra_clips_worker', ROOT / 'clips-worker' / 'server.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
app = worker.app
