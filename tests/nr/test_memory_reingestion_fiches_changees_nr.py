# -*- coding: utf-8 -*-
"""NR — Reingestion au demarrage des fiches memoire qui ont change.

Verifie :
1. fiche changee = reingeree ;
2. budget depasse = reste en file sandbox/memory_ingest_pending.json puis reprise a l'appel suivant ;
3. budget 0 = rien sauf MEMORY.md ;
4. ingerer en panne = rien de perdu, message rendu.
Par le chemin reel main() avec --auto, --memory-dir temporaire.
"""
import io
import json
import os
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.tools import forge_memory_compactor as compactor
from nokido_agent.tools import forge_memory_ledger as ml


@pytest.fixture(autouse=True)
def _ledger_reel_intouche(monkeypatch):
    """`--auto` appelle `prune()` sur la base par defaut : le NR n'y touche pas."""
    monkeypatch.setattr(ml, "prune", lambda *a, **k: None)


def _preparer_env(tmp_path: Path):
    mdir = tmp_path / "memory"
    mdir.mkdir(parents=True, exist_ok=True)
    mem = mdir / "MEMORY.md"
    mem.write_text("# Index\n\n- [[fiche1.md]] : test\n", encoding="utf-8")
    return mdir


def test_reingestion_fiche_changee(tmp_path: Path, monkeypatch):
    mdir = _preparer_env(tmp_path)
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    pending_file = sandbox_dir / "memory_ingest_pending.json"

    # Rediriger sandbox vers notre dossier temporaire
    monkeypatch.setattr(compactor, "_RACINE_AMORCE", str(tmp_path))

    ingerees = []

    def faux_ingerer(appliquer=True, fichier=""):
        ingerees.append(fichier)
        return 0

    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer", faux_ingerer)

    # Initialisation de base du ledger
    f1 = mdir / "fiche1.md"
    f1.write_text("---\nname: fiche1\n---\ncontenu v1\n", encoding="utf-8")
    r0 = ml.sync(mdir)
    assert "fiche1.md" in r0.get("changees", [])

    # Modifier la fiche1
    f1.write_text("---\nname: fiche1\n---\ncontenu v2 modifie\n", encoding="utf-8")

    out = io.StringIO()
    with patch("sys.argv", ["forge_memory_compactor.py", "--auto", "--memory-dir", str(mdir)]):
        with redirect_stdout(out):
            compactor.main()

    sortie = out.getvalue()
    assert "MEMORY.md" in ingerees
    assert "fiche1.md" in ingerees
    assert not pending_file.exists() or json.loads(pending_file.read_text(encoding="utf-8")) == []
    assert "[memory_ingest] fiches reingerees : 1 traitee(s), 0 en attente" in sortie


def test_budget_depasse_et_reprise_file(tmp_path: Path, monkeypatch):
    mdir = _preparer_env(tmp_path)
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    pending_file = sandbox_dir / "memory_ingest_pending.json"

    monkeypatch.setattr(compactor, "_RACINE_AMORCE", str(tmp_path))
    # Budget tres court : 0.05 s
    monkeypatch.setenv("LAFORGE_MEMORY_INGEST_BUDGET_S", "0.05")

    ingerees = []

    def faux_ingerer_lent(appliquer=True, fichier=""):
        ingerees.append(fichier)
        if fichier != "MEMORY.md":
            time.sleep(0.08)  # Depasse le budget de 0.05s des la premiere fiche
        return 0

    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer", faux_ingerer_lent)

    # Creer 3 fiches
    for i in range(1, 4):
        (mdir / f"fiche{i}.md").write_text(f"---\nname: fiche{i}\n---\ncontenu\n", encoding="utf-8")

    # Appel 1 : passe 1
    out = io.StringIO()
    with patch("sys.argv", ["forge_memory_compactor.py", "--auto", "--memory-dir", str(mdir)]):
        with redirect_stdout(out):
            compactor.main()

    # La premiere fiche a ete traitee, le budget est depasse, les 2 autres sont en attente
    assert pending_file.is_file()
    reste = json.loads(pending_file.read_text(encoding="utf-8"))
    assert len(reste) == 2
    assert "MEMORY.md" in ingerees

    # Appel 2 : reprise de la file
    # On donne un budget large cette fois
    monkeypatch.setenv("LAFORGE_MEMORY_INGEST_BUDGET_S", "5.0")
    ingerees.clear()

    def faux_ingerer_rapide(appliquer=True, fichier=""):
        ingerees.append(fichier)
        return 0

    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer", faux_ingerer_rapide)

    out2 = io.StringIO()
    with patch("sys.argv", ["forge_memory_compactor.py", "--auto", "--memory-dir", str(mdir)]):
        with redirect_stdout(out2):
            compactor.main()

    assert not pending_file.exists()
    assert reste[0] in ingerees
    assert reste[1] in ingerees


