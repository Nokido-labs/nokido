# -*- coding: utf-8 -*-
"""Non-regression — le routeur ne cite que des slots qui existent, et le chemin
OpenAI-compat se DECLARE au lieu de se deduire d'un nom.

Deux mesures du 2026-08-28.

1. `nvidia_nim` repondait `[OK]` avec nemotron-3-super-120b-a12b — le plus gros modele
   du parc qui reponde — et n'avait AUCUN slot : appelable a la main, jamais
   choisissable par le routeur, donc absent de toute cascade de raisonnement. Un
   provider peut donc etre parfaitement sain ET invisible pour ce qui decide.

2. Le brancher a bute sur `_is_openai_compat_custom`, qui testait le PREFIXE DU NOM du
   slot (`github_`, `hf_`, `llamacpp_local`). Tout endpoint OpenAI-compat nomme
   autrement tombait dans la branche legacy, ou `api_base` n'est pose que pour les
   providers locaux, et litellm partait sur l'API publique avec un modele inconnu. Le
   seul moyen d'ajouter NIM aurait ete de le NOMMER `hf_*` : mentir sur son identite
   pour obtenir le bon comportement. La propriete se demande a l'organe, elle ne se
   deduit pas de son etiquette.

Hermetique : lecture AST du module, aucun import (donc pas de litellm), aucun reseau.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "app" / "forge_llm_router.py"

# Slots qui parlent a un endpoint OpenAI-compat par un nom historique. Ils restent
# honores par le code ; la liste sert seulement a ne pas exiger d'eux la declaration.
_PREFIXES_HISTORIQUES = ("github_", "hf_")
_NOMS_HISTORIQUES = {"llamacpp_local"}


def _arbre():
    if not SOURCE.exists():
        pytest.skip("forge_llm_router absent de cette copie")
    return ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"), filename=str(SOURCE))


def _slots_et_chaines():
    """(slots: {nom: {cle: litteral}}, chaines: {use_case: [slots]}) lus a l'AST."""
    slots: dict = {}
    chaines: dict = {}
    for node in _arbre().body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        nom = node.targets[0].id if isinstance(node.targets[0], ast.Name) else ""
        if nom == "USE_CASE_CHAINS":
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and isinstance(v, ast.List):
                    chaines[k.value] = [e.value for e in v.elts if isinstance(e, ast.Constant)]
        elif nom == "PROVIDERS":
            for k, v in zip(node.value.keys, node.value.values):
                if not isinstance(k, ast.Constant) or not isinstance(v, ast.Dict):
                    continue
                conf = {}
                for ck, cv in zip(v.keys, v.values):
                    if isinstance(ck, ast.Constant):
                        try:
                            conf[ck.value] = ast.literal_eval(cv)
                        except (ValueError, SyntaxError):
                            conf[ck.value] = "<non-litteral>"
                slots[k.value] = conf
    return slots, chaines


def test_le_lecteur_trouve_quelque_chose():
    """Sans ca, tous les tests ci-dessous passeraient sur des dictionnaires vides."""
    slots, chaines = _slots_et_chaines()
    assert len(slots) > 10, "PROVIDERS illisible (%d entrees) — le garde ne garderait rien" % len(slots)
    assert len(chaines) > 5, "USE_CASE_CHAINS illisible — le garde ne garderait rien"


def test_aucune_chaine_ne_cite_un_slot_inexistant():
    """Un slot cite mais non defini est un echec GARANTI a chaque fois que la cascade
    le tire, et il est invisible en lecture : les deux listes vivent loin l'une de
    l'autre dans le fichier."""
    slots, chaines = _slots_et_chaines()
    fantomes = sorted({s for c in chaines.values() for s in c} - set(slots))
    assert not fantomes, (
        "slots cites par une chaine mais absents de PROVIDERS — la cascade les tirera "
        "et echouera : %s" % fantomes)


def test_un_modele_fort_reste_routable_en_raisonnement():
    """Le defaut paye : un provider sain, avec sa cle, qu'aucune chaine ne peut choisir.

    On n'exige pas nvidia_nemotron_super par son NOM — un remplacant plus gros serait
    legitime. On exige qu'il reste, en tete des cascades de raisonnement, au moins un
    slot de gros calibre declare pour ce role."""
    slots, chaines = _slots_et_chaines()
    for uc in ("reasoning", "debate", "strategy"):
        chaine = chaines.get(uc)
        assert chaine, "cascade '%s' absente" % uc
        forts = [s for s in chaine[:3]
                 if uc in (slots.get(s, {}).get("use_case") or [])]
        assert forts, (
            "aucun des trois premiers slots de '%s' ne se declare pour ce use_case : "
            "la cascade tirera des modeles qui n'ont pas ete choisis pour ca (%s)"
            % (uc, chaine[:3]))


# NOTE — un test « tout slot avec base_url doit declarer openai_compat » a ete ECRIT
# puis RETIRE le 2026-08-28, dans l'heure. Il criait sur cinq slots preexistants et
# fonctionnels (lmstudio_native, xai_grok3, xai_grok3_mini, sambanova_llama_405b,
# sambanova_llama_70b) : la liste des prefixes litellm que j'y avais mise etait
# incomplete, et de toute facon un prefixe ne dit rien du provider — `nvidia/` dans
# `nvidia/nemotron-3-super-120b-a12b` est un namespace de MODELE, pas un provider.
# Un garde qui crie a faux se fait desarmer, et il aurait desarme les deux qui suivent.
# Ce qui compte est teste autrement : le code consulte la declaration (ci-dessous) et
# un modele fort reste en tete des cascades (ci-dessus).


def test_le_slot_declare_ce_dont_il_a_besoin():
    """Un slot qui SE DECLARE openai_compat doit porter la base_url qui va avec,
    sinon la declaration est decorative."""
    slots, _ = _slots_et_chaines()
    incomplets = [n for n, c in slots.items()
                  if c.get("openai_compat") and not c.get("base_url")]
    assert not incomplets, (
        "slots `openai_compat` sans base_url : le drapeau ne mene nulle part -- %s"
        % incomplets)


def test_le_code_lit_la_declaration():
    """Garde d'alignement : la branche openai-compat doit consulter la CONFIG.

    Si quelqu'un revient a un test sur le seul prefixe du nom, le drapeau declare
    ci-dessus deviendrait decoratif et le defaut reviendrait en silence."""
    src = SOURCE.read_text(encoding="utf-8", errors="replace")
    # L'ASSIGNATION, pas la premiere mention : le nom apparait d'abord dans le
    # commentaire d'un slot, et viser `index()` faisait lire le mauvais bloc — defaut
    # de ce test, corrige le jour meme.
    marqueur = "_is_openai_compat_custom ="
    assert marqueur in src, "branche openai-compat introuvable (renommee ?)"
    debut = src.index(marqueur)
    bloc = src[debut:debut + 400]
    assert "openai_compat" in bloc.replace("_is_openai_compat_custom", ""), (
        "le choix du chemin openai-compat ne consulte plus la configuration du slot : "
        "il est redevenu une deduction sur le nom")
