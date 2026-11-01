"""NR 30/10 : l'evenement « STATUT running -> done » du moniteur des delegations porte la LIVRAISON.

Mesure : une tache AGY affichee « done » avait son commit REFUSE par l'executeur ; une tache GLM affichee « failed »
avait ecrit 2 fichiers. Il fallait lire tasks.db a la main. La livraison vient de la fonction CANONIQUE de l'executeur
(forge_task_executor._statut_livraison), jamais d'un classement reinvente ; illisible -> ILLISIBLE, jamais rien.
Un rendu precedent (GLM, 4c2ed6899) modifiait la vue instantanee, pas la ligne d'evenement lue par l'owner.
"""
from nokido_agent.tools import forge_job_watch_cli as W


def _ev(statut_apres, result):
    avant = {"t1": {"agent": "ANTIGRAVITY", "statut": "running"}}
    apres = {"t1": {"agent": "ANTIGRAVITY", "statut": statut_apres, "result": result}}
    return [e for e in W.transitions(avant, apres) if e["genre"] == "STATUT"][0]


def test_commit_refuse_se_lit_needs_human():
    e = _ev("done", "[effet observe] commits produits : 0 ; fichiers non commites : 2 | {...}\n"
                    "[executeur] commit executeur REFUSE : reecriture destructrice de x.md")
    assert e["livraison"] == "NEEDS_HUMAN"
    assert "[NEEDS_HUMAN]" in W.ligne_evenement(e)


def test_livraison_reussie_se_lit_success():
    e = _ev("done", "[effet observe] commits produits : 1 (a..b) ; fichiers non commites : 0 | OK_DONE")
    assert e["livraison"] == "SUCCESS"


def test_travail_inacheve_preserve_se_lit_partiel():
    """30/10 job_84c166a1 : session AGY en echec, travail commite « INACHEVE a relire » par l'executeur -> affiche
    [SUCCESS] ; c'est LIVRE mais A RELIRE : PARTIEL (ni succes propre, ni echec)."""
    e = _ev("done", "[effet observe] commits produits : 1 (a..b) ; fichiers non commites : 0 | ... OK_DONE\n"
                    "[executeur] travail INACHEVE preserve : commit executeur de 2 fichier(s) : chore(agy): INACHEVE")
    assert e["livraison"] == "PARTIEL"


def test_rien_produit_se_lit_failure():
    """30/10 job_9b5d2a58 : claude -p « Not logged in », l'executeur ecrit [RIEN PRODUIT] -- et la tache sortait
    [SUCCESS]. Une reponse sans effet n'est pas livree : FAILURE."""
    e = _ev("done", "[effet observe] commits produits : 0 (a..a) ; fichiers non commites : 0 ; [RIEN PRODUIT] "
                    "(RIEN_PRODUIT) ni commit ni fichier, et aucun artefact pointe : une reponse sans effet n'est pas "
                    "livree | Not logged in")
    assert e["livraison"] == "FAILURE"


def test_status_code_explicite_prime():
    e = _ev("done", '{"intent":"NEED_CLARIFY","status_code":"CANCELLED","pointer_ref":"x"}')
    assert e["livraison"] == "CANCELLED"


def test_resultat_absent_se_dit_illisible():
    e = _ev("failed", None)
    assert "ILLISIBLE" in W.ligne_evenement(e)


def test_passage_en_cours_sans_livraison():
    avant = {"t1": {"agent": "ANTIGRAVITY", "statut": "pending"}}
    apres = {"t1": {"agent": "ANTIGRAVITY", "statut": "running", "result": None}}
    e = W.transitions(avant, apres)[0]
    assert "livraison" not in e and "[" not in W.ligne_evenement(e).split("STATUT", 1)[1]
