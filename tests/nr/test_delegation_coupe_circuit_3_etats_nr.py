# -*- coding: utf-8 -*-
"""NR -- delegation sans ping-pong : coupe-circuit 3 etats par executeur + refus / avertissement a l'assignation.

Patron OmniRoute, plan S3 (docs/enquetes/omniroute_free_tier_quota_effort_20261030.md §4-5).
Symptome mesure (1/11 10 h 27-10 h 35, sandbox/tasks.db) : 6 taches assignees a OPENCODE_NEMOTRON /
OPENCODE_GPTOSS / OPENCODE_DEFAUT2/3 passent running puis sont reaffectees en ~30 s, parfois vers un
executeur lui aussi epuise (NEMOTRON -> GPTOSS -> GLM), et tout finit serialise sur OPENCODE_GLM.

Exigences :
1. A l'assignation (`task assign`, via `_avertissement_agent` ou son appelant) : si `_opencode_hors_quota(agent)`
   ou le coupe-circuit dit OPEN, la reponse le DIT (motif + executeur eligible propose) au lieu d'accepter en silence.
   Ne PAS refuser un agent dont l'etat est illisible (UNKNOWN != NO).
2. Coupe-circuit par executeur, 3 etats CLOSED / OPEN / HALF_OPEN :
   - OPEN apres N=2 sorties « vide » ou reaffectations consecutives de cet executeur (ou pannes fournisseur) ;
   - cooldown 15 min (900s) ;
   - HALF_OPEN = une seule tache d'essai ; succes -> CLOSED.
   - Etat persiste dans un fichier sous sandbox/ (pas en memoire seule : plusieurs processus).
   - `_reaffecter` ne choisit JAMAIS une cible OPEN.
3. NR specifiques :
   (a) assignation a un executeur OPEN ou hors quota -> motif rendu + proposition d'eligible ;
   (b) 2 echecs consécutifs -> OPEN, 4e appel saute ;
   (c) cooldown ecoule -> HALF_OPEN -> succes -> CLOSED ;
   (d) reaffectation ne vise pas un OPEN ;
   (e) etat illisible -> pas de refus (UNKNOWN != NO).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as T  # noqa: E402
from app.forge_mcp_registry import ToolRegistry  # noqa: E402

# Reference RELATIVE a l'horloge : `_reaffecter` et l'avertissement d'assignation lisent time.time() ; une reference
# figee (1793530000, 1/11 11 h 46) faisait passer ces NR 15 min puis les rendait rouges (relecture 1/11, rejeu 12 h 13).
T0 = time.time()


def test_nr_b_deux_echecs_menent_a_open_et_quatrieme_appel_saute(tmp_path, monkeypatch):
    """(b) 2 echecs / sorties vide consecutives -> OPEN, 4e appel saute."""
    f_cc = tmp_path / "coupe_circuit.json"
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(f_cc))

    # Au depart, CLOSED
    assert T.statut_coupe_circuit("OPENCODE_NEMOTRON", maintenant=T0) == ("CLOSED", None)

    # 1er echec
    motif1 = T.enregistrer_echec_executeur("OPENCODE_NEMOTRON", "sortie vide", maintenant=T0)
    assert motif1 is None
    etat, _ = T.statut_coupe_circuit("OPENCODE_NEMOTRON", maintenant=T0 + 1)
    assert etat == "CLOSED"

    # 2e echec consecutif -> bascule en OPEN
    motif2 = T.enregistrer_echec_executeur("OPENCODE_NEMOTRON", "sortie vide", maintenant=T0 + 10)
    assert motif2 is not None
    assert "OPEN" in motif2 or "coupe-circuit" in motif2.lower()

    # Verifie statut OPEN
    etat, motif_open = T.statut_coupe_circuit("OPENCODE_NEMOTRON", maintenant=T0 + 15)
    assert etat == "OPEN"
    assert motif_open is not None

    # L'executeur est suspendu et ne peut plus etre lance
    assert T._executeur_suspendu("OPENCODE_NEMOTRON", maintenant=T0 + 15)
    peut, raison = T._peut_lancer_opencode("OPENCODE_NEMOTRON")
    assert not peut

    # 3e et 4e appels pendant OPEN sont sautes sans nouvel enregistrement d'echec
    assert T.statut_coupe_circuit("OPENCODE_NEMOTRON", maintenant=T0 + 30)[0] == "OPEN"
    assert T.statut_coupe_circuit("OPENCODE_NEMOTRON", maintenant=T0 + 50)[0] == "OPEN"


def test_nr_c_cooldown_ecoule_half_open_essai_succes_closed(tmp_path, monkeypatch):
    """(c) Cooldown 15 min (900s) ecoule -> HALF_OPEN -> succes -> CLOSED."""
    f_cc = tmp_path / "coupe_circuit.json"
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(f_cc))

    # Mettre en OPEN
    T.enregistrer_echec_executeur("OPENCODE_GPTOSS", "reaffectation", maintenant=T0)
    T.enregistrer_echec_executeur("OPENCODE_GPTOSS", "reaffectation", maintenant=T0 + 5)
    assert T.statut_coupe_circuit("OPENCODE_GPTOSS", maintenant=T0 + 10)[0] == "OPEN"

    # Pendant les 15 min (< 900s depuis le dernier echec a T0+5), toujours OPEN
    assert T.statut_coupe_circuit("OPENCODE_GPTOSS", maintenant=T0 + 890)[0] == "OPEN"

    # Apres 15 min ecoulees (>= 905s), passe en HALF_OPEN
    etat, motif = T.statut_coupe_circuit("OPENCODE_GPTOSS", maintenant=T0 + 910)
    assert etat == "HALF_OPEN"

    # En HALF_OPEN, une premiere tache d'essai est permise
    permis, _ = T.autoriser_essai_half_open("OPENCODE_GPTOSS", maintenant=T0 + 911)
    assert permis is True

    # Une deuxieme tentative concurrente en vol pendant l'essai est refusee
    permis2, raison2 = T.autoriser_essai_half_open("OPENCODE_GPTOSS", maintenant=T0 + 912)
    assert permis2 is False
    assert "essai en cours" in raison2.lower() or "half_open" in raison2.lower()

    # Enregistrement du succes -> CLOSED
    T.enregistrer_succes_executeur("OPENCODE_GPTOSS")
    assert T.statut_coupe_circuit("OPENCODE_GPTOSS", maintenant=T0 + 920) == ("CLOSED", None)
    # L'essai n'est plus verrouille
    p, _ = T.autoriser_essai_half_open("OPENCODE_GPTOSS", maintenant=T0 + 921)
    assert p is True


def test_nr_d_reaffectation_ne_vise_pas_un_open(tmp_path, monkeypatch):
    """(d) _reaffecter ne choisit JAMAIS une cible OPEN."""
    f_cc = tmp_path / "coupe_circuit.json"
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(f_cc))

    # Initialise base tasks
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, classe TEXT)")
    c.execute("INSERT INTO tasks VALUES ('job_nr_d', 'OPENCODE_DEFAUT2', 'running', '[opencode] tache M', 'M:ecrit')")
    c.commit()
    c.close()

    monkeypatch.setattr(T, "TASKS_DB", db)
    monkeypatch.setattr(T, "_executeur_bat", lambda a, max_age_s=None: True)
    monkeypatch.setattr(T, "_repli_gratuit_seul", lambda: False)

    # Mettre OPENCODE_GLM en OPEN
    T.enregistrer_echec_executeur("OPENCODE_GLM", "sortie vide", maintenant=T0)
    T.enregistrer_echec_executeur("OPENCODE_GLM", "sortie vide", maintenant=T0 + 5)
    assert T.statut_coupe_circuit("OPENCODE_GLM", maintenant=T0 + 10)[0] == "OPEN"

    task = {"id": "job_nr_d", "agent": "OPENCODE_DEFAUT2", "description": "[opencode] tache M"}
    # Ordre repli propose OPENCODE_GLM puis CLAUDE_HEADLESS
    vers = T._reaffecter(task, "echec sans livraison", ordre=("OPENCODE_GLM", "CLAUDE_HEADLESS"))
    # Doit sauter OPENCODE_GLM et choisir CLAUDE_HEADLESS
    assert vers == "CLAUDE_HEADLESS"

    # Si toutes les cibles sont OPEN ou indisponibles, ne reaffecte pas vers un OPEN
    T.enregistrer_echec_executeur("CLAUDE_HEADLESS", "panne", maintenant=T0)
    T.enregistrer_echec_executeur("CLAUDE_HEADLESS", "panne", maintenant=T0 + 5)
    task2 = {"id": "job_nr_d", "agent": "OPENCODE_DEFAUT2", "description": "[opencode] tache M"}
    vers2 = T._reaffecter(task2, "echec sans livraison", ordre=("OPENCODE_GLM", "CLAUDE_HEADLESS"))
    assert vers2 is None


def test_nr_a_assignation_executeur_open_ou_hors_quota_avertit_et_propose(tmp_path, monkeypatch):
    """(a) assignation a un executeur OPEN ou hors quota -> avertissement rendu + proposition d'eligible."""
    f_cc = tmp_path / "coupe_circuit.json"
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(f_cc))

    # Mettre OPENCODE_NEMOTRON en OPEN
    T.enregistrer_echec_executeur("OPENCODE_NEMOTRON", "2 reaffectations consecutives", maintenant=T0)
    T.enregistrer_echec_executeur("OPENCODE_NEMOTRON", "2 reaffectations consecutives", maintenant=T0 + 1)

    # Configurer services.toml
    d = tmp_path / "proxy_deno" / "core"
    d.mkdir(parents=True)
    toml = '''
    [[services]]
    name = "A"
    args = ["x.py", "--agent", "OPENCODE_NEMOTRON"]
    [[services]]
    name = "B"
    args = ["x.py", "--agent", "OPENCODE_GLM"]
    '''
    (d / "services.toml").write_text(toml, encoding="utf-8")

    reg = ToolRegistry(root_dir=tmp_path)

    # 1. Agent en OPEN
    avert_open = reg._avertissement_agent("OPENCODE_NEMOTRON")
    assert avert_open is not None
    assert "OPENCODE_NEMOTRON" in avert_open
    assert "coupe-circuit" in avert_open.lower() or "open" in avert_open.lower() or "repos" in avert_open.lower()
    # Doit proposer un remplacant eligible (ex OPENCODE_GLM)
    assert "OPENCODE_GLM" in avert_open

    # 2. Agent hors quota via _opencode_hors_quota
    monkeypatch.setattr(T, "_opencode_hors_quota", lambda ag: "TPD epuise" if ag == "OPENCODE_GLM" else None)
    avert_quota = reg._avertissement_agent("OPENCODE_GLM")
    assert avert_quota is not None
    assert "OPENCODE_GLM" in avert_quota
    assert "quota" in avert_quota.lower() or "tpd" in avert_quota.lower()


