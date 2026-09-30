"""Gardes d'EFFET pour `tools/forge_audit_copies_hors_depot.py`.

Cet outil sert a decider si un fichier hors depot est dangereux. Un audit qui se
trompe de classement est pire qu'aucun audit : il fait supprimer ce qui sert, ou
rassure sur ce qui nuit. Les proprietes figees ici sont celles dont le verdict depend.

1. **Le regex couvre tous les VOLUMES.** La premiere version codait `C:` en dur et
   serait passee a cote de `D:\\Temp` — un audit borgne rend un « 0 trouve » qui se
   lit comme « rien a signaler ».
2. **`confronter` distingue ABSENT, ILLISIBLE et DIVERGENTE.** Trois etats, jamais
   deux : un fichier qu'on ne peut pas lire n'est pas un fichier propre. Et un
   lanceur qui pointe un fichier INEXISTANT n'est pas rassurant non plus — il echoue
   en silence si personne ne verifie son code retour.
3. **L'index du depot est construit UNE SEULE FOIS.** La premiere version rebalayait
   tout le depot par fichier confronte : 13,3 Mo/s d'I/O pendant plus de cinq
   minutes, le meme motif de re-scan que celui corrige ailleurs dans la session.
"""

import re
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : os.walk racine (code appele)
#   (l.147)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _mod():
    import forge_audit_copies_hors_depot as A  # noqa: PLC0415

    return A


def test_le_motif_couvre_tous_les_volumes():
    """`C:` code en dur rendrait l'audit borgne sur D:, E:, etc."""
    A = _mod()
    for chemin in (r"C:\tmp\x.py", "C:/tmp/x.py", r"D:\Temp\x.py", "D:/temp/x.py",
                   "E:/TMP/x.py"):
        assert A._REF.search(chemin), "volume non couvert : %s" % chemin
    assert not A._REF.search("/home/user/tmp/x.py"), (
        "un chemin POSIX sans lettre de volume ne doit pas matcher ce motif Windows")


def test_les_racines_auditees_incluent_les_deux_volumes():
    racines = {str(r).lower().replace("\\", "/") for r in _mod().RACINES_HORS_DEPOT}
    assert any("c:/tmp" in r for r in racines), "C:/tmp absent des racines auditees"
    assert any("d:/temp" in r for r in racines), (
        "D:/temp absent : les scratchpads d'agents y vivent, un lancement depuis "
        "cette racine serait aussi grave que depuis C:/tmp")


def test_confronter_distingue_absent_de_illisible(tmp_path):
    """ABSENT n'est pas un verdict rassurant, et ne doit pas etre muet."""
    A = _mod()
    r = A.confronter(str(tmp_path / "nexiste_pas.py").replace("\\", "/"))
    assert "etat" in r, "aucun etat rendu pour un fichier absent"
    assert "ABSENT" in r["etat"], (
        "un lanceur qui pointe dans le vide doit etre NOMME comme tel, pas ignore "
        "(il echoue en silence si personne ne lit son code retour) : %r" % r["etat"])


def test_confronter_detecte_une_copie_divergente(tmp_path):
    """Le coeur de l'outil : dire qu'une copie a derive de son jumeau du depot."""
    A = _mod()
    faux = tmp_path / "forge_audit_copies_hors_depot.py"   # meme NOM qu'un fichier du depot
    faux.write_text("# contenu different du depot\n", encoding="utf-8")
    r = A.confronter(str(faux).replace("\\", "/"))
    assert r.get("jumeau"), (
        "le jumeau du depot n'a pas ete retrouve alors que le nom est identique — "
        "l'index du depot est vide ou mal construit")
    assert "DIVERGENTE" in r.get("etat", ""), (
        "une copie au contenu different doit etre declaree DIVERGENTE, sinon "
        "l'audit rassure sur une copie perimee : %r" % r.get("etat"))


