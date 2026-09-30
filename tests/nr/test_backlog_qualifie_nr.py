"""NR — le regulateur decide sur le backlog QUALIFIE, sans payer son calcul.

Mesure du 2026-09-02 qui fonde ce test. `arbitrer_pression` recevait
`_backlog_embeddings()`, c'est-a-dire `COUNT(embedding IS NULL)` = 751 305. Or
ce nombre melange trois etats que `forge_memory_availability` distingue :

    626 646  REFUSED_BY_POLICY   refuses par palier, ils n'attendent RIEN
    124 659  PENDING             le backlog reel
  1 280 037  AVAILABLE

L'arbitre comparait donc a son seuil de 5 000 une famine SIX FOIS plus grosse
que la vraie. Et le canal lexical couvre 100 % du corpus (2 031 354 entrees) :
la memoire reste interrogeable malgre la dette vectorielle.

Trois garanties, et elles sont independantes :
  1. la VALEUR consommee est le PENDING, pas le brut ;
  2. le chemin chaud ne declenche JAMAIS le calcul (8,27 s pour le seul
     GROUP BY, 139 342 groupes) -- il lit un fichier, ~7 ms ;
  3. l'absence de mesure se DIT (INCONNU) et ne se rabat pas sur le brut :
     un repli silencieux recreerait la confusion qu'on vient de lever.

Ce fichier ne teste PAS la politique d'arbitrage : la corriger n'etait pas
l'objet. Un cas verrouille meme le contraire -- a conditions egales, la
decision doit rester la meme qu'avec l'ancien capteur.
"""

import json
import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

import forge_memory_availability as ma  # noqa: E402
import forge_resource_manager as rm  # noqa: E402

BRUT = 751305          # ce que `embedding IS NULL` rendrait
PENDING = 124659       # le backlog reel
REFUSED = 626646


@pytest.fixture
def snap(tmp_path, monkeypatch):
    """Snapshot de TEST : jamais la vraie base (22 Go)."""
    p = tmp_path / "snap.json"
    monkeypatch.setattr(ma, "_SNAPSHOT", p)
    return p


def _ecrire(p, age_s=0.0):
    p.write_text(json.dumps({
        "measured_at": time.time() - age_s, "total": 2031342,
        "vector_pending": PENDING, "vector_available": 1280037,
        "vector_refused": REFUSED, "lexical_available": 2031354,
        "lexical_ecart_source": -12,
    }), encoding="utf-8")


# ----------------------------------------------------- 1. la bonne valeur

def test_le_backlog_consomme_est_le_pending_pas_le_brut(snap):
    _ecrire(snap)
    valeur, age, source = rm._backlog_pending_qualifie()
    assert valeur == PENDING, valeur
    assert valeur != BRUT, "le regulateur lit encore le chiffre brut"
    assert source == "snapshot"
    assert age is not None and age < 60


def test_le_brut_vaut_six_fois_le_reel(snap):
    """Ancre l'ordre de grandeur : si ce rapport change, la mesure a bouge."""
    _ecrire(snap)
    s = ma.snapshot()
    brut = s["vector_pending"] + s["vector_refused"]
    assert brut == BRUT
    assert brut / s["vector_pending"] > 5.5


# ------------------------------------------- 2. le chemin chaud ne calcule pas

def test_le_chemin_chaud_ne_declenche_jamais_le_calcul(snap, monkeypatch):
    """GARDE DE COUT. `compteurs()` balaye la table : 8,27 s pour le seul
    GROUP BY. Le declencher a chaque decision remplacerait un capteur FAUX par
    un capteur JUSTE qui etouffe l'organe qu'il informe."""
    _ecrire(snap)

    def _interdit(*a, **k):
        raise AssertionError("compteurs() appele sur le chemin chaud")

    monkeypatch.setattr(ma, "compteurs", _interdit)
    assert rm._backlog_pending_qualifie()[0] == PENDING


def test_la_lecture_est_rapide(snap):
    _ecrire(snap)
    t0 = time.time()
    for _ in range(20):
        rm._backlog_pending_qualifie()
    moyen = (time.time() - t0) / 20
    assert moyen < 0.20, "%.3f s par lecture : trop lent pour une boucle" % moyen


