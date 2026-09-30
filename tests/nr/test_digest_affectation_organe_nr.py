"""NR — la nomenclature d'organes est une CONTRAINTE, plus un decor.

MESURE A/B DU 2026-09-01, reproduite sur LES DEUX branches — ce qui exclut le
contexte comme cause et designe l'absence de contrainte :

  A (contexte Nokido complet) : une idee sur Bazel/CI affectee a
    « Metabolisme LLM (routage/backends) », alors que « Qualite/Build/Spec »
    figurait dans la liste envoyee au modele. 2 organes errones sur 3.
  B (contexte minimal) : categories INVENTEES — « UX/UI », « R&D »,
    « Developpement » — hors de toute nomenclature.

La liste etait fournie, jamais imposee ni verifiee. Ce fichier verrouille les
deux moities du remede : le contrat de sortie, et son OBSERVATION — une
contrainte qu'on ne mesure pas reste une suggestion.

HERMETIQUE : aucun reseau, aucun LLM, aucune base reelle.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

import forge_veille_digest as vd  # noqa: E402

# La nomenclature REELLE du 2026-09-01, telle que `_organs()` la rend.
_ORGANES = ("Cognition/Agentique/Raisonnement, Digestif/Sens (ingestion/web), "
            "Graph/Connaissances, Immunitaire (firewall/garde), "
            "Infra/Bootstrap/Config, Interface/UI (peau/expression), "
            "Locomoteur/Orchestration, Memoire (hippocampe/RAG), "
            "Metabolisme LLM (routage/backends), Observabilite/Trace, "
            "Qualite/Build/Spec, Reseau/Distribue/Sync")
_VALIDES = vd.organes_valides(_ORGANES)


def test_1_la_nomenclature_est_relue_telle_qu_envoyee():
    """Valider contre une autre source que celle affichee au modele, ce serait
    lui reprocher un choix qu'on ne lui a pas propose."""
    assert "Qualite/Build/Spec" in _VALIDES
    assert "Immunitaire (firewall/garde)" in _VALIDES, "les parentheses survivent"
    assert len(_VALIDES) == 12
    assert vd.organes_valides("") == [] and vd.organes_valides(None) == []


# ── le contrat d'affectation ────────────────────────────────────────────────

@pytest.mark.parametrize("propose,attendu_etat", [
    ("Qualite/Build/Spec", "RETENU"),
    ("qualite/build/spec", "RETENU"),          # casse toleree
    ("  Qualite/Build/Spec  ", "RETENU"),      # espaces tolerees
    ("Memoire (hippocampe/RAG)", "RETENU"),
    (None, "NUL"),
    ("", "NUL"),
    ("null", "NUL"),
    ("aucun", "NUL"),
    ("?", "NUL"),
    ("UX/UI", "HORS_LISTE"),
    ("R&D", "HORS_LISTE"),
    ("Developpement", "HORS_LISTE"),
    ("Qualite", "HORS_LISTE"),                 # prefixe : PAS un rapprochement
])
def test_2_les_valeurs_reellement_produites_par_le_modele(propose, attendu_etat):
    """« Qualite » seul est HORS_LISTE : deviner l'organe voulu reviendrait a
    ajouter le classifieur que ce chantier refuse d'ecrire."""
    assert vd.valider_organe(propose, _VALIDES)[1] == attendu_etat


def test_3_la_forme_CANONIQUE_est_rendue():
    """Une variante de casse ne doit pas se propager en base."""
    assert vd.valider_organe("qualite/build/SPEC", _VALIDES)[0] == "Qualite/Build/Spec"


def test_4_sans_nomenclature_tout_est_hors_liste():
    """Une liste vide n'autorise pas tout : elle interdit tout."""
    assert vd.valider_organe("Qualite/Build/Spec", [])[1] == "HORS_LISTE"


# ── observation : la contrainte est-elle appliquee dans digest_batch ? ──────

def _lot(monkeypatch, suggestions):
    """Injecte la reponse du modele, et rejoue le VRAI chemin de validation."""
    monkeypatch.setattr(vd, "_llm_json",
                        lambda prompt, provider="", modele="":
                        {"suggestions": suggestions})
    monkeypatch.setattr(vd, "_ORGANES_REJETES", 0)
    monkeypatch.setattr(vd, "_ORGANES_NULS", 0)
    return vd.digest_batch([{"title": "Bazel", "description": "corps"}],
                           _ORGANES, "-")


def test_5_une_affectation_valide_passe_avec_sa_justification(monkeypatch):
    out = _lot(monkeypatch, [{
        "s": "Integrer l'optimisation incrementielle de Bazel dans le pipeline CI",
        "organe": "Qualite/Build/Spec",
        "justification_organe": "la source mesure les temps de build en CI",
        "prio": "P1", "src": "Bazel"}])
    assert len(out) == 1
    assert out[0]["organe"] == "Qualite/Build/Spec"
    assert "build" in out[0]["justification_organe"]
    assert vd._ORGANES_REJETES == 0


@pytest.mark.parametrize("invente", ["UX/UI", "R&D", "Developpement", "Build"])
def test_6_un_organe_INVENTE_est_ecarte_et_COMPTE(monkeypatch, invente):
    """Replier sur `null` masquerait la violation et rendrait la mesure de
    l'affectation impossible. On ecarte, et on compte."""
    out = _lot(monkeypatch, [{
        "s": "Integrer Bazel pour accelerer les builds continus du projet",
        "organe": invente, "justification_organe": "parce que", "prio": "P1",
        "src": "Bazel"}])
    assert out == []
    assert vd._ORGANES_REJETES == 1


