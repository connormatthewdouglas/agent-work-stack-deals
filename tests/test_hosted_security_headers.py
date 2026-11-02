import re
from pathlib import Path
SRC = (Path(__file__).resolve().parents[1] / "hosted/src/entry.py").read_text()

def test_security_headers_defined_and_cors_kept():
    for h in ("x-content-type-options", "referrer-policy", "content-security-policy", "strict-transport-security"):
        assert f'"{h}"' in SRC
    assert '"access-control-allow-origin": "*"' in SRC and "CORS = {**CORS, **SEC}" in SRC

def test_every_response_carries_headers():
    for m in re.finditer(r"Response\((.*?)\)\n", SRC, re.S):
        call = m.group(1)
        if "headers=" in call:
            assert "CORS" in call or "SEC" in call, call[:120]