def test_nr_e_etat_illisible_ne_refuse_pas(tmp_path, monkeypatch):
    """(e) etat illisible -> pas de refus (UNKNOWN != NO)."""
    # Coupe circuit pointant sur un fichier corrompu
    f_bad = tmp_path / "corrompu.json"
    f_bad.write_text("{ ce json n'est pas valide ...", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(f_bad))

    etat, motif = T.statut_coupe_circuit("OPENCODE_GLM")
    assert etat == "CLOSED"
    assert motif is None

    # services.toml absent / registry sans donnees
    reg = ToolRegistry(root_dir=tmp_path / "introuvable")
    # Ne doit pas lever et ne doit rien refuser ni avertir
    assert reg._avertissement_agent("OPENCODE_GLM") is None


def test_nr_statut_coupe_circuit_lecture_pure_sans_ecriture(tmp_path, monkeypatch):
    """statut_coupe_circuit calcule HALF_OPEN sans ecrire sur disque."""
    f_cc = tmp_path / "coupe_circuit.json"
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(f_cc))

    # Mettre en OPEN
    T.enregistrer_echec_executeur("OPENCODE_DEFAUT3", "reaffectation", maintenant=T0)
    T.enregistrer_echec_executeur("OPENCODE_DEFAUT3", "reaffectation", maintenant=T0 + 5)
    contenu_open = f_cc.read_text(encoding="utf-8")

    # Lecture apres cooldown -> HALF_OPEN calcule
    st, motif = T.statut_coupe_circuit("OPENCODE_DEFAUT3", maintenant=T0 + 950)
    assert st == "HALF_OPEN"
    # Le fichier sur disque ne doit PAS avoir ete modifie par la simple lecture
    assert f_cc.read_text(encoding="utf-8") == contenu_open

    # L'ecriture effective de transition intervient lors de autoriser_essai_half_open
    permis, _ = T.autoriser_essai_half_open("OPENCODE_DEFAUT3", maintenant=T0 + 951)
    assert permis is True
    assert f_cc.read_text(encoding="utf-8") != contenu_open


