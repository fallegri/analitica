import sys
from pathlib import Path

# Add backend to path so `from app.routers...` imports resolve
_backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from app.main import app  # noqa: E402, F401
