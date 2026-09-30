"""NR — aucun pattern attendant un fournisseur mort ne doit affamer le daemon.

SERIE NATURELLE INSTRUMENTEE DU 2026-08-31, cinq morts avec leur pattern :

    epistemic_consolidation   921 s
    epistemic_consolidation  1258 s
    epistemic_consolidation  1669 s
    epistemic_consolidation  1217 s
    health_check              699 s

Dans les CINQ cas, `gap_s == pattern_running_for_s` : l'instance est entree dans
le pattern, a battu une derniere fois, et n'en est jamais ressortie.

CE QUI EST ETABLI, et rien de plus : les morts surviennent pendant qu'un pattern
attend un fournisseur externe. On n'affirme pas que ces patterns TUENT le daemon
— on protege sa liveness contre cette classe de blocage.

DEUX CAUSES DISTINCTES, deux remedes distincts :
  - `epistemic_consolidation` appelle Ollama en LOCAL (120 s par lot, 20 lots) et
    son repli Cerebras est OPT-IN par contrat. Sur fournisseur mort il n'a aucune
    issue : il attend. Remede = abstention sur capteur de sante EXISTANT.
  - `health_check` sonde 8 endpoints bornes a 12 s CHACUN, ce qui ne borne rien
    globalement. Remede = budget TOTAL, sans reecrire le moniteur.

HERMETIQUE : aucun reseau, aucun LLM, aucun delai reel de 120 s.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "app", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_veille_digest as vd  # noqa: E402
from app import forge_autonomous_loops as al  # noqa: E402

_MODELE_EPI = "qwen2.5-coder:1.5b"      # ce que `consolider` appelle reellement


def _sante(tmp_path, monkeypatch, statut="200", nom="ollama", age=0.0,
           modele_pret=True):
    """Les DEUX capteurs, isoles.

    Le releve `endpoint_health_last.json` atteste que le PORT repond ; il ne dit
    rien du MODELE. Mesure 2026-08-31 : `_fournisseur_pret('ollama')` rendait
    True pendant que `/api/ps` rendait `{"models":[]}` — le pattern passait le
    garde, payait un chargement a froid et tuait le daemon en 65 s. Depuis, la
    garde exige MODEL_READY, donc un test qui n'isole que le releve sortirait
    sur le reseau reel et mesurerait la machine au lieu du code.
    """
    p = tmp_path / "endpoint_health.json"
    p.write_text(json.dumps({"ts": time.time() - age,
                             "par_statut": {statut: [nom]}}), encoding="utf-8")
    monkeypatch.setattr(al, "_SANTE_ENDPOINTS", p)
    monkeypatch.setattr(vd, "_SANTE_ENDPOINTS", p)
    monkeypatch.setattr(vd, "sonde_ollama", lambda *a, **k: {
        "api": True, "catalogue": [_MODELE_EPI],
        "residents": [_MODELE_EPI] if modele_pret else []})
    return p


@pytest.fixture()
def consolidateur(monkeypatch):
    """`consolider` INJECTE : il ne doit JAMAIS etre appele fournisseur mort.
    S'il l'est, c'est la regression exacte des quatre morts observees."""
    import forge_epistemic_extract_claims as fe
    appels: list = []

    def _faux(limit=20, **kw):
        appels.append({"limit": limit})
        return {"traites": limit}

    monkeypatch.setattr(fe, "consolider", _faux)
    monkeypatch.setattr(al, "_ram_gate", lambda *a, **k: True)
    return appels


# ── 1 / 6 : fournisseur sain ────────────────────────────────────────────────
def test_1_fournisseur_SAIN_le_pattern_travaille(tmp_path, monkeypatch,
                                                 consolidateur):
    _sante(tmp_path, monkeypatch, statut="200")
    r = al.PATTERNS["epistemic_consolidation"].fn()
    assert len(consolidateur) == 1
    assert "skipped" not in r


