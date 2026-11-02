"""Hosted worker sends X-Frame-Options: DENY (plus CSP frame-ancestors 'none') on every response."""
from pathlib import Path
SRC = (Path(__file__).resolve().parents[1] / "hosted" / "src" / "entry.py").read_text()


def test_x_frame_options_deny():
    assert '"x-frame-options": "DENY"' in SRC and "frame-ancestors 'none'" in SRC and "CORS = {**CORS, **SEC}" in SRC
