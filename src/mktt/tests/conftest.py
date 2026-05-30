"""Put the mktt package dir on sys.path so bare imports (gex_engine, app) resolve."""
import os
import sys

MKTT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if MKTT_DIR not in sys.path:
    sys.path.insert(0, MKTT_DIR)
