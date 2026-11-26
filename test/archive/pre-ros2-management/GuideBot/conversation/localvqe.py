"""Compatibility import; implementation lives in drivers.localvqe."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivers.localvqe import runtime as _runtime
sys.modules[__name__] = _runtime
