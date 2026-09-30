# -*- coding: utf-8 -*-
"""NR — `forge_mcp_json_sync --emit-headers` sert de headersHelper sans jamais emettre le maitre.

Reglage (c) accorde par l'owner le 24/09 : le jeton du hub ne doit plus vivre en clair dans
`.mcp.json`. Doc Claude Code (mcp.md) : `headersHelper` = commande lancee a chaque connexion,
qui ecrit sur stdout un objet JSON d'en-tetes. Contrat verifie par le vrai `main()` :
  1. jeton propre present -> JSON d'en-tetes sur stdout (Authorization + noms d'agent) ;
  2. jeton propre absent  -> RIEN sur stdout, code non nul, JAMAIS de repli sur le maitre
     (AUTH-2 : le maitre ne devient pas une identite d'organe ; AUTH-4 : absence = refus) ;
  3. --verifier           -> cles et longueur seulement, jamais la valeur ;
  4. la synchronisation ne reecrit JAMAIS en clair un serveur qui a un headersHelper.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import DIRECT, pas importorskip : sur le livrable teste, un import qui echoue doit
# rougir, pas se lire comme un test passe (faux vert paye le 08/09).
import forge_mcp_json_sync as fms  # noqa: E402

JETON = "ab" * 32


def _coffre(monkeypatch, valeurs):
    monkeypatch.setattr(fms, "vault_get", lambda cle: valeurs.get(cle))
    monkeypatch.setattr(fms, "vault_available", lambda: True)


def _lancer(monkeypatch, capsys, *args):
    monkeypatch.setattr(sys, "argv", ["forge_mcp_json_sync.py", *args])
    rc = fms.main()
    return rc, capsys.readouterr()


def test_emet_le_jeton_propre(monkeypatch, capsys):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON, "FORGE_MCP_TOKEN": "maitre"})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE")
    entetes = json.loads(sortie.out)
    assert rc == 0 and entetes["Authorization"] == "Bearer " + JETON
    assert entetes["X-Agent-Name"] == "CLAUDE"


def test_jamais_le_maitre_en_repli(monkeypatch, capsys):
    _coffre(monkeypatch, {"FORGE_MCP_TOKEN": "maitre"})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE")
    assert rc != 0 and sortie.out == "", "jeton propre absent : aucun en-tete, surtout pas le maitre"
    assert "maitre" not in sortie.out


def test_verifier_n_expose_pas_la_valeur(monkeypatch, capsys):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    rc, sortie = _lancer(monkeypatch, capsys, "--emit-headers", "CLAUDE", "--verifier")
    assert rc == 0 and JETON not in sortie.out
    assert json.loads(sortie.out)["longueur_jeton"] == len(JETON)


def test_un_serveur_a_helper_n_est_jamais_reecrit_en_clair(monkeypatch):
    _coffre(monkeypatch, {"FORGE_TOKEN_CLAUDE": JETON})
    cfg = {"mcpServers": {"hub": {"type": "http", "headersHelper": "x",
                                  "headers": {"X-Agent-Name": "CLAUDE"}}}}
    nouveau, changements = fms._patch_config(cfg)
    assert "Authorization" not in nouveau["mcpServers"]["hub"]["headers"]
    assert changements[0][1].startswith("HEADERS_HELPER")
