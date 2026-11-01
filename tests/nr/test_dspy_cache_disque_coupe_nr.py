# -*- coding: utf-8 -*-
"""NR — le routeur dspy coupe le cache DISQUE de dspy, et un `import dspy` hors ligne ne le tue pas.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du cache disque dspy coupe (diskcache sans correctif)"

CE QUI A ÉTÉ PAYÉ (2026-10-12). `diskcache` 5.6.3 (GHSA-w8v5-vhqr-4h9v) dépique ce qu'il trouve dans son dossier,
et AUCUNE version corrigée n'est publiée ; dspy l'exige (3.4.0 encore) et ouvre par défaut un cache disque
`~/.dspy_cache`. `app/forge_dspy_router.py` n'utilise dspy que pour ses Signatures (l'appel LLM passe par le hub) :
le cache disque n'a aucun usage, il est coupé à l'import. Sondé le même jour : hors ligne, `import dspy` mourait en
`ConnectionError` (tiktoken chargé à l'import par litellm) -- hors du garde `except ImportError` d'alors.

Les deux premiers tests passent par un FAUX module `dspy` : ils ne dépendent ni du réseau ni du cache tiktoken.

DURCI LE 2026-10-21. La coupure était muette et seulement DEMANDÉE (`configure_cache` appelé), jamais relue. Mesure du
jour : sous le compte du hub, dspy 3.2.1 ne peut déjà pas créer `~/.dspy_cache` et retombe seul en mémoire -- un test
sur le VRAI dspy passerait sans rien prouver. Les tests suivants tournent chacun dans un processus NEUF avec un
`DSPY_CACHEDIR` inscriptible : le cache disque est réellement ACTIF avant la coupure (précondition vérifiée), puis
relu coupé après l'import du routeur ; un échec de la coupure est DIT (`MITIGATION_CACHE_DISQUE`, stderr).
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _cache_tiktoken():
    """Le cache tiktoken (non versionne) : celui de l'arbre, sinon celui du depot principal.

    22/10 : la CI de reference tourne dans un worktree git qui n'a PAS `sandbox/tiktoken_cache` ;
    `import dspy` (avant le routeur) telechargeait alors cl100k_base hors ligne -> WinError 10013.
    Le depot principal se lit dans le fichier `.git` du worktree (`gitdir: <depot>/.git/worktrees/<nom>`).
    """
    candidats = [ROOT / "sandbox" / "tiktoken_cache"]
    marque = ROOT / ".git"
    if marque.is_file():
        ligne = marque.read_text(encoding="utf-8", errors="replace").strip()
        if ligne.startswith("gitdir:"):
            gitdir = Path(ligne[len("gitdir:"):].strip())
            if gitdir.parent.name == "worktrees":
                candidats.append(gitdir.parent.parent.parent / "sandbox" / "tiktoken_cache")
    return next((c for c in candidats if c.is_dir()), None)
MODULE = ROOT / "app" / "forge_dspy_router.py"


def _charger(monkeypatch, faux_dspy):
    """Importe le module DEPUIS SON FICHIER, avec `dspy` remplace (objet module, ou exception a lever)."""
    if isinstance(faux_dspy, BaseException):
        class _Chercheur:
            def find_spec(self, nom, chemin=None, cible=None):
                if nom == "dspy":
                    raise faux_dspy
                return None

        monkeypatch.delitem(sys.modules, "dspy", raising=False)
        monkeypatch.setattr(sys, "meta_path", [_Chercheur()] + sys.meta_path)
    else:
        monkeypatch.setitem(sys.modules, "dspy", faux_dspy)
    spec = importlib.util.spec_from_file_location("forge_dspy_router_nr", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _faux_dspy(appels: list):
    d = types.ModuleType("dspy")

    class Signature:
        pass

    d.Signature = Signature
    d.InputField = lambda **k: None
    d.OutputField = lambda **k: None
    d.configure_cache = lambda **k: appels.append(k)
    return d


def test_le_cache_disque_de_dspy_est_coupe_a_l_import(monkeypatch):
    appels: list = []
    mod = _charger(monkeypatch, _faux_dspy(appels))
    assert mod._DSPY_OK is True
    assert appels, "configure_cache n'a pas ete appele : le cache disque (diskcache) reste ouvert"
    assert appels[-1].get("enable_disk_cache") is False, appels[-1]


def test_un_import_dspy_hors_ligne_ne_tue_pas_le_module(monkeypatch):
    mod = _charger(monkeypatch, ConnectionError("tiktoken : WinError 10013"))
    assert mod._DSPY_OK is False
    rendu = mod.signature_call("CodePatchProposal", {}, provider="x", hub_token="")
    assert rendu["ok"] is False and "dspy" in rendu["error"]


# === Processus neuf, VRAI dspy (2026-10-21) ===================================


def _lancer(tmp_path, avant_import: str) -> dict:
    code = (
        "import json, sys\n"
        "sys.path.insert(0, %r)\n" % str(ROOT / "app")
        + avant_import + "\n"
        "etat = {}\n"
        "try:\n"
        "    import dspy\n"
        "    etat['avant'] = bool(getattr(dspy.cache, 'enable_disk_cache', None))\n"
        "except ImportError:\n"
        "    etat['avant'] = None\n"
        "import forge_dspy_router as r\n"
        "etat['mitigation'] = getattr(r, 'MITIGATION_CACHE_DISQUE', None)\n"
        "try:\n"
        "    import dspy\n"
        "    etat['apres'] = bool(getattr(dspy.cache, 'enable_disk_cache', None))\n"
        "except ImportError:\n"
        "    etat['apres'] = None\n"
        "print('ETAT=' + json.dumps(etat))\n"
    )
    env = dict(os.environ, PYTHONNOUSERSITE="1", DSPY_CACHEDIR=str(tmp_path / "dspy_cache"))
    tiktoken = _cache_tiktoken()
    if tiktoken is not None:
        env["CUSTOM_TIKTOKEN_CACHE_DIR"] = str(tiktoken)
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=200)
    lignes = [l for l in r.stdout.splitlines() if l.startswith("ETAT=")]
    assert lignes, "rc=%s\n%s" % (r.returncode, (r.stdout + r.stderr)[-1500:])
    etat = json.loads(lignes[-1][5:])
    etat["stderr"] = r.stderr
    return etat


def _dspy_present() -> bool:
    return importlib.util.find_spec("dspy") is not None


@pytest.mark.timeout(240)
@pytest.mark.skipif(not _dspy_present(), reason="dspy absent de cet interpreteur")
def test_le_cache_disque_actif_par_defaut_est_coupe_par_le_routeur(tmp_path):
    e = _lancer(tmp_path, "")
    assert e["avant"] is True, "precondition : le cache disque de dspy doit etre ACTIF avant le routeur %r" % e
    assert e["apres"] is False, "le routeur n'a pas coupe le cache disque de dspy %r" % e
    assert e["mitigation"] == "COUPE", e


@pytest.mark.timeout(240)
@pytest.mark.skipif(not _dspy_present(), reason="dspy absent de cet interpreteur")
def test_sans_configure_cache_l_echec_de_mitigation_est_dit(tmp_path):
    e = _lancer(tmp_path, "import dspy\ndel dspy.configure_cache")
    assert str(e["mitigation"]).startswith("ECHEC"), e
    assert "cache disque" in e["stderr"], "l'echec de la mitigation doit etre DIT %r" % e["stderr"][-500:]


@pytest.mark.timeout(240)
def test_sans_dspy_le_routeur_s_importe_et_le_dit(tmp_path):
    e = _lancer(tmp_path, "sys.modules['dspy'] = None")
    assert e["mitigation"] == "SANS_DSPY", e
