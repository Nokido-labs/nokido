"""NR -- le hub ecrit la provenance MESUREE de chaque appelant dans sa presence (demande owner 15/10 : « les agents
utilises, dynamiques, avec leur provenance exacte »). La fonction pure est extraite de la source dans un module
temporaire (le hub n'est pas importable en test) ; le cablage est verifie dans le handler."""
import ast
import importlib.util
from pathlib import Path

HUB = Path(__file__).resolve().parents[2] / "tools" / "nokido_hub.py"
SRC = HUB.read_text(encoding="utf-8")


def _module_de(nom, tmp_path):
    arbre = ast.parse(SRC)
    noeud = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == nom)
    f = tmp_path / ("extrait_%s.py" % nom)
    f.write_text("from __future__ import annotations\n" + ast.get_source_segment(SRC, noeud) + "\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location("extrait_" + nom, f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, nom)


def test_le_reseau_du_client_est_mesure_et_classe(tmp_path):
    rc = _module_de("_reseau_client", tmp_path)
    assert rc("127.0.0.1") == "local" and rc("::1") == "local"
    assert rc("100.64.0.1") == "tailscale" and rc("100.127.255.254") == "tailscale"
    assert rc("localhost") == "lan" and rc("localhost") == "lan"
    assert rc("8.8.8.8") == "externe"
    assert rc("unknown") is None and rc("") is None


def test_la_presence_du_hub_recoit_l_adresse_du_client():
    assert "_write_agent_presence(agent_hdr, ring, client=client_ip)" in SRC
    corps = SRC.split("def _write_agent_presence", 1)[1].split("\ndef ", 1)[0]
    assert '"client": client' in corps and '"reseau": _reseau_client(client)' in corps
