# -*- coding: utf-8 -*-
"""NR — la clé Gemini est résolue par le COFFRE, et ne reste pas dans l'environnement.

Finding E1 du registre de sécurité, passe 3 du 2026-09-22.

CE QUI A ÉTÉ MESURÉ
===================
`app/forge_litellm_connector.py`, par booléens évalués côté serveur :

    importe forge_secrets : False
    appelle get_secret(   : False
    écrit dans os.environ : True

La chaîne réelle de résolution était :

    _load_env()  ->  _load_env_file("Nokido.env")  puis  dict(os.environ)

Or l'ordre documenté de `forge_secrets.get_secret` est : coffre DPAPI machine, puis
WCM per-user, puis `Nokido.env`, puis l'environnement **en émettant un WARNING
« non securise »**. Ce module partait directement du troisième échelon : les deux
premiers n'étaient jamais interrogés, et le WARNING qui devait signaler le repli
n'était jamais émis.

    UNE RÈGLE ÉCRITE QU'AUCUNE PORTE NE CONSULTE NE GARDE RIEN.

Troisième occurrence du motif en deux jours, sur trois organes sans rapport.

ET LE DÉFAUT EST RÉALISÉ, PAS THÉORIQUE
=======================================
`LITELLM_USE_PROXY` vaut `False`, donc le mode direct est le chemin PAR DÉFAUT, et la
clé est présente sur cette machine. Ce n'est pas une branche morte : `mécanisme
présent != défaut réalisé` joue ici dans l'autre sens, et il fallait le mesurer avant
de le dire.

LES DEUX PROPRIÉTÉS GARDÉES
===========================
1. La clé est demandée au COFFRE, et à CHAQUE APPEL — pas une fois au chargement du
   module. Une résolution au chargement rend une rotation de clé invisible jusqu'au
   redémarrage, et « une migration d'import est invisible jusqu'au redémarrage » est
   une leçon déjà payée ici.
2. Si la clé doit transiter par l'environnement du processus, elle en est RETIRÉE
   après l'appel. L'écriture permanente élargit sa portée à tout module chargé dans
   le hub et à tout sous-processus lancé ensuite — c'est une élévation de portée, pas
   un simple détail d'implémentation.

CE QUE CE NR N'EXIGE PAS, ET POURQUOI
=====================================
Il n'exige pas que la clé soit passée en paramètre à la bibliothèque. Ce serait plus
propre, mais `litellm` est ILLISIBLE depuis le compte sandbox — son import tente une
requête sortante et échoue sur la membrane. On ne pose pas un correctif dont on ne
peut pas éprouver la forme : `ILLISIBLE != INCOMPATIBLE`, et l'inverse non plus.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_litellm_connector as C  # noqa: E402

_CLE = "GEMINI_API_KEY"


def test_le_module_consulte_le_coffre():
    """La PROPRIÉTÉ, pas le nom : une fonction de résolution existe et passe par
    `forge_secrets`. Chercher un nom connu d'avance ne voit pas ce qui arrive —
    six faux verts de ce motif ont été payés le 2026-09-22."""
    resolveur = getattr(C, "_cle_gemini", None)
    assert callable(resolveur), (
        "aucun résolveur de clé au niveau module : la clé est donc lue au chargement, "
        "et une rotation resterait invisible jusqu'au redémarrage"
    )
    src = Path(C.__file__).read_text(encoding="utf-8", errors="replace")
    assert "forge_secrets" in src, "le module ne mentionne toujours pas le coffre"
    assert "get_secret" in src, "le module n'appelle pas get_secret"


def test_le_resolveur_prefere_le_coffre_a_l_environnement(monkeypatch):
    """CONTRÔLE POSITIF : si le coffre rend une valeur, c'est elle qui sort —
    même lorsque l'environnement en porte une autre."""
    temoin_coffre = "valeur-du-coffre-" + "x" * 8
    temoin_env = "valeur-de-l-env-" + "y" * 8
    monkeypatch.setenv(_CLE, temoin_env)
    monkeypatch.setattr(C, "_ENV", dict(C._ENV, **{_CLE: temoin_env}), raising=False)
    # On substitue `get_secret` SOUS SON NOM. La première version passait par un
    # wrapper `_get_secret`, et ce nom à underscore rendait le coffre INVISIBLE à
    # l'exemption `_repli_apres_coffre` du gate golden-rules — cliquet rompu,
    # 1 -> 3 violations. Le détecteur avait raison : un nom d'appel générique ne
    # prouve pas qu'on parle au coffre.
    monkeypatch.setattr(C, "get_secret", lambda k, **kw: temoin_coffre if k == _CLE else None,
                        raising=False)
    assert C._cle_gemini() == temoin_coffre, (
        "le résolveur préfère l'environnement au coffre, ou n'appelle pas le coffre du tout"
    )


