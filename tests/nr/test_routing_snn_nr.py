# -*- coding: utf-8 -*-
"""Tests NR — contrat de decision de routage et etage SNN L1.

Verifient l'EFFET, pas l'import : chaque test fait prendre une decision au code
et controle ce qu'elle vaut. Un test qui se contente d'importer ne tue aucun
mutant (cf. tests_de_source_ne_tuent_aucun_mutant, 2026-08-18).

Le coeur de la regle d'abstention est teste SANS torch, via la fonction pure
decide_from_rates : c'est la regle qu'il faut proteger, pas le reseau.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_routing_decision as rd  # noqa: E402
import forge_snn_router as sr  # noqa: E402


# ── contrat de decision ─────────────────────────────────────────────────────


def test_marge_vient_des_alternatives_pas_d_un_champ_libre():
    d = rd.RoutingDecision(route="provider", provider="claude", confidence=0.9,
                           alternatives=[("claude", 0.90), ("groq", 0.20)],
                           level="L1", next_level="L3")
    assert d.margin == pytest.approx(0.70)
    seul = rd.RoutingDecision(route="provider", provider="claude",
                              alternatives=[("claude", 0.4)], level="L1")
    # Un seul candidat : rien ne le conteste.
    assert seul.margin == 1.0


def test_escalade_decide_sur_l_incertitude_pas_sur_la_confiance():
    """Le cas qui justifie d'avoir DEUX champs : confiant ET incertain."""
    sur = rd.RoutingDecision(route="provider", provider="claude", confidence=0.9,
                             uncertainty=0.1, level="L1", next_level="L3")
    ambigu = rd.RoutingDecision(route="provider", provider="claude", confidence=0.9,
                                uncertainty=0.8, level="L1", next_level="L3")
    assert not sur.should_escalate()
    assert ambigu.should_escalate()
    # Meme confiance, verdicts opposes : 1-confidence n'aurait pas suffi.
    assert sur.confidence == ambigu.confidence


def test_un_next_level_qui_ne_monte_pas_est_refuse():
    """Sans cette garde, une cascade peut boucler entre deux etages."""
    with pytest.raises(ValueError):
        rd.RoutingDecision(route="x", level="L3", next_level="L1")
    with pytest.raises(ValueError):
        rd.RoutingDecision(route="x", level="L3", next_level="L3")
    with pytest.raises(ValueError):
        rd.RoutingDecision(route="x", level="LX")


def test_confidence_et_uncertainty_sont_bornees():
    d = rd.RoutingDecision(route="x", confidence=5.0, uncertainty=-3.0, level="L0")
    assert d.confidence == 1.0 and d.uncertainty == 0.0


def test_abstention_dit_ou_aller_ensuite():
    a = rd.abstention("L1", "L3", "taux trop bas", source="snn")
    assert a.route == "abstain"
    assert a.provider is None
    assert a.uncertainty == 1.0
    assert a.next_level == "L3"


def test_une_etiquette_rendue_comme_provider_devient_une_abstention():
    """Regression du 2026-08-20 : route_with_dt rendait "orchestrator",
    l'etiquette de systeme prise pour un provider."""
    bon = rd.from_legacy_tuple("claude", 1.0, "hard", known_providers=["claude"])
    assert bon.route == "provider" and bon.level == "L0"
    faux = rd.from_legacy_tuple("orchestrator", 0.9, "spike",
                                known_providers=["claude", "groq"])
    assert faux.route == "abstain"
    assert faux.provider is None


def test_to_dict_expose_la_marge_calculee():
    d = rd.RoutingDecision(route="provider", provider="a", level="L1",
                           alternatives=[("a", 0.8), ("b", 0.3)])
    assert d.to_dict()["margin"] == pytest.approx(0.5)


# ── regle d'abstention de l'etage SNN (sans torch) ──────────────────────────

PROVIDERS_T = ["p0", "p1", "p2", "p3"]


def _rates(vals):
    return np.array(vals, dtype=np.float32)


def test_taux_dominant_et_net_donne_un_provider():
    d = sr.decide_from_rates(_rates([0.95, 0.20, 0.10, 0.05]),
                             _rates([0.01, 0.01, 0.01, 0.01]), PROVIDERS_T)
    assert d.route == "provider"
    assert d.provider == "p0"
    assert d.level == "L1" and d.next_level == "L3"


def test_taux_trop_bas_donne_une_abstention():
    """Le defaut mesure le 2026-08-21 : avec MIN_RATE=0.15, une entree vide
    rendait un provider a 0.171. Le seuil doit trancher."""
    d = sr.decide_from_rates(_rates([0.30, 0.02, 0.01, 0.01]),
                             _rates([0.01, 0.01, 0.01, 0.01]), PROVIDERS_T)
    assert d.route == "abstain"
    assert "trop bas" in d.reason


