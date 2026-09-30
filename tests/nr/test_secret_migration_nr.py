#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NR — tools/forge_secret_migration.py : migration des secrets vers le coffre.

Tests d'EFFET, jamais d'import. Chaque cas fait tourner la transformation sur
une source et compare le RESULTAT : un test qui verifierait que la fonction
existe n'attraperait aucune regression, et ne tuerait aucun mutant.

Les trois formes de lecture n'ont PAS le meme contrat, et c'est precisement ce
que ces tests figent :
    os.environ.get("X")      -> get_secret("X")          # None si absent
    os.environ.get("X", D)   -> get_secret("X") or D     # defaut preserve
    os.environ["X"]          -> INTOUCHE, signale        # levait KeyError
"""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import forge_secret_migration as M  # noqa: E402


def test_forme_sans_defaut_migre_vers_le_coffre():
    src = 'tok = os.environ.get("FORGE_MCP_TOKEN")\n'
    neuf, n, _ = M._migrer_source(src)
    assert n == 1
    assert 'get_secret("FORGE_MCP_TOKEN")' in neuf
    assert "os.environ.get" not in neuf


def test_forme_avec_defaut_PRESERVE_le_defaut():
    """`or D` n'est pas cosmetique : sans lui, un appelant qui comptait sur son
    defaut recevrait None, et le defaut disparaitrait en silence."""
    src = 'u = os.environ.get("LMSTUDIO_TOKEN", "vide")\n'
    neuf, n, _ = M._migrer_source(src)
    assert n == 1
    assert 'get_secret("LMSTUDIO_TOKEN") or "vide"' in neuf


def test_forme_indexee_JAMAIS_migree_mais_signalee():
    """`os.environ["X"]` LEVAIT KeyError. La migrer changerait la semantique :
    on la signale pour decision humaine, on n'y touche pas."""
    src = 'tok = os.environ["GITHUB_TOKEN"]\n'
    neuf, n, signale = M._migrer_source(src)
    assert n == 0, "la forme indexee ne doit jamais etre reecrite"
    assert 'os.environ["GITHUB_TOKEN"]' in neuf
    assert signale and "GITHUB_TOKEN" in signale[0]


@pytest.mark.parametrize("cle", ["LAFORGE_DB_PATH", "LAFORGE_ROOT", "LOG_DIR", "HOME"])
def test_les_non_secrets_sont_laisses_intacts(cle):
    """Un garde qui crie sur un chemin se fait desarmer. `_PATH`/`_DIR`/`_FILE`
    doivent passer, meme quand ils contiennent KEY ou PAT."""
    src = f'v = os.environ.get("{cle}")\n'
    neuf, n, _ = M._migrer_source(src)
    assert n == 0
    assert neuf == src


@pytest.mark.parametrize("cle", ["FORGE_MCP_TOKEN", "GROQ_API_KEY", "LAFORGE_DB_KEY",
                                 "LAFORGE_JWT_SECRET", "LANGFUSE_PUBLIC_KEY"])
def test_les_vrais_secrets_sont_reconnus(cle):
    assert M._est_secret(cle), f"{cle} doit etre traite comme un secret"


def test_appel_adapte_a_l_import_reel_from():
    src = "from forge_secrets import get_secret\n"
    assert M._forme_appel(src) == "get_secret"


def test_appel_adapte_a_l_import_reel_module():
    """⚠️ Le coeur de la surete. Un module qui fait `import forge_secrets` n'a
    PAS `get_secret` dans sa portee : y ecrire `get_secret(...)` produit un
    fichier qui PARSE et leve NameError a l'execution — l'AST ne voit pas un
    NameError."""
    src = "import forge_secrets\n"
    assert M._forme_appel(src) == "forge_secrets.get_secret"


def test_alias_d_import_respecte():
    src = "from forge_secrets import get_secret as gs\n"
    assert M._forme_appel(src) == "gs"
    neuf, n, _ = M._migrer_source('t = os.environ.get("HF_TOKEN")\n', "gs")
    assert n == 1 and 'gs("HF_TOKEN")' in neuf


def test_sans_import_du_coffre_aucun_appel_possible():
    """None = ce module ne peut pas appeler le coffre : il doit etre REPORTE,
    jamais migre a l'aveugle."""
    assert M._forme_appel("import os\n") is None


def test_source_migree_reste_parsable():
    import ast

    src = (
        "import os\n"
        "from forge_secrets import get_secret\n"
        'a = os.environ.get("FORGE_MCP_TOKEN")\n'
        'b = os.environ.get("GROQ_API_KEY", "x")\n'
    )
    neuf, n, _ = M._migrer_source(src)
    assert n == 2
    ast.parse(neuf)


def test_essai_a_blanc_n_ecrit_rien(tmp_path, monkeypatch):
    """Hermetique : on detourne le module vers un arbre jetable, jamais le
    working tree. `--dry-run` (defaut) ne doit modifier AUCUN octet."""
    faux = tmp_path / "tools"
    faux.mkdir(parents=True)
    cible = faux / "faux_client.py"
    cible.write_text(
        "from forge_secrets import get_secret\n"
        'import os\n'
        't = os.environ.get("FORGE_MCP_TOKEN")\n',
        encoding="utf-8",
    )
    avant = cible.read_bytes()
    monkeypatch.setattr(M, "_fichiers", lambda: [str(cible)])
    monkeypatch.setattr(M, "ROOT", str(tmp_path))

    r = M.executer(appliquer=False)
    assert r["occurrences_migrees"] == 1
    assert cible.read_bytes() == avant, "le dry-run a ECRIT sur le disque"


def test_application_ecrit_et_preserve_les_octets(tmp_path, monkeypatch):
    """`--appliquer` ecrit, et n'introduit PAS de CRLF : reecrire en mode texte
    salirait tout le depot (defaut deja paye par le cliquet de mutation)."""
    faux = tmp_path / "tools"
    faux.mkdir(parents=True)
    cible = faux / "faux_client.py"
    cible.write_bytes(
        b"from forge_secrets import get_secret\n"
        b"import os\n"
        b't = os.environ.get("FORGE_MCP_TOKEN")\n'
    )
    monkeypatch.setattr(M, "_fichiers", lambda: [str(cible)])
    monkeypatch.setattr(M, "ROOT", str(tmp_path))

    r = M.executer(appliquer=True)
    assert r["occurrences_migrees"] == 1
    apres = cible.read_bytes()
    assert b'get_secret("FORGE_MCP_TOKEN")' in apres
    assert b"os.environ.get" not in apres
    assert b"\r\n" not in apres, "reecriture en mode texte : fins de ligne converties"
