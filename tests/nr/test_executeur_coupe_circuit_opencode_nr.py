"""NR -- executeurs OpenCode : coupe-circuit fournisseur, veille ACP par taille/modele, taille M/L hors OpenCode.

Mesure 24/10 : ~8 taches OpenCode, 5 echecs -- GLM -32603 « service may be temporarily overloaded » x2, DEFAUT2/NEMOTRON/
DEFAUT5 « SilenceACP : silence de l'agent depuis 300 s », reaffectations en chaine d'OpenCode en OpenCode
(GPTOSS -> GLM -> GLM). Attendu :
- 2 pannes FOURNISSEUR en 30 min -> l'executeur est mis en REPOS (journalise), n'est plus choisi, et la reaffectation
  part HORS famille OpenCode (CLAUDE_HEADLESS puis MISTRAL) ; une panne isolee -> pas de repos ;
- veille ACP 300 s par defaut, 600 s pour une tache L ou un modele de raisonnement ;
- une tache M/L n'est pas confiee a OpenCode par defaut (forge_palier_effort.TABLE), sauf demande explicite."""
from __future__ import annotations

import importlib.util
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
T0 = time.time()
PANNE_GLM = "erreur ACP OpenCode (RuntimeError): -32603 service may be temporarily overloaded"
PANNE_SILENCE = "erreur ACP OpenCode (SilenceACP): silence de l'agent depuis 300 s"


def _m(monkeypatch, tmp_path):
    for v in ("LAFORGE_OPENCODE_SILENCE_S", "LAFORGE_OPENCODE_SILENCE_LONG_S", "LAFORGE_OPENCODE_REPOS_S"):
        monkeypatch.delenv(v, raising=False)
    spec = importlib.util.spec_from_file_location("coupe_circuit_nr", RACINE / "tools" / "forge_task_executor.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(tmp_path / "coupe_circuit.json"))
    monkeypatch.setattr(m, "_lire_registre", lambda: {})
    return m


def test_deux_pannes_fournisseur_en_30_min_mettent_en_repos_et_journalisent(monkeypatch, tmp_path, caplog):
    m = _m(monkeypatch, tmp_path)
    assert m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_GLM, maintenant=T0) is None
    with caplog.at_level(logging.WARNING, logger="TaskExecutor"):
        motif = m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_SILENCE, maintenant=T0 + 600)
    assert motif and "REPOS" in motif.upper()
    assert m.executeur_en_repos("OPENCODE_GLM", maintenant=T0 + 700)
    assert any("REPOS" in r.getMessage().upper() and "OPENCODE_GLM" in r.getMessage() for r in caplog.records)
    # plus choisi : ni par la reaffectation (suspendu) ni par defaut (capacite refusee)
    assert m._executeur_suspendu("OPENCODE_GLM")
    ok, pq = m._peut_lancer_opencode("OPENCODE_GLM")
    assert ok is False and "repos" in pq.lower()


def test_panne_isolee_ou_espacee_pas_de_repos(monkeypatch, tmp_path):
    m = _m(monkeypatch, tmp_path)
    m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_GLM, maintenant=T0)
    assert not m.executeur_en_repos("OPENCODE_GLM", maintenant=T0 + 60)
    # deuxieme panne HORS fenetre de 30 min : toujours pas de repos
    assert m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_GLM, maintenant=T0 + 1801) is None
    assert not m.executeur_en_repos("OPENCODE_GLM", maintenant=T0 + 1802)
    # un echec de TRAVAIL n'est pas une panne fournisseur
    assert not m._est_panne_fournisseur("2 failed, NR rouges : AssertionError")
    assert m._est_panne_fournisseur(PANNE_GLM) and m._est_panne_fournisseur(PANNE_SILENCE)
    assert m._est_panne_fournisseur("Error: Client error '429 Too Many Requests'")


def test_repos_expire(monkeypatch, tmp_path):
    m = _m(monkeypatch, tmp_path)
    m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_GLM, maintenant=T0)
    m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_GLM, maintenant=T0 + 10)
    assert m.executeur_en_repos("OPENCODE_GLM", maintenant=T0 + 20)
    assert not m.executeur_en_repos("OPENCODE_GLM", maintenant=T0 + 10 + 3 * 3600)


def _base_taches(m, monkeypatch, tmp_path, agent):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, classe TEXT)")
    c.execute("INSERT INTO tasks VALUES ('job_cc', ?, 'running', '[opencode] tache S', 'S:ecrit')", (agent,))
    c.commit()
    c.close()
    monkeypatch.setattr(m, "TASKS_DB", db)
    monkeypatch.setattr(m, "_executeur_bat", lambda a, max_age_s=None: True)
    return db


def test_repos_reaffecte_hors_famille_opencode(monkeypatch, tmp_path):
    m = _m(monkeypatch, tmp_path)
    db = _base_taches(m, monkeypatch, tmp_path, "OPENCODE_GPTOSS")
    m.enregistrer_panne_fournisseur("OPENCODE_GPTOSS", PANNE_GLM)
    m.enregistrer_panne_fournisseur("OPENCODE_GPTOSS", PANNE_SILENCE)
    task = {"id": "job_cc", "agent": "OPENCODE_GPTOSS", "description": "[opencode] tache S"}
    # meme si l'appelant passe un ordre 100 % OpenCode, l'executeur en repos sort de la famille
    vers = m._reaffecter(task, "PANNE FOURNISSEUR : -32603", ordre=m._OPENCODE_ECRITURE)
    assert vers in ("CLAUDE_HEADLESS", "MISTRAL"), vers
    row = sqlite3.connect(str(db)).execute("SELECT agent, reaffectations FROM tasks WHERE id='job_cc'").fetchone()
    assert row[0] == vers and json.loads(row[1])[-1]["de"] == "OPENCODE_GPTOSS"


