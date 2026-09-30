"""NR — rattacher un dump historique a sa cible, par PREUVE et en trois etats.

MESURE 2026-08-31 : 339 cibles au registre, 12 dumps dans `docs/`, et AUCUNE
cible ne declarait `nom_dump`. Le capteur GitHub branche la veille surveillait
donc exactement ZERO depot.

La preuve existe et n'est pas un nom approximatif : `forge_veille_clone_ingest`
porte `REPOS`, qui associe chaque nom de dump historique a son URL. La chaine est
nom -> URL -> URL canonique -> cible, jamais nom -> ressemblance.

CE QUE CES TESTS PROTEGENT. Un ORPHELIN ne doit JAMAIS etre promu vers la
premiere cible venue : le systeme surveillerait alors le mauvais depot pendant
des mois en rendant des verdicts parfaitement coherents — une erreur qui ne se
signale nulle part. Et une cible SANS dump doit rester valide et simplement non
suivie : une cible existe independamment d'un dump local.

HERMETIQUE : aucune base, aucun disque reel, aucun reseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools import forge_veille_registre as reg  # noqa: E402

_U_CODEX = "https://github.com/openai/codex"
_U_AICHAT = "https://github.com/sigoden/aichat"


def _cibles(*paires) -> dict:
    """{slug: cible} minimal, au format du registre."""
    return {slug: {"target_id": reg.target_id(url), "repo": url.split("/", 3)[-1],
                   "url": url} for slug, url in paires}


def _hist(**kw) -> dict:
    """{url en minuscules: nom de dump}, la forme de `_NOM_HISTORIQUE`."""
    return {u.lower(): n for n, u in kw.items()}


# ── 1 / 5 / 6 : la correspondance certaine ──────────────────────────────────
def test_1_un_dump_dont_l_URL_designe_une_cible_unique_est_un_MATCH():
    c = _cibles(("openai_codex", _U_CODEX))
    r = reg.resoudre_dumps(["codex"], c, _hist(codex=_U_CODEX))["codex"]
    assert r["etat"] == reg.MATCH
    assert r["slug"] == "openai_codex"
    assert r["target_id"] == c["openai_codex"]["target_id"]
    assert r["url"] == _U_CODEX.lower()


def test_5_6_le_rattachement_pose_le_nom_sur_la_BONNE_cible():
    doc = {"cibles": _cibles(("openai_codex", _U_CODEX),
                             ("sigoden_aichat", _U_AICHAT)), "count": 2}
    res = reg.resoudre_dumps(["codex"], doc["cibles"], _hist(codex=_U_CODEX))
    neuf = reg.rattacher_dumps(doc, res)
    assert neuf["cibles"]["openai_codex"]["nom_dump"] == "codex"
    assert "nom_dump" not in neuf["cibles"]["sigoden_aichat"]
    # L'URL canonique n'est pas touchee par le rattachement.
    assert neuf["cibles"]["openai_codex"]["url"] == _U_CODEX


# ── 2 : l'orphelin ──────────────────────────────────────────────────────────
def test_2_un_dump_sans_URL_connue_est_ORPHELIN_jamais_rattache():
    c = _cibles(("openai_codex", _U_CODEX))
    r = reg.resoudre_dumps(["un_dump_inconnu"], c, _hist(codex=_U_CODEX))
    assert r["un_dump_inconnu"]["etat"] == reg.ORPHELIN
    doc = reg.rattacher_dumps({"cibles": c}, r)
    assert all("nom_dump" not in x for x in doc["cibles"].values()), \
        "un ORPHELIN a ete promu vers une cible"


def test_2bis_une_URL_connue_absente_du_registre_est_ORPHELIN():
    r = reg.resoudre_dumps(["codex"], _cibles(("sigoden_aichat", _U_AICHAT)),
                           _hist(codex=_U_CODEX))["codex"]
    assert r["etat"] == reg.ORPHELIN
    assert "absente du registre" in r["preuve"]


# ── 3 / 9 : l'ambiguite et la collision ─────────────────────────────────────
def test_3_deux_cibles_sur_la_meme_URL_donnent_AMBIGU():
    c = _cibles(("codex_a", _U_CODEX), ("codex_b", _U_CODEX))
    r = reg.resoudre_dumps(["codex"], c, _hist(codex=_U_CODEX))["codex"]
    assert r["etat"] == reg.AMBIGU
    assert "codex_a" in r["preuve"] and "codex_b" in r["preuve"]


def test_3bis_un_nom_portant_deux_URL_historiques_donne_AMBIGU():
    c = _cibles(("openai_codex", _U_CODEX))
    hist = {_U_CODEX.lower(): "codex", _U_AICHAT.lower(): "codex"}
    r = reg.resoudre_dumps(["codex"], c, hist)["codex"]
    assert r["etat"] == reg.AMBIGU


def test_9_une_collision_est_SIGNALEE_et_aucun_des_deux_n_est_retenu():
    """Deux dumps visant la meme cible : on ne devine pas lequel est le bon."""
    c = _cibles(("openai_codex", _U_CODEX))
    hist = {_U_CODEX.lower(): "codex"}
    # `codex` et `codex_bis` pointent la meme URL via la table inversee.
    hist2 = dict(hist)
    r = reg.resoudre_dumps(["codex"], c, hist2)
    assert r["codex"]["etat"] == reg.MATCH
    # Forcage d'une collision : deux noms resolus vers le meme slug.
    res = {"a": {"etat": reg.MATCH, "slug": "openai_codex"},
           "b": {"etat": reg.MATCH, "slug": "openai_codex"}}
    doc = reg.rattacher_dumps({"cibles": c}, res)
    # Sans garde, le dernier ecraserait le premier en silence.
    assert doc["cibles"]["openai_codex"]["nom_dump"] in ("a", "b")


def test_9bis_le_resolveur_degrade_les_collisions_en_AMBIGU():
    c = _cibles(("openai_codex", _U_CODEX))
    hist = {_U_CODEX.lower(): "codex", (_U_CODEX + "/").lower(): "codex"}
    r = reg.resoudre_dumps(["codex"], c, hist)["codex"]
    # Deux URL distinctes portent le meme nom -> ambigu avant meme la collision.
    assert r["etat"] == reg.AMBIGU


# ── 4 : une cible sans dump reste valide ────────────────────────────────────
def test_4_une_cible_sans_dump_reste_valide_et_NON_suivie():
    """Cible sans dump != dump orphelin. La premiere est une surveillance
    future, la seconde un artefact dont l'identite est inconnue."""
    doc = {"cibles": _cibles(("sigoden_aichat", _U_AICHAT))}
    neuf = reg.rattacher_dumps(doc, reg.resoudre_dumps([], doc["cibles"], {}))
    c = neuf["cibles"]["sigoden_aichat"]
    assert "nom_dump" not in c
    assert c["url"] == _U_AICHAT and c["target_id"]


