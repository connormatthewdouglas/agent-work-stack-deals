import pathlib, re, shutil, subprocess, pytest
JS = (pathlib.Path(__file__).resolve().parent.parent / "embed/badge.js").read_text()
@pytest.mark.skipif(not shutil.which("node"), reason="node")
@pytest.mark.parametrize("ref,want", [("t54-gpuhunt", "?ref=t54-gpuhunt"), ("T54 <x>&y", "?ref=t54xy"), ("a" * 80, "?ref=" + "a" * 64), ("", "")])
def test_badge_ref_passthrough(ref, want):
    fns = re.search(r"(function refOf.*?\nfunction withRef[^\n]*)", JS, re.S).group(1)
    js = fns + f"\nconsole.log(withRef({{getAttribute:()=>{ref!r}}},'https://thelanternworks.com/gpu/h100-rental-price/'))"
    out = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, check=True).stdout.strip()
    assert out == "https://thelanternworks.com/gpu/h100-rental-price/" + want
