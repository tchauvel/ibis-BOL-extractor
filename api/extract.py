"""
extract.py — Vercel serverless entry point.

Vercel's builds config points at this file. It simply imports
the FastAPI app from the api package and exposes it as `handler`.
"""
from api import app  # noqa: F401

handler = app
