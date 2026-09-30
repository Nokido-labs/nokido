"""NR -- le tableau de bord LLM cite TOUS les fournisseurs a clef du catalogue.

DEMANDE OWNER (2026-09-18) : « doit referencer TOUTES les inscriptions par clef
compatibles avec Nokido, il en manque beaucoup ».

MESURE qui l'a confirme : le catalogue `tools/forge_provider_catalogue.py` porte
vingt-deux fournisseurs interrogeables par clef ; la page en citait treize. NEUF
manquaient -- together, deepinfra, siliconflow, zai, mammouth, voyage, jina,
llamacpp, litellm -- non pas parce qu'ils etaient indisponibles, mais parce que
la page portait sa propre liste, ecrite a la main, a cote de la source.

CE QUE CE NR FIGE : une page qui documente un catalogue ne peut pas en ignorer
une partie. Le jour ou le catalogue gagne un fournisseur, ce test echoue et
nomme celui qui manque -- sans quoi la divergence recommence en silence, ce qui
est exactement ce qui vient d'etre paye.

CE QU'IL NE FIGE PAS : ni l'ordre, ni la mise en forme, ni les liens. Il verifie
la COUVERTURE, pas le style -- un NR qui fige une presentation empeche de la
corriger.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
PAGE = RACINE / "tools" / "llm-dashboard.html"
CATALOGUE = RACINE / "tools" / "forge_provider_catalogue.py"


def _catalogue():
    spec = importlib.util.spec_from_file_location("_fpc_nr", CATALOGUE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def page() -> str:
    assert PAGE.exists(), (
        "%s introuvable : sans la page, ce test passerait sur du vide" % PAGE.name)
    return PAGE.read_text(encoding="utf-8", errors="replace").lower()


def test_le_catalogue_est_lisible_et_non_vide():
    """L'instrument avant la mesure : un catalogue vide rendrait tout vert."""
    f = _catalogue().FOURNISSEURS
    assert len(f) >= 15, (
        "catalogue anormalement court (%d) : la comparaison suivante ne "
        "prouverait rien" % len(f))


def test_chaque_fournisseur_du_catalogue_est_cite_dans_la_page(page):
    absents = [nom for nom, _var, _url in _catalogue().FOURNISSEURS
               if nom.lower() not in page]
    assert not absents, (
        "%d fournisseur(s) du catalogue ne figurent pas dans le tableau de bord : "
        "%s. La page porte une liste a cote de la source au lieu de la refleter."
        % (len(absents), ", ".join(absents)))


def test_chaque_variable_de_clef_est_citee(page):
    """Sans la variable, on sait qu'un fournisseur existe mais pas quoi renseigner.

    `ollama` est exempte : il n'a pas de variable au catalogue (champ vide), et
    exiger une chaine vide rendrait ce test toujours vert.
    """
    manquantes = [var for _nom, var, _url in _catalogue().FOURNISSEURS
                  if var and var.lower() not in page]
    assert not manquantes, (
        "variables de clef absentes de la page : %s" % ", ".join(manquantes))


def test_aucune_clef_n_est_affichee(page):
    """Contre-epreuve : documenter des variables ne doit pas devenir les DIVULGUER.

    On cherche les formes de secrets connues des fournisseurs listes. Ce test
    doit rester vert : c'est un garde, pas une mesure de couverture.
    """
    for motif in ("sk-", "gsk_", "hf_", "xai-", "csk-"):
        # Le motif seul est trop court pour trancher ; on exige qu'il soit suivi
        # d'une longue suite de caracteres de secret, ce qu'un nom de variable
        # documente n'a jamais.
        import re
        trouve = re.search(re.escape(motif) + r"[a-z0-9]{24,}", page)
        assert not trouve, (
            "la page contient ce qui ressemble a une clef (%s...) : une page de "
            "documentation ne doit jamais en porter" % motif)


def test_les_exclusions_sont_NOMMEES_et_pas_silencieuses(page):
    """Le catalogue declare ce qu'il met hors perimetre, avec un motif.

    Une absence expliquee n'est pas un oubli ; une absence muette, si. On exige
    qu'au moins la moitie des exclusions declarees soit mentionnee, pour que le
    lecteur sache que le vide est un choix.
    """
    exclus = list(_catalogue().HORS_PERIMETRE)
    cites = [e for e in exclus if e.split("_")[0].lower() in page]
    assert len(cites) >= max(1, len(exclus) // 2), (
        "les exclusions du catalogue ne sont pas dites dans la page (%d/%d) : "
        "un lecteur ne peut pas distinguer un choix d'un oubli"
        % (len(cites), len(exclus)))
