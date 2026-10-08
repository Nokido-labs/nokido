"""NR -- l'acceptation de l'installation complete (tools/forge_install_acceptance.py + son workflow), 2026-10-07.

Ce qui est garde :
  * une etape dont une dependance n'est pas PASS devient NON_TESTE (avec la raison), une exception devient FAIL,
    et le rapport continue -- un passage dit tout l'ecart ;
  * les identifiants que le script telecharge EXISTENT, epingles, dans distribution/packs/local-llm.toml (sinon le
    runner partirait chercher un composant que le manifeste ne connait pas) ;
  * le workflow ne tourne que sur des runners HEBERGES, en lecture seule, sans secret : du code public n'entre
    jamais sur le runner auto-heberge du poste owner.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
WORKFLOW = RACINE / ".github" / "workflows" / "installation-complete.yml"


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_nr", RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    return m


def test_une_dependance_en_echec_rend_non_teste_et_le_rapport_continue():
    m = _module()

    @m.etape("a")
    def a():
        raise RuntimeError("panne simulee")

    @m.etape("b", "a")
    def b():
        return "PASS", "ne doit pas tourner"

    @m.etape("c")
    def c():
        return "PASS", "independante"

    for f in (a, b, c):
        f()
    assert m.R["a"]["etat"] == "FAIL" and "panne simulee" in m.R["a"]["detail"]
    assert m.R["b"] == {"etat": "NON_TESTE", "detail": "depend de a"}
    assert m.R["c"]["etat"] == "PASS"
    assert "| b | NON_TESTE | depend de a |" in m.resume()


@pytest.mark.parametrize("cid", ["llama-server-windows-x64-cpu", "llama-server-linux-x64-cpu",
                                 "bge-m3-Q8_0.gguf", "bge-reranker-v2-m3-Q8_0.gguf"])
def test_les_composants_telecharges_sont_epingles_au_manifeste(cid):
    c = _module().composant("local-llm", cid)
    assert c["source"] == "url" and c["url"].startswith("https://")
    assert re.fullmatch(r"[0-9a-f]{64}", c["sha256"]) and isinstance(c["taille"], int) and c["taille"] > 0


def test_un_composant_non_epingle_n_est_jamais_telecharge():
    with pytest.raises(LookupError):
        _module().composant("local-llm", "bitnet_b1_58.gguf")


def test_le_workflow_reste_sur_runners_heberges_sans_secret():
    texte = WORKFLOW.read_text(encoding="utf-8")
    assert "self-hosted" not in texte, "du code public ne tourne jamais sur le runner du poste owner"
    assert re.search(r"(?m)^permissions:\s*\n\s+contents: read\s*$", texte)
    assert "secrets." not in texte
    assert "windows-latest" in texte and "ubuntu-latest" in texte
    assert "tools/forge_install_acceptance.py" in texte
    assert re.search(r'push:\s*\n\s+branches:\s*\["essai/\*\*"\]', texte), "push limite aux branches essai/**"
    assert "tags:" not in texte, "une repetition ne se declenche jamais sur un tag de release"
    for ligne in re.findall(r"uses:\s*(\S+)", texte):
        assert re.search(r"@[0-9a-f]{40}$", ligne), "action non epinglee par sha : %s" % ligne


def test_le_promoteur_embarque_le_workflow_dans_le_depot_public():
    src = (RACINE / "tools" / "forge_dist_publish.py").read_text(encoding="utf-8")
    assert '".github/workflows/installation-complete.yml"' in src
