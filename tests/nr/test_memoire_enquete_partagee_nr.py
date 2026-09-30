"""NR — la memoire d'enquete voyage avec l'outil, et revient des contributeurs.

Mesure du 2026-09-19. `tools/forge_symptom_index.py` est publie dans le dist ;
sa memoire, `sandbox/enquetes_index.json`, n'est meme pas suivie par git. Un
contributeur recevait donc un outil de memoire VIDE : a toute question il
repondait « terrain neuf », ce qui est un FAUX NEGATIF et non une absence.

Ce que le depot a deja paye pour ce defaut, chez l'owner qui avait pourtant
l'index : l'enquete du 2026-07-26 sur des heartbeats `never_read` a ete
ENTIEREMENT REFAITE le 29/07 — trois hypotheses fausses, quatre redemarrages.

Le besoin est BIDIRECTIONNEL, et c'est lui qui dicte le format : un contributeur
LIT cette memoire, puis renvoie la sienne dans sa PR ; en edge, N instances
accumulent chacune la leur. D'ou JSONL (git fusionne ligne a ligne, la ou un
JSON monolithique de 700 Ko produit un conflit des que deux personnes ajoutent
une enquete), tri stable (meme donnee -> meme diff), et un champ `origine`.

CE TEST VERROUILLE TROIS PROPRIETES, dans cet ordre d'importance :
  1. le fichier publie ne contient AUCUNE donnee personnelle ;
  2. un contributeur SANS index local obtient quand meme des reponses ;
  3. les lecteurs passent par la MEME fonction de chargement — il y en avait
     trois, chacun avec son chemin en dur, et n'en brancher qu'un aurait
     reproduit le motif « deux chemins pour une capacite, un seul lit la
     politique », deja paye dans ce depot.
"""

import json
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
PARTAGE = RACINE / "docs" / "enquetes_partagees.jsonl"

for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SI = pytest.importorskip("tools.forge_symptom_index")

# Le controle est ECRIT ICI, separement des regles de remplacement de l'outil :
# un filtre qui se verifie avec ses propres motifs ne trouve que ce qu'il sait
# deja remplacer.
_INTERDITS = (
    ("adresse de courriel", re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)),
    ("chemin de profil Windows", re.compile(r"[Cc]:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9_.]+")),
    ("adresse IP privee", re.compile(r"\b(?:10|127|192\.168)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")),
    ("lettre de lecteur locale", re.compile(r"\b[D-Zd-z]:[\\/]{1,2}[A-Za-z0-9_]")),
)


@pytest.fixture(scope="module")
def corps():
    if not PARTAGE.is_file():
        pytest.skip("memoire partagee pas encore publiee")
    return PARTAGE.read_text(encoding="utf-8")


def test_aucune_donnee_personnelle_dans_le_fichier_publie(corps):
    """LA PROPRIETE QUI PRIME. Publier « presque propre » est pire que ne pas
    publier : ca se relit comme verifie."""
    trouves = [f"{nom} x{len(rx.findall(corps))}" for nom, rx in _INTERDITS if rx.search(corps)]
    assert not trouves, f"donnees personnelles dans la memoire publiee : {trouves}"


def test_une_ligne_par_enquete_et_json_valide(corps):
    """Le format de fusion : une ligne = une enquete. Un JSON multi-lignes
    rouvrirait les conflits de merge que ce format existe pour eviter."""
    lignes = [l for l in corps.splitlines() if l.strip()]
    assert lignes, "memoire partagee vide"
    for i, l in enumerate(lignes[:400], 1):
        try:
            r = json.loads(l)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"ligne {i} n'est pas un JSON autonome : {type(e).__name__}")
        assert {"enquete", "pieges", "origine"} <= set(r), f"ligne {i} : champs manquants"


def test_le_tri_est_stable(corps):
    """Sans tri, deux exports de la meme donnee donnent des diffs differents et
    la revue d'une PR devient illisible."""
    cles = [(json.loads(l).get("date", ""), json.loads(l).get("enquete", ""))
            for l in corps.splitlines() if l.strip()]
    assert cles == sorted(cles), "les enquetes ne sont pas triees : le diff sera instable"


def test_un_contributeur_sans_index_local_obtient_des_reponses(monkeypatch):
    """LE CAS DU DIST. C'est la raison d'etre de tout ce dispositif."""
    if not PARTAGE.is_file():
        pytest.skip("memoire partagee pas encore publiee")
    monkeypatch.setattr(SI, "INDEX", RACINE / "sandbox" / "_index_absent_pour_ce_test.json")
    idx = SI.charger_index()
    assert idx["sessions"], (
        "sans index local, la memoire est vide : un contributeur du dist "
        "recevrait « terrain neuf » a toute question"
    )
    assert any(s.startswith("partage:") for s in idx["sources"]), idx["sources"]


def test_l_union_ne_duplique_pas_les_enquetes():
    """L'owner publie DEPUIS son local : les deux sources se recouvrent. Sans
    deduplication, chaque enquete compterait double et les rappels seraient
    servis en double."""
    idx = SI.charger_index()
    ids = [s.get("session") for s in idx["sessions"]]
    assert len(ids) == len(set(ids)), "des enquetes apparaissent en double dans l'union"


def test_une_source_illisible_est_DITE_et_non_avalee(monkeypatch, tmp_path):
    """« je n'ai pas pu lire » n'est pas « il n'y a rien » — la distinction que
    la constitution semantique impose."""
    casse = tmp_path / "casse.jsonl"
    casse.write_text("{ceci n'est pas du json\n", encoding="utf-8")
    monkeypatch.setattr(SI, "PARTAGE", casse)
    idx = SI.charger_index()
    assert idx["illisibles"], "une source illisible passe pour une source vide"


def test_les_lecteurs_passent_par_la_meme_fonction():
    """Trois lecteurs existaient, chacun avec son chemin en dur. N'en brancher
    qu'un laisserait les autres aveugles chez un contributeur."""
    import ast

    for rel in ("tools/hook_recon_first.py", "tools/forge_symptom_index.py"):
        src = (RACINE / rel).read_text(encoding="utf-8")
        assert "charger_index" in src, f"{rel} n'utilise pas la source unique"
        ast.parse(src)  # et le fichier reste parsable

    # Le hook ne doit plus relire le fichier local par un chemin en dur.
    hook = (RACINE / "tools" / "hook_recon_first.py").read_text(encoding="utf-8")
    assert "enquetes_index.json" not in hook, (
        "hook_recon_first relit encore l'index local en dur : chez un "
        "contributeur du dist, ce fichier n'existe pas et le garde serait aveugle"
    )
