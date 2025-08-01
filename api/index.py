"""Vercel entry point for the FastAPI application."""

import os
import sys

# Ensure the project root is on the Python path so ``main`` can be imported
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from main import app

__all__ = ["app"]