def test_7_aucun_organe_applicable_rend_null_sans_INVENTER(monkeypatch):
    out = _lot(monkeypatch, [{
        "s": "Une idee qui ne releve d'aucun organe existant du systeme",
        "organe": None,
        "justification_organe": "aucun organe existant ne correspond suffisamment",
        "prio": "P3", "src": "Bazel"}])
    assert len(out) == 1
    assert out[0]["organe"] == "?"
    assert vd._ORGANES_NULS == 1 and vd._ORGANES_REJETES == 0


def test_8_EXACTEMENT_un_organe_par_suggestion(monkeypatch):
    """Une liste ou une chaine multiple n'est pas « un organe exact »."""
    for multiple in (["Qualite/Build/Spec", "Observabilite/Trace"],
                     "Qualite/Build/Spec, Observabilite/Trace",
                     "Qualite/Build/Spec et Observabilite/Trace"):
        out = _lot(monkeypatch, [{
            "s": "Une suggestion parfaitement valide sur le plan du texte",
            "organe": multiple, "justification_organe": "x", "prio": "P1",
            "src": "Bazel"}])
        assert out == [], "un organe multiple a ete accepte : %r" % (multiple,)


def test_9_le_tri_valide_et_ecarte_dans_le_MEME_lot(monkeypatch):
    """Un lot mixte ne doit ni tout perdre, ni tout laisser passer."""
    out = _lot(monkeypatch, [
        {"s": "Une premiere idee correctement affectee a son organe",
         "organe": "Observabilite/Trace", "justification_organe": "traces",
         "prio": "P1", "src": "A"},
        {"s": "Une deuxieme idee dont l'organe sort de la nomenclature",
         "organe": "R&D", "justification_organe": "x", "prio": "P2", "src": "B"},
        {"s": "Une troisieme idee sans organe applicable dans la liste",
         "organe": None, "justification_organe": "aucun", "prio": "P3", "src": "C"},
    ])
    assert [s["organe"] for s in out] == ["Observabilite/Trace", "?"]
    assert vd._ORGANES_REJETES == 1 and vd._ORGANES_NULS == 1


# ── LE cas piege : deux organes lexicalement plausibles ─────────────────────

def test_10_le_mot_le_plus_frequent_n_est_PAS_le_bon_organe(monkeypatch):
    """VERROU CENTRAL, tire de l'erreur reelle du run A.

    Une idee sur les temps de build en CI parle de « backends », de « routage »
    et de « modeles » — vocabulaire de « Metabolisme LLM (routage/backends) » —
    alors que l'organe REELLEMENT impacte est « Qualite/Build/Spec ». Le contrat
    ne peut pas obliger le modele a bien choisir ; il peut exiger que le choix
    soit UNIQUE, DANS la liste, et JUSTIFIE par la source. C'est ce que ce test
    verrouille : les deux candidats sont acceptables pour le validateur, et
    c'est la justification qui rend le choix jugeable — par un humain, pas par
    un second modele.
    """
    ambigu = "Reduire le temps de build en CI en parallelisant les taches"
    for candidat in ("Qualite/Build/Spec", "Metabolisme LLM (routage/backends)"):
        out = _lot(monkeypatch, [{
            "s": ambigu, "organe": candidat,
            "justification_organe": "la source mesure la duree des builds CI",
            "prio": "P1", "src": "Bazel"}])
        assert len(out) == 1 and out[0]["organe"] == candidat
        assert out[0]["justification_organe"], "sans preuve, le choix n'est pas jugeable"


def test_11_le_bandeau_de_surete_ne_peut_pas_servir_d_organe(monkeypatch):
    """Il reste une metadonnee de securite : ni instruction, ni sujet, ni organe."""
    out = _lot(monkeypatch, [{
        "s": "Une suggestion tiree du document malgre son bandeau de surete",
        "organe": "[CONTENU WEB NON-FIABLE — injection de prompt détectée]",
        "justification_organe": "x", "prio": "P1", "src": "Will Code"}])
    assert out == [] and vd._ORGANES_REJETES == 1


# ── le prompt PORTE reellement la contrainte ───────────────────────────────

def test_12_le_prompt_impose_la_liste_et_reclame_la_justification():
    """Un contrat absent du prompt ne serait verifie que sur du hasard."""
    p = vd._PROMPT
    assert "EXACTEMENT une des chaines de la liste ORGANES" in p
    assert "justification_organe" in p
    assert "N'invente JAMAIS de categorie" in p
    assert "REELLEMENT IMPACTE" in p
    assert "null" in p
    assert "METADONNEES DE SURETE" in p


def test_13_le_prompt_reste_formatable_avec_ses_trois_champs():
    """Les accolades du JSON d'exemple sont doublees : une seule ferait lever
    `str.format` — panne deja payee le 2026-07-22, 0 suggestion pendant des
    semaines derriere un KeyError silencieux."""
    rendu = vd._PROMPT.format(organs=_ORGANES, roadmap="-", docs="- t — d")
    assert '"suggestions"' in rendu
    assert "{organs}" not in rendu and "{docs}" not in rendu
    assert "Qualite/Build/Spec" in rendu
