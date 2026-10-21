# -*- coding: utf-8 -*-
"""NR (audit pair 19/10, affirmation 3 verifiee par AGY 1f2afef04) : PARLER d'une erreur n'est pas ETRE une erreur.

Mesure : ConfidenceScorer forcait le score a 0.0 des que « erreur|error|exception|traceback|timeout » ou « aucun
resultat » apparaissait N'IMPORTE OU dans les 200 premiers caracteres -- un diagnostic juste (« L'erreur provient
d'un debordement... ») tombait a 0, sous SPIN_THRESHOLD, et declenchait une escalade inutile (quota, latence). Ces
motifs ne s'appliquent plus qu'a une reponse qui COMMENCE comme une erreur (« Error: », « Traceback (... »,
« TimeoutError: », « Aucun resultat »). Le refus (deja ancre en tete) et la penalite de brievete ne changent pas
(calibration : a mesurer, pas a decider ici).
"""
from nokido_agent.app.forge_metacognition_gate import ConfidenceScorer

S = ConfidenceScorer()
LONG = " Il faut verifier la borne superieure et ajouter un test qui couvre la valeur maximale du compteur." * 2


def test_un_diagnostic_qui_parle_d_erreur_n_est_pas_un_echec():
    for rep in ("L'erreur provient d'un debordement d'entier a la ligne 42 du parseur." + LONG,
                "Une TimeoutError survient lorsque le serveur distant ne repond pas dans le delai de 30 s." + LONG,
                "La recherche n'a donné aucun résultat parce que l'index est vide ; reconstruisez-le." + LONG):
        assert S.score(rep).raw_score > 0.0, rep[:50]


def test_une_reponse_qui_est_une_erreur_reste_a_zero():
    for rep in ("Error: connection refused by host",
                "Traceback (most recent call last):\n  File \"x.py\", line 1",
                "TimeoutError: le fournisseur n'a pas repondu",
                "Aucun résultat.",
                "Aucun resultat.",
                "Je ne peux pas repondre a cette question."):
        assert S.score(rep).raw_score == 0.0, rep[:40]