def test_6_fournisseur_REVENU_le_travail_reprend(tmp_path, monkeypatch,
                                                 consolidateur):
    """La matiere n'a pas ete perdue pendant l'abstention."""
    _sante(tmp_path, monkeypatch, statut="200", modele_pret=False)
    assert al.PATTERNS["epistemic_consolidation"].fn()["skipped"] == "fournisseur_indisponible"
    assert consolidateur == []
    _sante(tmp_path, monkeypatch, statut="200", modele_pret=True)
    al.PATTERNS["epistemic_consolidation"].fn()
    assert len(consolidateur) == 1


def test_6bis_PORT_ouvert_mais_modele_NON_CHARGE_fait_s_abstenir(
        tmp_path, monkeypatch, consolidateur):
    """LA regression du 2026-08-31, et elle est de mon fait.

    En corrigeant `-` (non sonde) pour qu'il cesse de valoir « en panne », j'ai
    leve une abstention qui PROTEGEAIT par accident : tant qu'ollama etait range
    en `-`, ce pattern s'abstenait. Des qu'il est repasse a 200, le garde a
    laisse passer — et le daemon est mort en 65 s sur ce pattern, pouls fige a
    `current_pattern: epistemic_consolidation`, alors que `/api/ps` rendait
    `{"models":[]}`. SERVICE_UP n'a jamais valu MODEL_READY.
    """
    _sante(tmp_path, monkeypatch, statut="200", modele_pret=False)
    r = al.PATTERNS["epistemic_consolidation"].fn()
    assert r["skipped"] == "fournisseur_indisponible"
    assert r["etat_modele"] == "MODEL_COLD"
    assert consolidateur == [], "un chargement a froid a ete paye sur le tick"


# ── 2 / 3 / 4 / 5 / 8 : les trois etats qui font s'abstenir ─────────────────
# `-` a change de LIBELLE le 2026-08-31, pas de comportement : il fait toujours
# s'abstenir, mais il se nomme desormais NON SONDE. `probe` ne produit cette
# valeur que depuis son `except` generique — c'est une absence de mesure, pas un
# verdict de panne. L'ancien libelle « INDISPONIBLE » etait la formulation meme du
# defaut qui a fait s'abstenir `veille_digest_auto` sept fois sur un Ollama vivant.
# Le releve de sante ne juge plus ce pattern : il attend MODEL_READY, qui se
# mesure sur la sonde locale. Les trois etats testes restent ceux qui font
# s'abstenir, mais ils se declarent desormais du cote du MODELE.
@pytest.mark.parametrize("cas,sonde,motif", [
    ("API_MUETTE", {"api": False, "raison": "URLError"}, "injoignable"),
    ("NON_SONDEE", {"api": None}, "NON SONDE"),
    ("MODELE_ABSENT", {"api": True, "catalogue": ["un_autre"], "residents": []},
     "absent du catalogue"),
    ("MODELE_FROID", {"api": True, "catalogue": [_MODELE_EPI], "residents": []},
     "NON CHARGE"),
    ("RESIDENTS_ILLISIBLES",
     {"api": True, "catalogue": [_MODELE_EPI], "residents": None}, "ILLISIBLES"),
])
def test_2345_les_etats_non_prets_font_s_abstenir(tmp_path, monkeypatch,
                                                  consolidateur, cas, sonde,
                                                  motif):
    # L'ABSTENTION est identique dans tous les cas : c'est le COMPORTEMENT qui est
    # verrouille ici, le libelle n'etant verifie que pour rester diagnostique.
    _sante(tmp_path, monkeypatch, statut="200")
    monkeypatch.setattr(vd, "sonde_ollama", lambda *a, **k: sonde)
    r = al.PATTERNS["epistemic_consolidation"].fn()
    assert r["skipped"] == "fournisseur_indisponible"
    assert motif in r["raison"]
    # 5 + 8 : AUCUN lot consomme, AUCUN appel LLM lance.
    assert consolidateur == [], "un appel LLM a ete lance sur fournisseur %s" % cas
    assert "matiere reste entiere" in r["note"]


