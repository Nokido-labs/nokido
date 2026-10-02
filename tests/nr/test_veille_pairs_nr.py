"""NR -- la boucle du client est REVEILLEE quand un pair cloud depose son rendu (forge_job_watch_cli --pair).

Owner 2026-10-01 : « la capsule claude.ai est finie, tu ne le vois pas direct ? lance un monitor en
fonction du LLM qui le lance ». Job local -> --job, tache d'AGY -> --task, pair cloud -> --pair.
Contrat : premier depot NEUF (posterieur au debut de la veille) -> une ligne de METADONNEES, jamais le
texte externe, et fin ; anciens depots ignores ; base illisible DITE (jamais lue comme « rien ») ;
borne de duree.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(30)

RACINE = Path(__file__).resolve().parents[2]
SECRET_DU_PAIR = "TEXTE EXTERNE a ne jamais recopier"


def _cli():
    spec = importlib.util.spec_from_file_location("veille_pairs_nr", RACINE / "tools" / "forge_job_watch_cli.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def m2m(tmp_path):
    db = tmp_path / "m2m.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, "
              "correlation_id TEXT, method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.execute("INSERT INTO agent_messages VALUES ('pair_ancien', 'PAIR:client-a', 'OWNER_APPROBATION', 'x', "
              "'pair.envoyer_message', ?, 'quarantaine', '2026-10-01T10:00:00+00:00')",
              (json.dumps({"intent": "REVIEW_FINDING", "texte": SECRET_DU_PAIR}),))
    c.commit()
    c.close()
    return db


def _deposer(db, ident, de="PAIR:client-a", vers="OWNER_APPROBATION", quand="2026-10-01T18:00:00+00:00"):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO agent_messages VALUES (?, ?, ?, ?, 'pair.envoyer_message', ?, 'quarantaine', ?)",
              (ident, de, vers, ident, json.dumps({"intent": "REVIEW_FINDING", "texte": SECRET_DU_PAIR}), quand))
    c.commit()
    c.close()


class _Temps:
    def __init__(self):
        self.t = 0.0

    def horloge(self):
        return self.t

    def dormir(self, s):
        self.t += s


def test_un_depot_neuf_reveille_avec_ses_seules_metadonnees(m2m):
    cli, temps, lignes = _cli(), _Temps(), []

    def dormir(s):
        temps.dormir(s)
        if temps.t >= 20:
            _deposer(m2m, "pair_neuf")
            _deposer(m2m, "msg_interne", de="CLAUDE", vers="AGY")          # hors quarantaine : ignore

    rc = cli.surveiller_pair(None, max_s=600, intervalle=10, ecrire=lignes.append, m2m=str(m2m),
                             horloge=temps.horloge, dormir=dormir, depuis_iso="2026-10-01T12:00:00+00:00")
    assert rc == 0
    depots = [l for l in lignes if l.startswith("PAIR DEPOT")]
    assert len(depots) == 1 and "pair_neuf" in depots[0] and "intent=REVIEW_FINDING" in depots[0]
    assert not [l for l in lignes if SECRET_DU_PAIR in l], "le texte externe n'entre jamais dans la boucle"


def test_un_ancien_depot_ne_reveille_pas_et_la_borne_tient(m2m):
    cli, temps, lignes = _cli(), _Temps(), []
    rc = cli.surveiller_pair(None, max_s=60, intervalle=10, ecrire=lignes.append, m2m=str(m2m),
                             horloge=temps.horloge, dormir=temps.dormir, depuis_iso="2026-10-01T12:00:00+00:00")
    assert rc == 0 and not [l for l in lignes if l.startswith("PAIR DEPOT")]
    assert "veille terminee" in lignes[-1]


def test_une_base_illisible_est_dite(tmp_path):
    cli, temps, lignes = _cli(), _Temps(), []
    cli.surveiller_pair(None, max_s=30, intervalle=10, ecrire=lignes.append, m2m=str(tmp_path / "absente.db"),
                        horloge=temps.horloge, dormir=temps.dormir, depuis_iso="2026-10-01T12:00:00+00:00")
    assert [l for l in lignes if "ILLISIBLE" in l]


def _garde(commande: str) -> int:
    """Code de sortie du VRAI bash_guard pour un appel Monitor (0 = accepte, 2 = bloque)."""
    import subprocess
    import sys

    entree = json.dumps({"tool_name": "Monitor", "tool_input": {"command": commande}})
    r = subprocess.run([sys.executable, str(RACINE / "tools" / "bash_guard.py")], input=entree,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    return r.returncode


@pytest.mark.parametrize("suffixe, attendu", [
    ("--pair", 0),
    ("--pair --intervalle 30 --max-s 1750", 0),
    ("--pair 4c9e23fd-f336-4dfc-a2eb-2d6a04db093a --max-s 60", 0),
    ("--task job_abc_123 --gel-s 60", 0),
    ("--pair ../../secret", 2),                       # un chemin n'est pas un client
    ("--pair -x", 2),                                 # le client ne peut pas etre une option
    ("--pair a; whoami", 2),                          # pas de second ordre
])
def test_bash_guard_accepte_la_forme_pair_et_rien_d_autre(suffixe, attendu):
    cmd = '"%USERPROFILE%/miniforge3/python.exe" "%s" %s' % (RACINE / "tools" / "forge_job_watch_cli.py", suffixe)
    assert _garde(cmd) == attendu, cmd


def test_le_filtre_client_et_le_refus_de_motif(m2m):
    cli, temps, lignes = _cli(), _Temps(), []
    _deposer(m2m, "pair_autre", de="PAIR:client-b")
    _deposer(m2m, "pair_bon", de="PAIR:client-a")
    cli.surveiller_pair("client-a", max_s=30, intervalle=10, ecrire=lignes.append, m2m=str(m2m),
                        horloge=temps.horloge, dormir=temps.dormir, depuis_iso="2026-10-01T12:00:00+00:00")
    depots = [l for l in lignes if l.startswith("PAIR DEPOT")]
    assert len(depots) == 1 and "pair_bon" in depots[0]
    assert cli.main(["--pair", "a%b"]) == 2
