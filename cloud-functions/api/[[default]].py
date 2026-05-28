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

    def _normalize_edgeone_path(self) -> None:
        # EdgeOne removes the file-system route prefix for catch-all Python
        # functions. The local handler expects full /api/... paths.
        path = str(getattr(self, "path", "") or "")
        if path.startswith("/api/"):
            return
        if path.startswith("api/"):
            self.path = "/" + path
            return
        if path.startswith("/"):
            self.path = "/api" + path
            return
        self.path = "/api/" + path

    def do_GET(self) -> None:
        self._normalize_edgeone_path()
        return super().do_GET()

    def do_POST(self) -> None:
        self._normalize_edgeone_path()
        return super().do_POST()
