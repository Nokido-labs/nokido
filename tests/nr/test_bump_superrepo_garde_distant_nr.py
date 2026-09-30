# -*- coding: utf-8 -*-
"""NR — le controle « ce sha est-il publie ? » doit porter les credentials.

__FORGE_COLOR__ = "qualite/livraison : non-regression du garde de gitlink"

CE QUI A ETE PAYE (2026-09-07). `forge_bump_superrepo` refuse de reaccrocher un
gitlink dont le sha n'existe pas chez le distant — garde JUSTE : un gitlink invalide
rend le submodule irrecuperable au clone, et l'inaction ne casse rien.

Mais le controle appelait `forge_delivery_integrity._git`, qui lance git avec
l'environnement HERITE (`subprocess.run` sans `env=`). Sur un depot PRIVE,
`ls-remote` sort donc vide **quel que soit le compte**, et le garde repondait
« distant illisible » depuis les TROIS comptes du hub — alors que le module va
chercher les jetons du coffre dans `_auth()`, deux fonctions plus haut, et ne les
passait pas a cet appel-la.

🔑 **Un garde qui exige une lecture qu'il n'authentifie jamais ne protege rien : il
interdit.** Meme famille que « un garde branche sur un signal que personne n'emet ».

⚠️ Le garde n'est PAS a assouplir. On lui donne les moyens de sa lecture — corriger
le diagnostic, jamais contourner le garde.

🪤 Ce fichier s'est d'abord appele `..._credentials_nr.py` et `.gitignore:91`
(`*_credentials*`, filet anti-secrets) l'a EXCLU du depot : un NR present en local,
absent du depot, donc jamais execute en CI. La regle est bonne, c'etait le nom qui
etait mauvais. `NR present != NR execute`.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import forge_bump_superrepo as bs  # noqa: E402

SRC = ROOT / "tools" / "forge_bump_superrepo.py"


def test_le_controle_du_distant_porte_l_environnement_authentifie(monkeypatch) -> None:
    """Comportement, pas relecture : on capture ce qui part reellement a git."""
    vu = {}

    def _faux(argv, **kw):
        vu["argv"] = argv
        vu["env"] = kw.get("env")

        class R:
            returncode = 0
            stdout = "cafe1234 refs/heads/alpha"
        return R()

    monkeypatch.setattr(bs, "_auth", lambda: (["-c", "credential.helper=temoin"],
                                              {"MARQUEUR_COFFRE": "1"}))
    monkeypatch.setattr(subprocess, "run", _faux)
    out = bs._git_distant(Path("."), "ls-remote", "origin", "refs/heads/alpha")

    assert vu["env"] == {"MARQUEUR_COFFRE": "1"}, (
        "sans `env=`, git part avec l'environnement herite et ls-remote sort vide "
        "sur un depot prive")
    assert "credential.helper=temoin" in vu["argv"], "les args de credential aussi"
    assert out == "cafe1234 refs/heads/alpha"


def test_un_echec_de_lecture_rend_une_chaine_VIDE_pas_une_exception() -> None:
    """L'appelant tranche sur `if not tip` : rendre None ou lever changerait le
    comportement du garde au lieu de le renseigner."""
    import inspect
    src = inspect.getsource(bs._git_distant)
    assert 'return r.stdout.strip() if r.returncode == 0 else ""' in src


def test_aucun_ls_remote_ne_passe_plus_par_le_helper_SANS_env() -> None:
    """`di._git` reste legitime pour les lectures LOCALES (merge-base) : elles n'ont
    besoin d'aucun credential. Seule la lecture du DISTANT doit changer de chemin."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    fautifs = [l.strip() for l in src.splitlines()
               if "ls-remote" in l and re.search(r"\bdi\._git\s*\(", l)]
    assert not fautifs, (
        "un ls-remote sans credential rend VIDE sur un depot prive, et le garde lit "
        "ce vide comme « distant illisible ». Trouve : %r" % fautifs)


def test_le_garde_refuse_toujours_un_sha_NON_publie() -> None:
    """Le correctif donne au garde les moyens de LIRE ; il ne l'assouplit pas.

    Les deux refus doivent rester dans la source : distant illisible, et sha absent
    du distant. Un garde qu'on « repare » en le desarmant n'est plus un garde."""
    src = SRC.read_text(encoding="utf-8", errors="replace")
    assert "on ne bumpe pas a l'aveugle" in src
    assert "n'est PAS publie" in src
    assert "--is-ancestor" in src, "l'ancetre reste la condition d'acceptation"
