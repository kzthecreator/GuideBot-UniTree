"""Compatibility import; implementation lives in drivers.agc2."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivers.agc2 import runtime as _runtime
sys.modules[__name__] = _runtime