def test_deux_candidats_a_egalite_donnent_une_abstention():
    """Un score eleve dont le second est a egalite designe une FAMILLE de
    providers, pas un provider."""
    d = sr.decide_from_rates(_rates([0.95, 0.94, 0.10, 0.05]),
                             _rates([0.01, 0.01, 0.01, 0.01]), PROVIDERS_T)
    assert d.route == "abstain"
    assert "marge insuffisante" in d.reason
    # L'abstention porte quand meme les candidats : l'appelant peut les lire.
    assert d.alternatives[0][0] == "p0" and d.alternatives[1][0] == "p1"


def test_un_train_de_spikes_instable_augmente_l_incertitude():
    """sigma = ce que l'encodage de Poisson laisse d'indetermine."""
    stable = sr.decide_from_rates(_rates([0.95, 0.20, 0.10, 0.05]),
                                  _rates([0.001, 0.01, 0.01, 0.01]), PROVIDERS_T)
    instable = sr.decide_from_rates(_rates([0.95, 0.20, 0.10, 0.05]),
                                    _rates([0.60, 0.01, 0.01, 0.01]), PROVIDERS_T)
    assert instable.uncertainty > stable.uncertainty


def test_les_seuils_sont_ceux_qui_ont_ete_calibres():
    """Garde-fou : ces valeurs viennent de calibrate_thresholds (LOO 55 plis,
    backend builtin). Les changer sans recalibrer casse la mesure."""
    assert sr.MIN_RATE == pytest.approx(0.80)
    assert sr.MIN_MARGIN == pytest.approx(0.15)
    assert sr.BACKEND == "builtin"


def test_available_distingue_absent_et_illisible():
    """Trois etats, jamais deux : un False unique confondrait "torch absent"
    et "pas pu regarder"."""
    av = sr.available()
    assert set(av) >= {"torch", "torch_etat", "torch_err", "model_present"}
    assert av["torch_etat"] in ("present", "absent", "illisible_garde_sandbox")
    assert av["torch"] is (av["torch_etat"] == "present")


# ── etage SNN complet (torch requis) ────────────────────────────────────────

besoin_torch = pytest.mark.skipif(not sr._TORCH, reason="torch indisponible ici")


@besoin_torch
def test_deux_appels_identiques_rendent_la_meme_decision():
    """L'encodage de Poisson rend le forward non reproductible ; un routeur qui
    change d'avis sans que rien ne change serait un defaut."""
    r = sr.SNNRouter()
    r.fit_from_corpus(epochs=5)
    prompt, tt = "analyse ce module python et corrige les bugs", "analyze_code"
    d1, d2 = r.predict(prompt, tt), r.predict(prompt, tt)
    assert d1.provider == d2.provider
    assert d1.confidence == pytest.approx(d2.confidence)
    assert d1.route == d2.route


@besoin_torch
def test_un_routeur_non_entraine_s_abstient():
    d = sr.SNNRouter().predict("peu importe", "")
    assert d.route == "abstain"
    assert d.next_level == "L3"


@besoin_torch
def test_des_features_hors_zero_un_sont_refusees():
    """Un rate-codage hors [0,1] produit des probabilites de spike aberrantes
    que torch.rand_like ne signale pas."""
    r = sr.SNNRouter()
    X = np.full((4, r.feature_dim), 3.0, dtype=np.float32)
    with pytest.raises(ValueError):
        r.fit(X, np.zeros(4, dtype=np.int64), epochs=1)


@besoin_torch
def test_le_backend_est_fige_et_persiste(tmp_path):
    """Regression du 2026-08-21 : la structure du reseau dependait de la
    presence de snntorch, et les poids ne se rechargeaient pas d'un
    interpreteur a l'autre."""
    import torch

    r = sr.SNNRouter()
    assert r.backend == "builtin"
    r.fit_from_corpus(epochs=2)
    p = tmp_path / "m.pt"
    r.save(p)
    assert torch.load(str(p), weights_only=False)["backend"] == "builtin"

    r2 = sr.SNNRouter()
    assert r2.load(p) is True

    # Un modele d'un autre backend doit etre REFUSE, pas charge de travers.
    blob = torch.load(str(p), weights_only=False)
    blob["backend"] = "snntorch"
    torch.save(blob, str(p))
    assert sr.SNNRouter().load(p) is False


@besoin_torch
def test_un_modele_d_un_autre_espace_de_features_est_refuse(tmp_path):
    import torch

    r = sr.SNNRouter()
    r.fit_from_corpus(epochs=2)
    p = tmp_path / "m.pt"
    r.save(p)
    blob = torch.load(str(p), weights_only=False)
    blob["feature_dim"] = r.feature_dim + 7
    torch.save(blob, str(p))
    assert sr.SNNRouter().load(p) is False


@besoin_torch
def test_load_d_un_fichier_absent_rend_false_sans_lever(tmp_path):
    assert sr.SNNRouter().load(tmp_path / "nexiste_pas.pt") is False
