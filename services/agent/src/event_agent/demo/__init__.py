"""Fixtures for demo mode and the evaluation harness.

Kept in their own package because production code imports them — the FastAPI
service falls back to the catalogue when extraction finds nothing, and the page
fetcher serves these pages in demo mode. That dependency is easy to miss when
the fixtures sit beside the real modules.
"""
