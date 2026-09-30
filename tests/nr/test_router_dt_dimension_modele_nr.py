"""NR 2026-09-09 — le vecteur de traits du routeur DT doit avoir la dimension que
le modele ENTRAINE attend.

PAYE LE 2026-09-09. `models/llm_router_dt.joblib` porte `n_features_in_ = 36`
(reecrit le 2026-09-08) pendant que `app/forge_llm_router_dt.py` declarait
`FEATURE_DIM = 35`. L'extracteur presentait donc un vecteur de 35 traits a un
arbre qui en exige 36 : l'etage DT de la cascade de routage ne decidait plus, et
RIEN ne le disait. Le desaccord ne vit ni dans le source ni dans le modele — il
vit ENTRE les deux, la ou ni l'un ni l'autre ne se relit. Le module porte bien un
`assert len(FEATURE_NAMES) == FEATURE_DIM`, mais il ne compare que le source a
lui-meme : un instrument qui ne lit que son propre vocabulaire ne voit pas l'ecart.

Le piege qui a coute le diagnostic : `pickle.load` rend `invalid load key '\\x01'`
sur ce fichier, ce qui se lit comme « modele corrompu » alors que c'est simplement
le mauvais lecteur — le bon est `joblib.load`. ILLISIBLE n'est pas ABSENT.

TROIS ETATS, JAMAIS DEUX. Le modele est LU (on compare), ILLISIBLE (on le DIT et
on s'abstient), ou ABSENT (idem). Un modele qu'on n'a pas pu ouvrir ne vaut pas un
accord : le test s'abstient en NOMMANT ce qu'il n'a pas pu voir, il ne verdit pas.

Zero service externe : deux fichiers du depot lus, aucun reseau, aucun import du
module teste (son extracteur joint des providers a l'instanciation — le lire par
AST evite cet effet de bord).
"""

import ast
import pathlib

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
SOURCE = RACINE / "app" / "forge_llm_router_dt.py"
MODELE = RACINE / "models" / "llm_router_dt.joblib"


def _dimension_declaree() -> tuple[int | None, int | None]:
    """Rend (FEATURE_DIM, len(FEATURE_NAMES)) lus par AST, sans importer le module."""
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))
    dim = noms = None
    for noeud in arbre.body:
        if not isinstance(noeud, ast.Assign):
            continue
        for cible in noeud.targets:
            if not isinstance(cible, ast.Name):
                continue
            if cible.id == "FEATURE_DIM" and isinstance(noeud.value, ast.Constant):
                dim = noeud.value.value
            elif cible.id == "FEATURE_NAMES" and isinstance(noeud.value, ast.List):
                noms = len(noeud.value.elts)
    return dim, noms


def test_feature_names_concorde_avec_feature_dim():
    """Accord du source avec lui-meme — dit AVANT l'import, la ou l'assert du
    module ne parle qu'au chargement."""
    dim, noms = _dimension_declaree()
    assert dim is not None, "FEATURE_DIM introuvable dans %s" % SOURCE
    assert noms is not None, "FEATURE_NAMES introuvable dans %s" % SOURCE
    assert noms == dim, (
        "FEATURE_NAMES en porte %d pour FEATURE_DIM = %d : ajouter un trait sans "
        "l'inscrire dans les deux listes casse l'extracteur au premier appel."
        % (noms, dim))


def test_dimension_du_modele_entraine_est_celle_du_source():
    """Accord du source avec le modele REEL — le garde qui manquait le 2026-09-09."""
    if not MODELE.is_file():
        pytest.skip(
            "modele ABSENT (%s) : aucun desaccord constate, aucun accord non plus"
            % MODELE)
    try:
        import joblib
    except Exception as err:  # noqa: BLE001 — l'absence de lecteur se DIT
        pytest.skip(
            "joblib ILLISIBLE (%r) : sans lecteur il n'y a pas de mesure, "
            "et une non-mesure n'est pas un accord" % err)
    try:
        modele = joblib.load(MODELE)
    except Exception as err:  # noqa: BLE001 — cf. le piege pickle en tete de fichier
        pytest.skip(
            "modele ILLISIBLE (%r) : a instruire, ce n'est pas un vert" % err)
    attendu = getattr(modele, "n_features_in_", None)
    if attendu is None:
        pytest.skip(
            "le modele charge (%s) n'expose pas n_features_in_ : rien a comparer"
            % type(modele).__name__)
    dim, _ = _dimension_declaree()
    assert dim == int(attendu), (
        "FEATURE_DIM vaut %s dans le source et le modele entraine attend %d "
        "traits. L'extracteur presente un vecteur que l'arbre refuse : l'etage DT "
        "ne route plus, en silence. Re-entrainer le modele OU aligner le source — "
        "jamais laisser l'ecart, il ne se voit dans aucun des deux fichiers."
        % (dim, int(attendu)))
