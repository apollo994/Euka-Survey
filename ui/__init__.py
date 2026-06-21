"""Streamlit view modules for EukaSurvey.

Each module exposes a single `render_*` function. `app.py` is the
controller that wires them together; nothing in `ui/` calls anything
in `ui/` (every cross-section state hop goes through `QueryState`).
"""
