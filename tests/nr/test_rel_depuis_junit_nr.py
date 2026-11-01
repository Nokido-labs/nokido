"""NR : REL (rapports d'erreur localises) tires d'un JUnit rouge, consommes par le self-patcher."""
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charge(nom, rel):
    spec = importlib.util.spec_from_file_location(nom, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod


TRACE_APP = """def test_a():
>       x.boom()

tests/test_a.py:7:
_ _ _
    def boom():
>       raise ValueError("x")
app/x.py:12: in boom
E   ValueError: x"""

TRACE_TESTS = """def test_b():
>       assert 1 == 2
tests/test_b.py:3: AssertionError"""


def _junit(chemin):
    chemin.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="p" tests="2" failures="2" errors="0" skipped="0">'
        '<testcase classname="tests.test_a" name="test_a"><failure message="ValueError: x">'
        + TRACE_APP + '</failure></testcase>'
        '<testcase classname="tests.test_b" name="test_b"><failure message="assert 1 == 2">'
        + TRACE_TESTS + '</failure></testcase>'
        '</testsuite></testsuites>', encoding="utf-8")
    return chemin


def _bloc(md):
    return json.loads(re.search(r"```json\s*(.*?)```", md, re.S).group(1))


def _par_id(out):
    return {_bloc(p.read_text(encoding="utf-8"))["error_id"]: p for p in out.glob("evolution_proposal_rel_*.md")}


def test_pointer_ref_traverse_tests_puis_app(tmp_path):
    rel = _charge("rel_mod", "tools/forge_rel_depuis_junit.py")
    out = tmp_path / "out"
    assert rel.main(["--junit", str(_junit(tmp_path / "j.xml")), "--out-dir", str(out)]) == 0
    a = _bloc(_par_id(out)["tests.test_a::test_a"].read_text(encoding="utf-8"))
    assert a["pointer_ref"] == {"file": "app/x.py", "function": "boom", "line": 12}
    assert "ValueError" in a["evidence"]["message"]


def test_sans_frame_app_tools_pointer_null_et_dit(tmp_path):
    rel = _charge("rel_mod", "tools/forge_rel_depuis_junit.py")
    out = tmp_path / "out"
    rel.main(["--junit", str(_junit(tmp_path / "j.xml")), "--out-dir", str(out)])
    p = _par_id(out)["tests.test_b::test_b"]
    t = p.read_text(encoding="utf-8")
    assert _bloc(t)["pointer_ref"] is None
    assert "pointer_ref null" in t


def test_dedoublonnage_7_jours(tmp_path):
    rel = _charge("rel_mod", "tools/forge_rel_depuis_junit.py")
    out = tmp_path / "out"
    j = str(_junit(tmp_path / "j.xml"))
    rel.main(["--junit", j, "--out-dir", str(out)])
    avant = {p.name: p.stat().st_mtime_ns for p in out.glob("*.md")}
    rel.main(["--junit", j, "--out-dir", str(out)])
    apres = {p.name: p.stat().st_mtime_ns for p in out.glob("*.md")}
    assert len(avant) == 2 and avant == apres


def test_dry_run_n_ecrit_rien_via_cli(tmp_path, capsys):
    rel = _charge("rel_mod", "tools/forge_rel_depuis_junit.py")
    out = tmp_path / "out"
    assert rel.main(["--junit", str(_junit(tmp_path / "j.xml")), "--out-dir", str(out), "--dry-run"]) == 0
    assert not out.exists() or not list(out.iterdir())
    assert "app/x.py" in capsys.readouterr().out


def test_self_patcher_refuse_target_hors_pointer_ref(tmp_path, monkeypatch):
    rel = _charge("rel_mod", "tools/forge_rel_depuis_junit.py")
    sp = _charge("sp_mod", "tools/forge_self_patcher.py")
    props = tmp_path / "props"
    rel.main(["--junit", str(_junit(tmp_path / "j.xml")), "--out-dir", str(props)])
    pa = _par_id(props)["tests.test_a::test_a"]
    pa.write_text(pa.read_text(encoding="utf-8").replace('"file": "app/x.py"', '"file": "tools/forge_rel_depuis_junit.py"')
                  .replace('"function": "boom"', '"function": "main"'), encoding="utf-8")
    pb = _par_id(props)["tests.test_b::test_b"]
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", tmp_path / "applied")
    monkeypatch.setattr(sp, "_rag_lookup", lambda *_a, **_k: "")
    prompts = []

    def faux_hub(tool, args, timeout=60):
        prompts.append(args["message"])
        rep = json.dumps({"target_file": "app/autre.py", "patch_search": "a", "patch_replace": "b"})
        return {"result": {"content": [{"text": rep}]}}

    monkeypatch.setattr(sp, "_hub_call", faux_hub)
    juge = []
    monkeypatch.setattr(sp, "_submit_to_judge", lambda *a, **k: juge.append(a) or {"verdict": "SURVIT"})
    st = sp.run_once()
    assert len(prompts) == 1 and "def main" in prompts[0] and "tests.test_a::test_a" in prompts[0]
    assert juge == [] and st["patches_applied"] == 0
    applied = {q.name for q in (tmp_path / "applied").glob("*.md")}
    assert pa.name in applied          # refusee mais jugee : consommee
    assert pb.name not in applied      # pointer_ref null : NON consommee
