"""NR — quota cloud épuisé : le drain DORT jusqu'au rechargement, il ne martèle pas.

Mesure 2026-09-06 : Cloudflare a vectorisé **27 100 chunks en 376 s** (lots de 50,
812 caractères par chunk) puis a rendu « you have used up your daily free allocation of
10 000 neurons ». Le 2026-08-03, la même API n'avait donné que 3 631 chunks — en appels
UNITAIRES. Ce n'est donc pas le quota qui a changé, c'est la forme de l'appel : le lot
vaut ~7x. Une fois le quota à sec, continuer à appeler ne rend rien et brûle des
requêtes ; le drain doit attendre le rechargement (00:00 UTC).

Trois garanties :
  1. l'écouteur de quota est BRANCHÉ sur le logger du routeur, pas seulement déclaré
     (un garde posé sur un signal que personne n'émet est une dette, pas une sécurité) ;
  2. une passe vide AVEC erreurs et motif de quota → sommeil long ;
  3. une passe qui a écrit, ou qui échoue pour une AUTRE cause, ne dort pas.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_embed_auto_trigger as T  # noqa: E402


def test_l_ecouteur_reconnait_un_quota_epuise():
    T._DERNIER_MOTIF_QUOTA[0] = False
    e = T._EcouteQuota()
    log = logging.getLogger("essai_quota")
    log.addHandler(e)
    log.warning("[embed:cloudflare] appel KO (HTTPError) you have used up your daily "
                "free allocation of 10,000 neurons")
    assert T._DERNIER_MOTIF_QUOTA[0] is True


def test_l_ecouteur_ignore_une_panne_ordinaire():
    T._DERNIER_MOTIF_QUOTA[0] = False
    e = T._EcouteQuota()
    log = logging.getLogger("essai_autre")
    log.addHandler(e)
    log.warning("[embed:cloudflare] shape inattendue : dim=?")
    assert T._DERNIER_MOTIF_QUOTA[0] is False


def test_une_passe_vide_sur_quota_declenche_le_sommeil():
    T._DERNIER_MOTIF_QUOTA[0] = True
    assert T._quota_epuise({"embedded": 0, "errors": 50}) is True


def test_une_passe_qui_a_ecrit_ne_dort_pas():
    T._DERNIER_MOTIF_QUOTA[0] = True
    assert T._quota_epuise({"embedded": 500, "errors": 50}) is False


def test_une_panne_sans_motif_de_quota_ne_dort_pas():
    T._DERNIER_MOTIF_QUOTA[0] = False
    assert T._quota_epuise({"embedded": 0, "errors": 50}) is False


def test_le_sommeil_vise_le_rechargement_et_reste_borne():
    s = T._secondes_avant_reset_quota()
    assert 60.0 <= s <= 24 * 3600 + 600, s


def test_l_ecouteur_est_effectivement_branche_dans_le_point_d_entree():
    """Le NR du 2026-09-06 : declarer un garde ne suffit pas, il faut le RACCORDER."""
    src = (ROOT / "tools" / "forge_embed_auto_trigger.py").read_text(encoding="utf-8", errors="replace")
    assert "addHandler(_ecoute)" in src, "ecouteur declare mais jamais branche"
    assert "_fer.logger.addHandler" in src, "le logger du routeur n'est pas ecoute"