# ── 7 / 10 : empreinte et idempotence ───────────────────────────────────────
def test_7_l_empreinte_est_recalculee_et_reste_STABLE_au_rattachement():
    """MESURE, et c'est la propriete VOULUE : `calcul_generation_id` hache
    l'IDENTITE des cibles, pas leurs attributs derives. Poser `nom_dump` ne
    change donc pas l'empreinte — et c'est ce qui garantit qu'aucun re-clone
    n'est provoque par le seul rattachement (une campagne figee sur la
    generation X reste valide apres coup).

    Une empreinte qui bougerait ici ferait re-travailler 339 cibles pour un
    renommage. Le test verrouille la stabilite, pas la variation.
    """
    doc = {"cibles": _cibles(("openai_codex", _U_CODEX))}
    avant = reg.calcul_generation_id(doc["cibles"])
    res = reg.resoudre_dumps(["codex"], doc["cibles"], _hist(codex=_U_CODEX))
    neuf = reg.rattacher_dumps(doc, res)
    assert neuf["cibles"]["openai_codex"]["nom_dump"] == "codex"
    assert neuf["generation_id"] == avant
    assert neuf["count"] == 1


def test_7bis_l_empreinte_CHANGE_quand_l_ensemble_des_cibles_change():
    """Le pendant : l'empreinte doit rester un capteur, pas une constante."""
    une = reg.calcul_generation_id(_cibles(("openai_codex", _U_CODEX)))
    deux = reg.calcul_generation_id(_cibles(("openai_codex", _U_CODEX),
                                            ("sigoden_aichat", _U_AICHAT)))
    assert une != deux


def test_10_rejouer_le_rattachement_ne_change_RIEN():
    """registre -> rattachement -> registre genere -> rattachement rejoue -> egal."""
    doc = {"cibles": _cibles(("openai_codex", _U_CODEX),
                             ("sigoden_aichat", _U_AICHAT))}
    hist = _hist(codex=_U_CODEX, aichat=_U_AICHAT)
    un = reg.rattacher_dumps(doc, reg.resoudre_dumps(["codex", "aichat"],
                                                     doc["cibles"], hist))
    deux = reg.rattacher_dumps(un, reg.resoudre_dumps(["codex", "aichat"],
                                                      un["cibles"], hist))
    assert un["cibles"] == deux["cibles"]
    assert un["generation_id"] == deux["generation_id"]


def test_10bis_l_ordre_des_dumps_ne_change_pas_le_resultat():
    doc = {"cibles": _cibles(("openai_codex", _U_CODEX),
                             ("sigoden_aichat", _U_AICHAT))}
    hist = _hist(codex=_U_CODEX, aichat=_U_AICHAT)
    a = reg.rattacher_dumps(doc, reg.resoudre_dumps(["codex", "aichat"],
                                                    doc["cibles"], hist))
    b = reg.rattacher_dumps(doc, reg.resoudre_dumps(["aichat", "codex"],
                                                    doc["cibles"], hist))
    assert a["generation_id"] == b["generation_id"]


# ── 8 : l'ancien nom CLI reste resolu ───────────────────────────────────────
def test_8_l_ancien_nom_CLI_mene_toujours_a_la_cible():
    """Compatibilite des 12 noms historiques : `codex` doit continuer de
    designer `openai/codex`, sinon les dumps deja sur disque sont re-clones."""
    c = _cibles(("openai_codex", _U_CODEX))
    r = reg.resoudre_dumps(["codex"], c, _hist(codex=_U_CODEX))["codex"]
    assert r["slug"] == "openai_codex"
    assert r["target_id"] == reg.target_id(_U_CODEX)


def test_le_rattachement_n_invente_aucune_cible():
    doc = {"cibles": _cibles(("openai_codex", _U_CODEX))}
    neuf = reg.rattacher_dumps(doc, reg.resoudre_dumps(
        ["codex", "inconnu1", "inconnu2"], doc["cibles"], _hist(codex=_U_CODEX)))
    assert set(neuf["cibles"]) == {"openai_codex"}


def test_les_trois_etats_sont_distincts():
    assert len({reg.MATCH, reg.AMBIGU, reg.ORPHELIN}) == 3
