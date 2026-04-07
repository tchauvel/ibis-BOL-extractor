# /api/index.py
import sys
import os

# Add the parent directory to sys.path so app.py can be found
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# This is required by Vercel's Python runtime
handler = app
