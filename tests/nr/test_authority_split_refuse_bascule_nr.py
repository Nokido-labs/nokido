"""NR — la bascule d'autorite refuse tant qu'un consommateur lit encore la base RAG.

`forge_authority_db_split --basculer` pose l'interrupteur qui fait vivre
`opsec_state` (kill-switch humain) et `forge_tools` (bareme d'autorisation)
hors de la base que le compte client ecrit. Basculer AVANT d'avoir redirige
`app/forge_opsec.py` et `app/forge_mcp_registry.py` donnerait un hub qui ECRIT
d'un cote et LIT de l'autre : le kill-switch paraitrait pose et ne protegerait
plus rien. C'est le defaut « un site bascule seul » que le corps a deja paye
sur la scission m2m.

Ce garde est la seule chose qui empeche ce scenario. Un garde sans NR se
retire sans que rien ne crie -- et un garde retire ne se voit pas en relecture.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_authority_db_split as split  # noqa: E402


def test_le_garde_existe_et_nomme_les_consommateurs():
    assert split.CONSOMMATEURS, "aucun consommateur declare : le garde ne peut rien verifier"
    for rel in split.CONSOMMATEURS:
        assert (ROOT / rel).exists(), f"consommateur declare mais introuvable : {rel}"


def test_bascule_refusee_tant_qu_un_consommateur_n_est_pas_redirige(monkeypatch):
    """Le refus doit etre NOMME : un refus muet se contourne par reessai."""
    monkeypatch.setattr(split, "_consommateurs_rediriges",
                        lambda: {"app/exemple.py": {"redirige": False, "motif": "test"}})
    r = split.basculer(appliquer=True)
    assert r["ok"] is False
    assert r["refus"] == "CONSOMMATEURS_NON_REDIRIGES"
    assert "app/exemple.py" in r["restants"]


def test_un_consommateur_illisible_compte_comme_NON_redirige(tmp_path, monkeypatch):
    """Fail-closed : « je n'ai pas pu lire » n'est jamais « c'est bon »."""
    monkeypatch.setattr(split, "CONSOMMATEURS", ("app/fichier_qui_n_existe_pas.py",))
    etat = split._consommateurs_rediriges()
    vu = etat["app/fichier_qui_n_existe_pas.py"]
    assert vu["redirige"] is False
    assert "ILLISIBLE" in vu["motif"], "un illisible doit se DIRE, pas se taire"


def test_bascule_refusee_si_la_copie_est_incomplete(monkeypatch):
    """Poser l'interrupteur sur une cible incomplete perdrait des lignes d'autorite."""
    monkeypatch.setattr(split, "_consommateurs_rediriges",
                        lambda: {"app/exemple.py": {"redirige": True, "motif": ""}})
    monkeypatch.setattr(split, "verifier",
                        lambda: {"identiques": False,
                                 "ecarts": [{"table": "opsec_state", "source": 3, "cible": 0}]})
    r = split.basculer(appliquer=True)
    assert r["ok"] is False
    assert r["refus"] == "COPIE_INCOMPLETE"


def test_la_copie_n_efface_jamais_la_source():
    """La source reste la reference tant que la bascule n'est pas faite."""
    src = Path(split.__file__).read_text(encoding="utf-8", errors="replace")
    for interdit in ("DROP TABLE IF EXISTS src.", "DELETE FROM src."):
        assert interdit not in src, f"la source peut etre altérée : {interdit}"


def test_nokido_tui_n_est_pas_compte_comme_consommateur():
    """`opsec_state()` y lit state.json, pas la table — homonyme, pas un site."""
    assert not any("nokido_tui" in c for c in split.CONSOMMATEURS), (
        "un homonyme a ete pris pour un consommateur : la bascule attendrait "
        "une redirection qui n'a aucun sens"
    )


def test_la_base_d_autorite_n_est_pas_en_wal():
    """En WAL, un compte en LECTURE SEULE ne peut pas ouvrir la base du tout.

    Mesure du 2026-09-13 : la premiere copie posait `PRAGMA journal_mode=WAL`
    par reflexe (c'est le bon choix pour la base RAG, cf.
    `forge_db_path.open_writer`). Or SQLite ecrit le fichier `-shm` MEME pour
    LIRE une base WAL : les comptes bac a sable, qui n'ont que `(R)`/`(RX)`,
    recevaient `unable to open database file` -- y compris en `mode=ro`. Le
    WAL sert la concurrence d'ECRITURE ; ici il y a un ecrivain et 28 lignes.
    """
    src = Path(split.__file__).read_text(encoding="utf-8", errors="replace")
    assert "journal_mode=WAL" not in src, (
        "WAL sur la base d'autorite : les comptes en lecture seule ne pourront "
        "plus la lire, ce qui annule la raison d'etre de la separation"
    )
    assert "journal_mode=DELETE" in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