def test_sante_ABSENTE_fait_s_abstenir_aussi(tmp_path, monkeypatch, consolidateur):
    monkeypatch.setattr(al, "_SANTE_ENDPOINTS", tmp_path / "jamais_ecrit.json")
    r = al.PATTERNS["epistemic_consolidation"].fn()
    assert r["skipped"] == "fournisseur_indisponible"
    assert consolidateur == []


# ── 7 : la sonde de sante ne peut plus attendre des minutes ─────────────────
def test_7_une_sonde_qui_traine_est_ABANDONNEE_au_budget():
    """`monitor` borne chaque requete a 12 s et il y a 8 fournisseurs : rien ne
    borne l'ensemble. La mort instrumentee de health_check a dure 699 s."""
    def _interminable():
        time.sleep(30)
        return ["jamais"]

    t0 = time.time()
    val, depasse = al._borner(_interminable, 0.2, defaut=[])
    ecoule = time.time() - t0
    assert depasse is True
    assert val == []
    assert ecoule < 3.0, "la borne n'a pas rendu la main (%.1f s)" % ecoule


def test_7bis_une_sonde_rapide_passe_normalement():
    val, depasse = al._borner(lambda: ["ok"], 5.0, defaut=[])
    assert depasse is False and val == ["ok"]


def test_7ter_une_erreur_de_la_sonde_REMONTE_au_lieu_d_etre_avalee():
    """Un echec qui passerait pour un depassement ferait diagnostiquer un
    fournisseur lent la ou le code est casse."""
    def _rate():
        raise ValueError("moniteur casse")

    with pytest.raises(ValueError):
        al._borner(_rate, 5.0)


def test_le_budget_total_est_plus_petit_qu_un_pire_cas_legitime():
    """8 fournisseurs x 12 s = 96 s, deja plus qu'un tick de 60 s."""
    assert al._ENDPOINTS_BUDGET_S < 96
    assert al._ENDPOINTS_BUDGET_S < 60


# ── 9 : LE test central ─────────────────────────────────────────────────────
def test_9_l_abstention_d_un_pattern_NE_BLOQUE_PAS_les_suivants(tmp_path,
                                                                monkeypatch,
                                                                consolidateur):
    """pattern A (fournisseur KO) rend vite -> pattern B demarre.

    C'est la propriete perdue le 2026-08-31 : `veille_github_head` n'a jamais
    obtenu son tour parce qu'un pattern amont attendait un fournisseur mort.
    """
    # La panne se declare desormais du cote du MODELE : port ouvert, modele non
    # charge — exactement l'etat reel du 2026-08-31 a 23:02.
    _sante(tmp_path, monkeypatch, statut="200", modele_pret=False)
    monkeypatch.setattr(al, "DB", tmp_path / "loops.db")
    monkeypatch.setattr(al, "_POULS_ETAT", {})
    passages: list = []
    monkeypatch.setattr(al, "PATTERNS", {
        "a_epistemic": al.Pattern(name="a_epistemic",
                                  fn=al.PATTERNS["epistemic_consolidation"].fn,
                                  interval_sec=0, description="banc"),
        "b_suivant": al.Pattern(name="b_suivant",
                                fn=lambda: passages.append("b") or {"ok": 1},
                                interval_sec=0, description="banc"),
    })
    t0 = time.time()
    res = al.run_due_patterns(force=True)
    ecoule = time.time() - t0
    assert passages == ["b"], "le pattern suivant n'a pas eu son tour"
    assert len(res) == 2
    assert consolidateur == []
    # Hermetique : sans la borne, ce tour aurait dure des minutes.
    assert ecoule < 5.0, "le tour a dure %.1f s" % ecoule
