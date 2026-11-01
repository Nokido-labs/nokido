"""NR -- P1 levier 2 (GO owner 22/10) : la sortie de `run` est bornee A L'ENTREE pour les agents LLM.

Mesure P0 (22/10) : les resultats de `run` du hub pesent 11-17 % du cout de relecture d'une session ; les resultats
intermediaires des chaines d'outils, 22-24 %. Veille (token-optimizer-mcp v1-frontier, rtk tee) : on ne compresse
qu'a l'entree, jamais l'historique deja en cache, et tout retrait est REVERSIBLE (la sortie complete est deversee dans
un fichier dont le chemin est donne).

Audit des consommateurs (22/10) : des demons internes cherchent une chaine n'importe ou dans la sortie (en-tete
`timed_out=`, `PYTEST_RC: 0`) -- donc LISTE BLANCHE des agents LLM ; une identite inconnue recoit la sortie intacte.
Le fichier recoit la version CAVIARDEE (redact_tool_output) : sans caviardage, pas de deversement, la sortie est rendue.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_run_sortie as S  # noqa: E402

ENTETE = "[trusted_script tools/x.py exit=0 timed_out=False user=LaForgeTrusted]\n"
CORPS = "".join("ligne %05d chemin C:\\Users\\quelquun\\dossier\\fichier.txt\n" % i for i in range(2000))
LONG = ENTETE + CORPS + "== 3 failed, 9 passed ==\n"


def test_un_agent_llm_recoit_tete_fin_et_chemin(tmp_path):
    r = S.borner(LONG, "CLAUDE", {}, dossier=tmp_path)
    assert len(r) < len(LONG) // 4
    assert r.startswith("[trusted_script tools/x.py exit=0")          # l'en-tete reste lisible
    assert r.rstrip().endswith("== 3 failed, 9 passed ==")             # le bilan de fin aussi
    fichiers = list(tmp_path.glob("run_*.txt"))
    assert len(fichiers) == 1 and str(fichiers[0]) in r
    complet = fichiers[0].read_text(encoding="utf-8")
    assert "ligne 01000" in complet and "== 3 failed, 9 passed ==" in complet   # rien n'est perdu


def test_le_fichier_deverse_est_caviarde(tmp_path):
    S.borner(LONG, "CLAUDE", {}, dossier=tmp_path)
    complet = next(tmp_path.glob("run_*.txt")).read_text(encoding="utf-8")
    assert "C:\\Users\\quelquun" not in complet


def test_un_demon_interne_ou_une_identite_inconnue_recoit_tout(tmp_path):
    for agent in ("AUTONOMOUS_LOOPS", "", None, "ORCHESTRATE_LOOP"):
        assert S.borner(LONG, agent, {}, dossier=tmp_path) == LONG
    assert not list(tmp_path.glob("run_*.txt"))


def test_courte_sortie_ou_sortie_complete_demandee_intactes(tmp_path):
    assert S.borner("ok\n", "CLAUDE", {}, dossier=tmp_path) == "ok\n"
    assert S.borner(LONG, "CLAUDE", {"sortie_complete": True}, dossier=tmp_path) == LONG


def test_sans_caviardage_pas_de_deversement_la_sortie_est_rendue(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "_caviarder", lambda texte: None)
    assert S.borner(LONG, "CLAUDE", {}, dossier=tmp_path) == LONG
    assert not list(tmp_path.glob("run_*.txt"))


def test_les_surfaces_llm_connues_sont_dans_la_liste_blanche():
    for agent in ("CLAUDE", "agt_claude", "GEMINI", "CODEX", "VIBE", "OPENCODE_GLM", "ANTIGRAVITY"):
        assert S.est_agent_llm(agent), agent
    assert not S.est_agent_llm("AUTONOMOUS_LOOPS")


def test_handle_run_du_hub_passe_par_la_borne(tmp_path, monkeypatch):
    from nokido_agent.app import forge_mcp_registry as M
    cls = next(c for c in vars(M).values() if isinstance(c, type) and hasattr(c, "_handle_run_brut"))
    reg = object.__new__(cls)

    async def brut(self, args, agent, ring):
        return LONG
    monkeypatch.setattr(cls, "_handle_run_brut", brut)
    monkeypatch.setenv("LAFORGE_RUN_SORTIE_DIR", str(tmp_path))
    r = asyncio.run(reg.handle_run({"action": "shell"}, "CLAUDE", 1))
    assert len(r) < len(LONG) and list(tmp_path.glob("run_*.txt"))
    assert asyncio.run(reg.handle_run({"action": "shell"}, "AUTONOMOUS_LOOPS", 1)) == LONG
