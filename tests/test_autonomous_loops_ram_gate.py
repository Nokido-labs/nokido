"""_ram_gate : ressource indéterminée = INDECIDABLE = refus, jamais fail-open.

Hermétique : extrait le code objet de la fonction depuis le source, sans
importer le module daemon (import de forge_autonomous_loops = effets de bord
registry/DB).
"""
import builtins
import io
import sys
import types
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"


def _load_ram_gate(monkeypatch, psutil_module):
    src = io.open(APP / "forge_autonomous_loops.py", encoding="utf-8").read()
    start = src.index("def _ram_gate")
    end = src.index("\n\n\n", start)
    warnings = []
    ns = {
        "__builtins__": builtins,
        "sys": types.SimpleNamespace(path=types.SimpleNamespace(insert=lambda *a: None)),
        "ROOT": Path("."),
        "log": types.SimpleNamespace(warning=warnings.append),
    }
    # None dans sys.modules -> ImportError au `import` (panne simulée).
    #
    # ⚠️ DEFAUT MESURE le 2026-09-10 : seul le nom PLAT etait pose, alors que
    # `_ram_gate` fait `from nokido_agent.app.forge_resource_manager import
    # request_resources` (mesure dans le source extrait). La panne n'etait donc
    # PAS simulee : le vrai gestionnaire de ressources repondait, et
    # `test_double_panne_refuse_jamais_fail_open` lisait `True is False`. Un test
    # ecrit contre le fail-open ne prouvait plus rien contre le fail-open.
    for _nom in ("forge_resource_manager", "nokido_agent.app.forge_resource_manager"):
        monkeypatch.setitem(sys.modules, _nom, None)
    monkeypatch.setitem(sys.modules, "psutil", psutil_module)
    mod_code = compile(src[start:end], "ram_gate_extract", "exec")
    fn_code = next(
        c for c in mod_code.co_consts
        if isinstance(c, types.CodeType) and c.co_name == "_ram_gate"
    )
    gate = types.FunctionType(fn_code, ns, "_ram_gate", (2.0, ""))
    return gate, warnings


def _fake_psutil(avail_gb):
    vm = types.SimpleNamespace(available=int(avail_gb * 1024 ** 3))
    return types.SimpleNamespace(virtual_memory=lambda: vm)


def test_fallback_psutil_autorise_si_ram_suffisante(monkeypatch):
    gate, _ = _load_ram_gate(monkeypatch, _fake_psutil(64))
    assert gate(2.0, "t") is True


def test_fallback_psutil_refuse_si_ram_insuffisante(monkeypatch):
    gate, warnings = _load_ram_gate(monkeypatch, _fake_psutil(1))
    assert gate(2.0, "t") is False
    assert any("INDECIDABLE" in w for w in warnings)


def test_double_panne_refuse_jamais_fail_open(monkeypatch):
    gate, warnings = _load_ram_gate(monkeypatch, None)
    assert gate(2.0, "t") is False
    assert any("INDECIDABLE" in w for w in warnings)
