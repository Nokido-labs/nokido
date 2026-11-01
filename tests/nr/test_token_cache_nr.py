"""
tests/nr/test_token_cache_nr.py - Tests de non-régression pour app/forge_token_cache.py

Vérifie :
1. Mode PLEIN sans etag (opt-in strict)
2. Mode INCHANGE avec le bon etag
3. Etag périmé -> PLEIN ou DIFF
4. DIFF plus petit que le contenu
5. Gros diff (> 50%) -> repli sur PLEIN
6. Isolation : même chemin, deux racines différentes -> pas d'INCHANGE croisé
7. 6e version -> la plus ancienne est retirée (max 5 versions)
"""

import json
import time
from pathlib import Path
import pytest

from app.forge_token_cache import (
    etag,
    lecture_conditionnelle,
    _calculer_cle_fichier,
)


@pytest.fixture(autouse=True)
def configure_cache_dir(tmp_path, monkeypatch):
    cache_dir = tmp_path / "sandbox_token_cache"
    monkeypatch.setenv("LAFORGE_TOKEN_CACHE_DIR", str(cache_dir))
    return cache_dir


def test_plein_sans_etag():
    contenu = "Ligne 1\nLigne 2\nLigne 3\n" * 10
    chemin = "C:/fake/repo/app/module.py"
    racine = "C:/fake/repo"

    res = lecture_conditionnelle(chemin, contenu, racine)
    assert res["mode"] == "PLEIN"
    assert res["etag"] == etag(contenu)
    assert res["corps"] == contenu
    assert res["tokens_evites"] == 0


def test_inchange_avec_bon_etag(configure_cache_dir):
    contenu = "Ligne 1\nLigne 2\nLigne 3\n" * 50
    tag = etag(contenu)
    chemin = "C:/fake/repo/app/module.py"
    racine = "C:/fake/repo"

    res = lecture_conditionnelle(chemin, contenu, racine, si_etag=tag)
    assert res["mode"] == "INCHANGE"
    assert res["etag"] == tag
    assert res["corps"] == f"[INCHANGE etag={tag}]"
    assert res["tokens_evites"] > 0

    journal = configure_cache_dir / "token_savings.jsonl"
    assert journal.is_file()
    lignes = journal.read_text(encoding="utf-8").strip().splitlines()
    assert len(lignes) == 1
    entree = json.loads(lignes[0])
    assert entree["mode"] == "INCHANGE"
    assert entree["tokens_evites"] == res["tokens_evites"]
    assert "app/module.py" in entree["chemin"]


def test_etag_perime_sans_depuis_donne_plein():
    contenu_initial = "Version 1\n" * 20
    tag_initial = etag(contenu_initial)

    contenu_modifie = "Version 2\n" * 20
    chemin = "C:/fake/repo/app/module.py"
    racine = "C:/fake/repo"

    res = lecture_conditionnelle(chemin, contenu_modifie, racine, si_etag=tag_initial)
    assert res["mode"] == "PLEIN"
    assert res["etag"] == etag(contenu_modifie)
    assert res["corps"] == contenu_modifie
    assert res["tokens_evites"] == 0


def test_diff_plus_petit_que_contenu():
    chemin = "C:/fake/repo/app/module.py"
    racine = "C:/fake/repo"

    base_lignes = [f"constante_val_{i} = {i}\n" for i in range(100)]
    contenu_v1 = "".join(base_lignes)
    tag_v1 = etag(contenu_v1)

    # 1. Enregistrer V1 dans les instantanés
    lecture_conditionnelle(chemin, contenu_v1, racine)

    # 2. V2 modifie une seule ligne au milieu
    base_lignes[50] = "constante_val_50 = 99999\n"
    contenu_v2 = "".join(base_lignes)
    tag_v2 = etag(contenu_v2)

    res = lecture_conditionnelle(
        chemin,
        contenu_v2,
        racine,
        si_etag=tag_v1,
        depuis_etag=tag_v1,
    )

    assert res["mode"] == "DIFF"
    assert res["etag"] == tag_v2
    assert "@@" in res["corps"]
    assert len(res["corps"]) <= 0.5 * len(contenu_v2)
    assert res["tokens_evites"] > 0


def test_gros_diff_repli_sur_plein():
    chemin = "C:/fake/repo/app/module.py"
    racine = "C:/fake/repo"

    contenu_v1 = "AAA\n" * 50
    tag_v1 = etag(contenu_v1)
    lecture_conditionnelle(chemin, contenu_v1, racine)

    # Contenu complètement différent : le diff unifié dépassera 50% de la taille
    contenu_v2 = "ZZZ\n" * 50
    tag_v2 = etag(contenu_v2)

    res = lecture_conditionnelle(
        chemin,
        contenu_v2,
        racine,
        depuis_etag=tag_v1,
    )

    assert res["mode"] == "PLEIN"
    assert res["etag"] == tag_v2
    assert res["corps"] == contenu_v2
    assert res["tokens_evites"] == 0


def test_isolation_deux_racines(configure_cache_dir):
    chemin = "C:/workspace/app/service.py"
    racine_a = "C:/workspace/worktree_a"
    racine_b = "C:/workspace/worktree_b"

    contenu = "def run():\n    pass\n" * 10
    tag = etag(contenu)

    # Enregistrement dans worktree A
    lecture_conditionnelle(chemin, contenu, racine_a)

    cle_a = _calculer_cle_fichier(racine_a, chemin)
    cle_b = _calculer_cle_fichier(racine_b, chemin)
    assert cle_a != cle_b

    dossier_a = configure_cache_dir / cle_a
    dossier_b = configure_cache_dir / cle_b

    assert (dossier_a / f"{tag}.txt").is_file()
    assert not dossier_b.exists()


def test_sixieme_version_retire_plus_ancienne(configure_cache_dir):
    chemin = "C:/fake/repo/app/module.py"
    racine = "C:/fake/repo"

    cle = _calculer_cle_fichier(racine, chemin)
    dossier_cle = configure_cache_dir / cle

    tags = []
    for i in range(6):
        contenu = f"Version {i}\n" * 10
        tag_i = etag(contenu)
        tags.append(tag_i)
        lecture_conditionnelle(chemin, contenu, racine)
        # Faire progresser légèrement le mtime pour ordonner strictement
        fic = dossier_cle / f"{tag_i}.txt"
        t = 1000.0 + (i * 10)
        import os
        os.utime(fic, (t, t))

    # Relancer une opération pour déclencher le contrôle de purge si nécessaire
    # ou vérifier directement le dossier
    # Comme la boucle ci-dessus crée les versions une par une, au 6e appel:
    fichiers = list(dossier_cle.glob("*.txt"))
    assert len(fichiers) == 5

    # Le tag 0 (le plus ancien) doit avoir disparu
    assert not (dossier_cle / f"{tags[0]}.txt").exists()
    # Le tag 5 (le plus récent) doit être présent
    assert (dossier_cle / f"{tags[5]}.txt").exists()