def test_budget_zero_aucun_traitement_fiches(tmp_path: Path, monkeypatch):
    mdir = _preparer_env(tmp_path)
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    pending_file = sandbox_dir / "memory_ingest_pending.json"

    monkeypatch.setattr(compactor, "_RACINE_AMORCE", str(tmp_path))
    monkeypatch.setenv("LAFORGE_MEMORY_INGEST_BUDGET_S", "0")

    ingerees = []

    def faux_ingerer(appliquer=True, fichier=""):
        ingerees.append(fichier)
        return 0

    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer", faux_ingerer)

    # Creer une fiche changee
    (mdir / "fiche_b0.md").write_text("---\nname: fiche_b0\n---\ncontenu\n", encoding="utf-8")

    out = io.StringIO()
    with patch("sys.argv", ["forge_memory_compactor.py", "--auto", "--memory-dir", str(mdir)]):
        with redirect_stdout(out):
            compactor.main()

    assert ingerees == ["MEMORY.md"]
    # La fiche reste dans la file d'attente persistante
    assert pending_file.is_file()
    reste = json.loads(pending_file.read_text(encoding="utf-8"))
    assert "fiche_b0.md" in reste


def test_ingerer_en_panne_rien_de_perdu(tmp_path: Path, monkeypatch):
    mdir = _preparer_env(tmp_path)
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(compactor, "_RACINE_AMORCE", str(tmp_path))

    def faux_ingerer_panne(appliquer=True, fichier=""):
        raise RuntimeError("Panne pipeline RAG")

    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer", faux_ingerer_panne)

    (mdir / "fiche_panne.md").write_text("---\nname: fiche_panne\n---\ncontenu\n", encoding="utf-8")

    out = io.StringIO()
    with patch("sys.argv", ["forge_memory_compactor.py", "--auto", "--memory-dir", str(mdir)]):
        with redirect_stdout(out):
            compactor.main()

    sortie = out.getvalue()
    assert "[memory_ingest] reingestion IMPOSSIBLE (RuntimeError: Panne pipeline RAG)" in sortie
    # Le ledger ne redira jamais cette fiche : elle doit etre en file.
    assert "fiche_panne.md" in json.loads((sandbox_dir / "memory_ingest_pending.json").read_text(encoding="utf-8"))


def _lancer(mdir):
    out = io.StringIO()
    with patch("sys.argv", ["forge_memory_compactor.py", "--auto", "--memory-dir", str(mdir)]):
        with redirect_stdout(out):
            compactor.main()
    return out.getvalue()


def test_un_refus_de_ingerer_garde_la_fiche_en_file(tmp_path: Path, monkeypatch):
    """`ingerer` rend 2 ou 3 sans lever : ce n'est pas un succes."""
    mdir = _preparer_env(tmp_path)
    monkeypatch.setattr(compactor, "_RACINE_AMORCE", str(tmp_path))
    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer",
                        lambda appliquer=True, fichier="": 0 if fichier == "MEMORY.md" else 3)
    (mdir / "fiche_refus.md").write_text("---\nname: r\n---\nx\n", encoding="utf-8")
    sortie = _lancer(mdir)
    assert "fiche_refus.md" in json.loads((tmp_path / "sandbox" / "memory_ingest_pending.json").read_text(encoding="utf-8"))
    assert "0 traitee(s)" in sortie


def test_la_file_est_ecrite_avant_toute_ingestion(tmp_path: Path, monkeypatch):
    """Hook tue a 8 s en pleine ingestion : la file doit deja etre sur le disque."""
    mdir = _preparer_env(tmp_path)
    monkeypatch.setattr(compactor, "_RACINE_AMORCE", str(tmp_path))
    pending = tmp_path / "sandbox" / "memory_ingest_pending.json"
    vu = {}

    def espion(appliquer=True, fichier=""):
        vu.setdefault(fichier, json.loads(pending.read_text(encoding="utf-8")) if pending.exists() else None)
        return 0

    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer", espion)
    (mdir / "fiche_tuee.md").write_text("---\nname: t\n---\nx\n", encoding="utf-8")
    _lancer(mdir)
    assert "fiche_tuee.md" in (vu["MEMORY.md"] or [])


def test_un_budget_illisible_ne_perd_rien(tmp_path: Path, monkeypatch):
    mdir = _preparer_env(tmp_path)
    monkeypatch.setattr(compactor, "_RACINE_AMORCE", str(tmp_path))
    monkeypatch.setenv("LAFORGE_MEMORY_INGEST_BUDGET_S", "pas_un_nombre")
    monkeypatch.setattr("nokido_agent.tools.forge_memory_ingest.ingerer", lambda appliquer=True, fichier="": 0)
    (mdir / "fiche_b.md").write_text("---\nname: b\n---\nx\n", encoding="utf-8")
    _lancer(mdir)
    assert "fiche_b.md" in json.loads((tmp_path / "sandbox" / "memory_ingest_pending.json").read_text(encoding="utf-8"))