def test_le_resolveur_retombe_sur_l_environnement_quand_le_coffre_est_muet(monkeypatch):
    """CONTRE-ÉPREUVE : sans elle, un résolveur qui rend toujours la même chose
    passerait le test précédent. Et le repli doit rester possible — couper l'accès
    d'un module qui fonctionne serait une régression, pas un durcissement."""
    temoin_env = "repli-environnement-" + "z" * 6
    monkeypatch.setattr(C, "get_secret", lambda k, **kw: None, raising=False)
    monkeypatch.setattr(C, "_ENV", dict(C._ENV, **{_CLE: temoin_env}), raising=False)
    assert C._cle_gemini() == temoin_env, "le repli documenté n'est plus emprunté"


def test_l_environnement_revient_a_son_etat_apres_l_appel(monkeypatch):
    """La propriété E1, exercée sur le CHEMIN RÉEL et pas seulement lue dans la source.

    Trois cas, parce qu'ils se comportent différemment : variable absente avant,
    variable présente avant, et sortie par EXCEPTION — ce dernier étant celui qui
    laissait la clé en place dans la version d'origine, et le seul qui compte
    vraiment puisqu'un appel réseau échoue plus souvent qu'il ne réussit.
    """
    import os as _os

    monkeypatch.delenv(_CLE, raising=False)
    with C._env_temporaire(_CLE, "valeur-de-passage"):
        assert _os.environ[_CLE] == "valeur-de-passage"
    assert _CLE not in _os.environ, "la clé survit à l'appel alors qu'elle était ABSENTE avant"

    monkeypatch.setenv(_CLE, "etat-anterieur")
    with C._env_temporaire(_CLE, "valeur-de-passage"):
        assert _os.environ[_CLE] == "valeur-de-passage"
    assert _os.environ[_CLE] == "etat-anterieur", "l'état antérieur n'est pas restauré"

    monkeypatch.delenv(_CLE, raising=False)
    try:
        with C._env_temporaire(_CLE, "valeur-de-passage"):
            raise RuntimeError("panne pendant l'appel")
    except RuntimeError:
        pass
    assert _CLE not in _os.environ, (
        "la clé survit à une SORTIE PAR EXCEPTION — c'est exactement le défaut E1"
    )


def test_la_cle_ne_reste_pas_dans_l_environnement_du_processus():
    """La propriété qui compte vraiment : quelle que soit la façon dont la clé est
    passée à la bibliothèque, l'environnement du processus revient à son état."""
    src = Path(C.__file__).read_text(encoding="utf-8", errors="replace")
    lignes = src.splitlines()
    ecritures = [
        (i + 1, l.strip())
        for i, l in enumerate(lignes)
        if "os.environ[" in l and "=" in l and not l.strip().startswith("#")
    ]
    print(f"[E1] {len(ecritures)} ecriture(s) dans os.environ au niveau source")
    for numero, ligne in ecritures:
        # Une écriture n'est tolérée que si le module sait la défaire.
        fenetre = "\n".join(lignes[max(0, numero - 6):min(len(lignes), numero + 22)])
        assert "finally" in fenetre, (
            f"L{numero} écrit la clé dans l'environnement du processus sans bloc de "
            f"restauration : la valeur survit à l'appel et devient lisible par tout "
            f"module chargé dans ce processus et par tout sous-processus lancé ensuite"
        )
        assert ("pop(" in fenetre or "del os.environ" in fenetre), (
            f"L{numero} : aucune remise en état de l'environnement n'est visible autour "
            "de l'écriture"
        )


def test_la_cle_n_est_pas_figee_au_chargement_du_module():
    """Une constante de module résolue à l'import rend une rotation invisible
    jusqu'au redémarrage — leçon déjà payée sur les migrations d'import."""
    # `bool(...)` et JAMAIS la valeur : un `assert not valeur` fait entrer le
    # secret dans le message d'echec de pytest, donc dans les journaux de CI.
    # Mesure du 2026-09-22 : la premiere version de cette ligne a fait remonter la
    # cle, que le redacteur du canal a heureusement masquee. Le garde n'est pas une
    # excuse pour le testeur — c'est la lecon du 2026-09-21, re-payee ici.
    cle_figee_au_chargement = bool(getattr(C, "GEMINI_API_KEY", None))
    assert not cle_figee_au_chargement, (
        "la clé est encore résolue au chargement du module dans une constante ; "
        "elle doit être demandée au coffre à chaque appel, sinon une rotation reste "
        "invisible jusqu'au redémarrage"
    )
    # L'etat de l'environnement est OBSERVE et rapporte, jamais exige : ce test
    # porte sur le module, pas sur la machine qui l'execute.
    print(f"[E1] {_CLE} present dans l'environnement du processus : {_CLE in os.environ}")
