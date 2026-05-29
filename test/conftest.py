"""Pytest configuration for OpenAgens API tests."""

import sys
from pathlib import Path

# Ensure the api package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
