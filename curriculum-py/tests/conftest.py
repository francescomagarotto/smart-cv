"""Shared pytest configuration.

Adds ``src/`` to ``sys.path`` so that ``cv_skill`` is importable without
requiring the package to be installed in the test environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Insert src/ at the front of the path so cv_skill can be imported directly.
_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
