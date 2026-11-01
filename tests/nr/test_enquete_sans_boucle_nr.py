# -*- coding: utf-8 -*-
"""
tests/nr/test_enquete_sans_boucle_nr.py — NR pour forge_enquete_sans_boucle.

Vérifie :
1. Dossier borné à 60 000 caractères et écart DIT (sources et caractères).
2. Requête FTS sans MATCH interdite.
3. redact_text appelée avant l'envoi au modèle.
4. Un seul appel au fournisseur.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

try:
    from nokido_agent.tools import forge_enquete_sans_boucle as fesb
except ImportError:
    import forge_enquete_sans_boucle as fesb



@pytest.fixture
def fts_db_factice(tmp_path):
    """Crée une base SQLite temporaire avec la table FTS rag_chunks_fts."""
    db_file = tmp_path / "test_embeddings.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute(
        "CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(source, text);"
    )
    # Remplir quelques documents
    cur.execute(
        "INSERT INTO rag_chunks_fts(source, text) VALUES (?, ?)",
        ("doc_alpha.md", "alpha contenu technique pour tester le MATCH"),
    )
    cur.execute(
        "INSERT INTO rag_chunks_fts(source, text) VALUES (?, ?)",
        ("doc_beta.md", "beta autre document sans le mot clef"),
    )
    conn.commit()
    yield conn
    conn.close()


def test_requete_sans_match_impossible(fts_db_factice):
    """Vérifie qu'une requête FTS sans MATCH ou avec terme vide est rejetée immédiatement."""
    with pytest.raises(ValueError, match="sans MATCH interdite"):
        fesb.interroger_fts(fts_db_factice, "")

    with pytest.raises(ValueError, match="sans MATCH interdite"):
        fesb.interroger_fts(fts_db_factice, "   ")

    # Requête valide avec MATCH
    res = fesb.interroger_fts(fts_db_factice, "alpha")
    assert len(res) == 1
    assert res[0][0] == "doc_alpha.md"


def test_dossier_borne_et_ecart_dit(tmp_path):
    """Vérifie que le dossier est borné et que les fragments dépassant le cap sont écartés et explicitement dits."""
    f1 = tmp_path / "mod1.py"
    f1.write_text("def f1():\n    return 'x' * 100\n", encoding="utf-8")
    f2 = tmp_path / "mod2.py"
    f2.write_text("def f2():\n    return 'y' * 100\n", encoding="utf-8")

    # cap = taille du 1er fragment SEUL (l'en-tete porte le chemin, dont la longueur depend du compte qui lance le
    # test : un cap fixe a 120 ecartait 1 fragment sur le poste, 2 dans le bac -- mesure 30/10)
    seul, _ = fesb.assembler_dossier(fts_termes=[], fonctions=[f"{f1}::f1"], db_conn=None, cap_max=10 ** 6)
    fonctions = [f"{f1}::f1", f"{f2}::f2"]
    dossier, ecartes = fesb.assembler_dossier(
        fts_termes=[],
        fonctions=fonctions,
        db_conn=None,
        cap_max=len(seul),
    )

    assert len(dossier) <= len(seul)
    assert len(ecartes) == 1
    assert ecartes[0]["source"] == f"AST:{f2}::f2"
    assert ecartes[0]["taille_caracteres"] > 0


def test_redaction_appelee_et_un_seul_appel_fournisseur(tmp_path):
    """Vérifie que redact_text est exécutée avant l'appel et qu'un seul appel fournisseur a lieu."""
    sortie = tmp_path / "rapport.md"

    f1 = tmp_path / "secret_mod.py"
    # Contient un secret potentiel
    f1.write_text("def reveal_secret():\n    return 'CLE_SECRETE_TEST'\n", encoding="utf-8")

    nb_appels = 0
    prompts_recus = []

    def faux_caller(fournisseur, message):
        nonlocal nb_appels
        nb_appels += 1
        prompts_recus.append(message)
        return True, "Analyse technique effectuée avec succès.", {"model": "groq/test", "tokens": 42}

    # Injecter forge_semantic_firewall si necessaire
    import sys
    try:
        import forge_semantic_firewall
    except ImportError:
        try:
            from nokido_agent.app import forge_semantic_firewall
            sys.modules["forge_semantic_firewall"] = forge_semantic_firewall
        except ImportError:
            pass

    with patch("forge_semantic_firewall.redact_text", create=True) as mock_redact:
        mock_redact.side_effect = lambda txt, **kw: (txt.replace("CLE_SECRETE_TEST", "[REDACTED_KEY]"), {})

        res = fesb.executer_enquete(
            question="Quelle est la clef ?",
            fts_termes=[],
            fonctions=[f"{f1}::reveal_secret"],
            sortie_fichier=str(sortie),
            fournisseur="groq",
            caller_fn=faux_caller,
        )

        assert mock_redact.called, "redact_text doit obligatoirement être appelée avant l'envoi"

    assert nb_appels == 1, "Un SEUL appel au fournisseur doit être effectué (patron agentless)"
    assert res["ok"] is True
    assert sortie.exists()

    contenu = sortie.read_text(encoding="utf-8")
    assert "Analyse technique effectuée avec succès." in contenu
    assert "**Fournisseur** : groq" in contenu
    assert "**Modèle** : groq/test" in contenu
    assert "**Tokens** : 42" in contenu
