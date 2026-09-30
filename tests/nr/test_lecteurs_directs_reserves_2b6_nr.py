"""NR -- etape 2b-6 du correctif du coffre (go owner 2026-09-28) : plus AUCUN lecteur direct
d'un nom reserve au coffre machine.

Le retrait des copies du coffre machine est la vraie frontiere : tant qu'un module lit un
nom reserve par `vault_get` en direct, il echappe au guichet (coffre reserve, transition,
fermeture, recensement) et casserait EN SILENCE au retrait. Mesure du 2026-09-28 : six
lecteurs directs du jeton maitre dans app/ et tools/, dont deux synchroniseurs qui
ECRIVAIENT le maitre en clair dans des configurations clientes quand un agent n'avait pas
de jeton propre.

Contrats :
  1. aucun `vault_get("<nom reserve>")` litteral dans app/ ni tools/ (hors le coffre et le
     guichet eux-memes) ;
  2. forge_vscode_mcp_sync et forge_mcp_json_sync ne rendent JAMAIS le maitre comme jeton
     d'un agent (doctrine deja ecrite dans `_jeton_propre` : le maitre ne devient pas une
     identite d'organe) ;
  3. le grounder presente le jeton de l'identite qu'il annonce (GROUNDER), par la brique
     `jeton_hub` -- propre, sinon le maitre en transition dite.

Aucune vraie valeur n'est lue : les coffres sont substitues.
"""
from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + lecture
#   (l.47)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
FS = "nokido_agent.app.forge_secrets"
EXCLUS = {"app/forge_machine_vault.py", "app/forge_secrets.py"}
MAITRE = "maitre-de-test-2b6-lecteurs"


def _charger(rel: str, nom: str):
    spec = importlib.util.spec_from_file_location(nom, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_aucun_lecteur_direct_d_un_nom_reserve_dans_app_et_tools():
    noms = importlib.import_module(FS).NOMS_RESERVES
    rx = re.compile(r"vault_get\(\s*[\"'](?:%s)[\"']" % "|".join(re.escape(n) for n in sorted(noms)))
    trouves, vus = [], 0
    for d in ("app", "tools"):
        for p in (ROOT / d).rglob("*.py"):
            rel = p.relative_to(ROOT).as_posix()
            if rel in EXCLUS or "__pycache__" in rel or "archaeology" in rel:
                continue
            vus += 1
            for i, ligne in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(ligne) and not ligne.lstrip().startswith("#"):
                    trouves.append(f"{rel}:{i}")
    assert vus > 500, f"balayage anormalement court ({vus} fichiers)"
    assert trouves == [], "lecture directe d'un nom reserve -- passer par le guichet : " + ", ".join(trouves)


def _faux_coffre(cle):
    return MAITRE if cle == "FORGE_MCP_TOKEN" else None


def test_la_synchro_vscode_n_ecrit_jamais_le_maitre(monkeypatch):
    m = _charger("tools/forge_vscode_mcp_sync.py", "nr_2b6_vscode_sync")
    monkeypatch.setattr(m, "vault_get", _faux_coffre)
    monkeypatch.setattr(m, "vault_available", lambda: True)
    jeton = m._resolve_token("AGENT_SANS_JETON_PROPRE")
    ok = jeton == ""
    assert ok


def test_la_synchro_mcp_json_n_ecrit_jamais_le_maitre(monkeypatch):
    m = _charger("tools/forge_mcp_json_sync.py", "nr_2b6_mcp_json_sync")
    monkeypatch.setattr(m, "vault_get", _faux_coffre)
    jeton = m._resolve_token("AGENT_SANS_JETON_PROPRE")
    ok = jeton is None
    assert ok


def test_le_grounder_presente_le_jeton_de_son_identite(monkeypatch):
    cred = importlib.import_module("nokido_agent.app.forge_agent_credential")
    demandes: list = []
    monkeypatch.setattr(cred, "jeton_hub", lambda agent: demandes.append(agent) or "jeton-de-test")
    g = importlib.import_module("nokido_agent.app.forge_grounder")
    ok = g._token() == "jeton-de-test"
    assert ok
    assert demandes == ["GROUNDER"]