# --------------------------------------- 3. l'absence se dit, ne se replie pas

def test_snapshot_absent_rend_INCONNU_jamais_le_brut(snap):
    assert not snap.exists()
    valeur, _age, source = rm._backlog_pending_qualifie()
    assert valeur == -1, valeur
    assert valeur != BRUT
    assert "INCONNU" in source


def test_snapshot_perime_rend_INCONNU_jamais_une_vieille_valeur(snap):
    _ecrire(snap, age_s=ma._AGE_MAX_DEFAUT_S + 3600)
    valeur, age, source = rm._backlog_pending_qualifie()
    assert valeur == -1, "une valeur perimee a ete presentee comme utilisable"
    assert "INCONNU" in source and "perime" in source
    assert age is not None, "l'age doit remonter meme perime"


def test_snapshot_illisible_rend_INCONNU(snap):
    snap.write_text("{ ceci n'est pas du json", encoding="utf-8")
    valeur, _age, source = rm._backlog_pending_qualifie()
    assert valeur == -1 and "INCONNU" in source


def test_l_age_fait_partie_du_signal(snap):
    _ecrire(snap, age_s=1234.0)
    _valeur, age, _src = rm._backlog_pending_qualifie()
    assert age is not None and 1200 < age < 1300, age


# --------------------------------------------- 4. la politique n'a PAS bouge

def test_a_conditions_egales_la_decision_est_inchangee():
    """1a corrige le CAPTEUR, pas la politique. Les deux valeurs doivent
    produire la meme decision dans les conditions observees ce jour-la."""
    commun = dict(rhythm="NORMAL", coder_up=True, coder_conns=0, chains_active=0,
                  embed_wanted=False, embedder_up=False, coder_ram_gb=5.17,
                  free_gb=2.7)
    avant = rm.arbitrer_pression(backlog=BRUT, **commun)
    apres = rm.arbitrer_pression(backlog=PENDING, **commun)
    assert avant["action"] == apres["action"] == "protect_coder"


def test_le_seuil_n_a_pas_ete_touche():
    assert rm._BACKLOG_AFFAME == 5000, (
        "1a ne devait modifier aucun seuil : %s" % rm._BACKLOG_AFFAME)


# ------------------------------------------------- 5. gardes structurels

def test_la_decision_n_appelle_plus_le_compteur_brut():
    """GARDE STRUCTUREL : `embedding IS NULL` ne doit plus etre la variable
    physiologique de cette decision. Lecture du CORPS, pas d'une sonde --
    remettre l'ancien appel ne ferait echouer aucun test fonctionnel."""
    import inspect
    import re

    src = inspect.getsource(rm)
    for m in re.finditer(r"backlog\s*=\s*([^,\n]+)", src):
        arg = m.group(1).strip()
        assert "_backlog_embeddings" not in arg, (
            "un appel a arbitrer_pression passe encore le compteur brut : %s" % arg)


def test_le_snapshot_ne_calcule_jamais(monkeypatch, snap):
    """`snapshot()` est PASSIF par contrat : il lit, il ne mesure pas."""
    def _interdit(*a, **k):
        raise AssertionError("snapshot() a declenche un calcul")

    monkeypatch.setattr(ma, "compteurs", _interdit)
    assert ma.snapshot()["frais"] is False       # absent : pas de calcul non plus
    _ecrire(snap)
    assert ma.snapshot()["frais"] is True


def test_la_peremption_est_alignee_sur_son_emetteur():
    """Le rafraichisseur tourne en NREM1, phase QUOTIDIENNE. Une peremption
    plus courte qu'un cycle laisserait l'arbitre muet la majorite du temps --
    un garde qu'on croit avoir et qui ne repond pas."""
    assert ma._AGE_MAX_DEFAUT_S >= 86400, ma._AGE_MAX_DEFAUT_S


def test_l_emetteur_existe():
    """Un snapshot que personne ne rafraichit perime : le motif « garde branche
    sur un signal que personne n'emet », deja paye ici plusieurs fois."""
    assert (RACINE / "tools" / "forge_memory_snapshot_refresh.py").exists()
    assert callable(getattr(ma, "rafraichir", None))