def test_une_cible_en_repos_n_est_jamais_choisie(monkeypatch, tmp_path):
    """24/10 : la protection ne regardait que la SOURCE ; la CIBLE en repos restait choisie -- 5 taches entonnees sur
    OPENCODE_GLM (fournisseur en surcharge) dans la journee, 1 seule livraison partielle."""
    m = _m(monkeypatch, tmp_path)
    # ce test porte sur le REPOS, pas sur la gratuite : le drapeau reel « repli gratuit seul » (29/10) ecartait
    # CLAUDE_HEADLESS et rendait le test dependant de l'environnement (rouge depuis le 29/10)
    monkeypatch.setattr(m, "_repli_gratuit_seul", lambda: False)
    db = _base_taches(m, monkeypatch, tmp_path, "CODEX")
    m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_GLM)
    m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_SILENCE)
    task = {"id": "job_cc", "agent": "CODEX", "description": "[opencode] tache S"}
    vers = m._reaffecter(task, "quota", ordre=("OPENCODE_GLM", "CLAUDE_HEADLESS"))
    assert vers == "CLAUDE_HEADLESS", vers
    assert sqlite3.connect(str(db)).execute("SELECT agent FROM tasks WHERE id='job_cc'").fetchone()[0] == vers


def test_si_toutes_les_cibles_sont_en_repos_la_tache_reste(monkeypatch, tmp_path):
    m = _m(monkeypatch, tmp_path)
    db = _base_taches(m, monkeypatch, tmp_path, "CODEX")
    m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_GLM)
    m.enregistrer_panne_fournisseur("OPENCODE_GLM", PANNE_SILENCE)
    task = {"id": "job_cc", "agent": "CODEX", "description": "[opencode] tache S"}
    assert m._reaffecter(task, "quota", ordre=("OPENCODE_GLM",)) is None
    assert sqlite3.connect(str(db)).execute("SELECT agent FROM tasks WHERE id='job_cc'").fetchone()[0] == "CODEX"


def test_panne_isolee_reaffectation_inchangee(monkeypatch, tmp_path):
    m = _m(monkeypatch, tmp_path)
    _base_taches(m, monkeypatch, tmp_path, "OPENCODE_GPTOSS")
    m.enregistrer_panne_fournisseur("OPENCODE_GPTOSS", PANNE_GLM)
    task = {"id": "job_cc", "agent": "OPENCODE_GPTOSS", "description": "[opencode] tache S"}
    vers = m._reaffecter(task, "PANNE FOURNISSEUR : -32603", ordre=("OPENCODE_GLM",))
    assert vers == "OPENCODE_GLM"


def test_veille_acp_par_taille_et_modele(monkeypatch, tmp_path):
    m = _m(monkeypatch, tmp_path)
    assert m._silence_acp_s("S", "zai/glm-4.7-flash", {}) == 300
    assert m._silence_acp_s(None, "", {}) == 300
    assert m._silence_acp_s("M", "", {}) == 300
    assert m._silence_acp_s("L", "", {}) == 600
    assert m._silence_acp_s("M", "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", {}) == 600
    assert m._silence_acp_s("S", "x/y", {"raisonnement": True}) == 600
    # l'executeur arme bien la veille rallongee (base + rallonge)
    assert m.OPENCODE_SILENCE_S + m._rallonge_veille_s("L", "", {}) == 600
    assert m.OPENCODE_SILENCE_S + m._rallonge_veille_s("M", "", {}) == 300
    src = (RACINE / "tools" / "forge_task_executor.py").read_text(encoding="utf-8")
    assert "client.silence_max = OPENCODE_SILENCE_S + _rallonge_veille_s(" in src


def test_taille_M_ou_L_sans_demande_explicite_pas_opencode(monkeypatch, tmp_path):
    m = _m(monkeypatch, tmp_path)
    for t in ("M", "L"):
        ordre = m._palier_par_defaut(t, ecrit=True)
        assert ordre and not any(a.startswith("OPENCODE") for a in ordre), (t, ordre)
        assert ordre[0] == "CLAUDE_HEADLESS"
        assert any(a.startswith("OPENCODE") for a in m._palier_par_defaut(t, ecrit=True, explicite=True))
    assert any(a.startswith("OPENCODE") for a in m._palier_par_defaut("S", ecrit=True))
    # depuis la consigne : taille declaree ou M par defaut ; [opencode] = demande explicite
    assert not any(a.startswith("OPENCODE") for a in m._ordre_repli_pour("corrige x. taille: M"))
    assert not any(a.startswith("OPENCODE") for a in m._ordre_repli_pour("corrige x sans taille"))
    assert any(a.startswith("OPENCODE") for a in m._ordre_repli_pour("[opencode] corrige x. taille: M"))
    assert any(a.startswith("OPENCODE") for a in m._ordre_repli_pour("corrige x. taille: S"))
