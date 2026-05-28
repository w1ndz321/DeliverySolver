"""EdgeOne Pages Function entry for AutoSolver API routes."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import Handler as AutoSolverHandler


class handler(AutoSolverHandler):
    """Reuse the local HTTP handler for EdgeOne's BaseHTTPRequestHandler runtime."""