def test_nr_half_open_une_seule_tache_en_reaffectation(tmp_path, monkeypatch):
    """En HALF_OPEN, autoriser_essai_half_open ne laisse passer qu'une seule reaffectation/delegation."""
    f_cc = tmp_path / "coupe_circuit.json"
    monkeypatch.setenv("LAFORGE_OPENCODE_COUPE_CIRCUIT_FILE", str(f_cc))

    # Initialise base tasks avec deux taches
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(str(db))
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, classe TEXT)")
    c.execute("INSERT INTO tasks VALUES ('job_1', 'OPENCODE_DEFAUT2', 'running', '[opencode] t1', 'M:ecrit')")
    c.execute("INSERT INTO tasks VALUES ('job_2', 'OPENCODE_DEFAUT2', 'running', '[opencode] t2', 'M:ecrit')")
    c.commit()
    c.close()

    monkeypatch.setattr(T, "TASKS_DB", db)
    monkeypatch.setattr(T, "_executeur_bat", lambda a, max_age_s=None: True)
    monkeypatch.setattr(T, "_repli_gratuit_seul", lambda: False)

    # Mettre OPENCODE_GLM en OPEN dans le passe pour que le cooldown soit ecoule a l'instant present
    t_passe = time.time() - 1000.0
    T.enregistrer_echec_executeur("OPENCODE_GLM", "sortie vide", maintenant=t_passe)
    T.enregistrer_echec_executeur("OPENCODE_GLM", "sortie vide", maintenant=t_passe + 5)
    # Cooldown ecoule : statut_coupe_circuit le voit HALF_OPEN
    assert T.statut_coupe_circuit("OPENCODE_GLM")[0] == "HALF_OPEN"

    # Premiere reaffectation : OPENCODE_GLM en HALF_OPEN autorise l'essai unique
    t1 = {"id": "job_1", "agent": "OPENCODE_DEFAUT2", "description": "[opencode] t1"}
    vers1 = T._reaffecter(t1, "echec", ordre=("OPENCODE_GLM", "CLAUDE_HEADLESS"))
    assert vers1 == "OPENCODE_GLM"

    # Deuxieme reaffectation concurrente : l'essai etant actif en HALF_OPEN, OPENCODE_GLM est saute
    t2 = {"id": "job_2", "agent": "OPENCODE_DEFAUT2", "description": "[opencode] t2"}
    vers2 = T._reaffecter(t2, "echec", ordre=("OPENCODE_GLM", "CLAUDE_HEADLESS"))
    assert vers2 == "CLAUDE_HEADLESS"