# ---------------------------------------------------------------------------
# PRECISION DU CLASSEMENT — mesurée le 2026-09-14, et elle était inversée.
#
# Sur les 5 références classées « LANCE depuis un chemin hors depot » ce jour-là,
# AUCUNE n'était un vrai défaut, tandis que les DEUX armes réelles
# (`deploy_hub_bundle` et `tmp_copy_bundle`, qui copiaient sans garde depuis
# `C:\tmp`) dormaient dans la catégorie « cité sans contexte d'exécution ».
#
# Un audit qui crie là où il ne faut pas finit ignoré — exactement ce que dit la
# règle déjà consignée sur les gardes : « un garde qui crie à faux se fait
# désarmer, donc un faux positif se corrige tout de suite ».
#
# Deux causes distinctes, deux correctifs :
#   A. les DOCSTRINGS n'étaient pas écartées (3 des 5 faux positifs) — le filtre
#      ne reconnaissait que `#`, `//`, `*` ;
#   B. aucun moyen de DÉCLARER un repli légitime (2 des 5) — or le dépôt a déjà
#      ce patron avec `# muet-ok` pour les chemins d'erreur silencieux.
# ---------------------------------------------------------------------------

def test_une_reference_en_docstring_n_est_pas_un_lancement(tmp_path):
    """Cas réels : `forge_vendor_place` documente son usage CLI,
    `forge_module_census` cite la provenance d'une carte. Personne ne LANCE."""
    A = _mod()
    f = tmp_path / "m.py"
    f.write_text(
        '"""Module.\n\n'
        'Usage : outil.py --src C:/tmp/chose.py\n'
        'La carte est produite par C:/tmp/autre.py + suite.py\n'
        '"""\n'
        'X = 1\n',
        encoding="utf-8")
    assert A.lignes_de_docstring(f.read_text(encoding="utf-8")) >= {3, 4}, (
        "les lignes de docstring ne sont pas reperees"
    )


def test_un_repli_declare_n_est_pas_un_defaut():
    """Le dépôt d'abord, la copie en dernier recours, et elle le DIT.

    `forge_local_pool_wake` fait exactement cela, et son retour nomme la copie
    (« COPIE C:/tmp -- perimee, sans intention »). Le signaler comme un
    lancement fautif, c'est accuser le seul endroit qui se comporte bien.
    """
    A = _mod()
    assert A.repli_declare('    tmp = Path("C:/tmp/x.py")  # repli-hors-depot-ok: dernier recours')
    assert not A.repli_declare('    tmp = Path("C:/tmp/x.py")')


def test_le_marqueur_suit_le_patron_du_depot():
    """`# muet-ok` existe déjà pour les chemins d'erreur : on réutilise la forme,
    on n'invente pas une seconde convention que personne ne connaîtra."""
    assert _mod().MARQUEUR_REPLI.startswith("repli-hors-depot-ok")


def test_le_verdict_distingue_ce_qui_est_grave():
    """Aujourd'hui l'outil rend TOUJOURS 0 : même câblé, il ne garderait rien.

    C'est la « dette de câblage » déjà consignée — un mécanisme présent mais sans
    effet observable n'est pas une sécurité.
    """
    A = _mod()
    assert A.code_de_sortie([]) == 0
    assert A.code_de_sortie([{"certitude": "cite (contexte d'execution non vu)"}]) == 0
    assert A.code_de_sortie([{"certitude": "LANCE"}]) == 1


def test_l_index_du_depot_est_mis_en_cache():
    """Sans cache, chaque confrontation rebalaie le depot entier."""
    A = _mod()
    A._INDEX_DEPOT = None
    premier = A._index_depot()
    assert premier, "index vide : aucun executable trouve dans le depot"
    assert A._index_depot() is premier, (
        "l'index est reconstruit a chaque appel — c'est le re-scan mesure a "
        "13,3 Mo/s pendant cinq minutes le 2026-09-04")
