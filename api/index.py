"""Vercel serverless entrypoint for the FastAPI app."""

import sys
from pathlib import Path

# Make the project root importable so server.py and its sibling modules resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import app  # noqa: E402
