"""Non-regression : la veille APPROFONDIE ne coupe pas le contenu a la source.

DEFAUT MESURE le 2026-09-12, sur demande owner — le contrat de non-troncature
devait aussi valoir pour le workflow via docker searxng et crawl4ai.

L'audit precedent ne couvrait que `forge_veille*`, `forge_ingest*`,
`forge_retrieval*` et le moteur RAG. Il a donc rate toute la couche AMONT : celle
qui RECUPERE le contenu avant qu'il atteigne l'ingestion.

Ce qui s'y trouvait :

  `forge_web._extract_sync`   les TROIS chemins d'extraction coupaient a 4000
                              (trafilatura, bs4, newspaper3k), et le repli bs4
                              cumulait `paragraphs[:40]`. Une page de 30 000
                              caracteres perdait 87 % de son contenu.
  `forge_source_discovery`    l'artefact JSONL persistait 4 000 caracteres tout
                              en hashant le contenu COMPLET — le hash ne
                              correspondait pas au contenu conserve.
  `forge_research_agent`      le fetch coupait a 6000, et son `except:` NU
                              rendait "" : page injoignable indiscernable d'une
                              page vide.

🔑 POURQUOI CE DEFAUT AVAIT SURVECU A LA MESURE PRECEDENTE. Le test du pic — qui
compare l'effectif d'une longueur a celui de ses voisines — a prouve les
troncatures EN BASE (2000 : ratio 159,7 sur 13 896 chunks). Il est AVEUGLE a
celle-ci : le chunker redecoupe les 4 000 survivants en blocs de ~800, donc aucun
chunk ne porte la longueur de la coupe et aucun pic n'apparait.

    UNE TRONCATURE AMONT NE LAISSE AUCUNE SIGNATURE EN AVAL.

C'est la lecon de portee du jour : mesurer la sortie d'une chaine ne dit rien de
ce qui a ete jete a son entree. Le garde doit donc etre STRUCTUREL (lire le code
de la couche amont), puisqu'aucune mesure du corpus ne peut le remplacer.

Une borne reste permise si elle DIT ce qu'elle ecarte — la fenetre d'un modele
est une contrainte reelle. On interdit le silence, pas la limite.

Ecrit apres les correctifs de `82d2715e3`, pour empecher leur retour.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

# La couche AMONT : ce qui recupere du contenu avant l'ingestion.
COUCHE_AMONT = [
    RACINE / "app" / "forge_web.py",
    RACINE / "app" / "forge_research_agent.py",
    RACINE / "tools" / "forge_source_discovery.py",
]

# Un contenu recupere se reconnait a ces noms.
NOMS_CONTENU = ("text", "texte", "content", "contenu", "html", "body", "corps",
                "article", "markdown", "page", "raw")

# En deca, la borne vise un extrait declare (snippet) ou un libelle.
SEUIL_CONTENU = 1000

# Marques qui rendent une borne ADMISSIBLE : elle se declare.
MARQUES_PARLANTES = ("tronque", "ecarte", "n est pas", "n'est pas", "cap ",
                     "snippet", "extrait", "apercu")


def _sources():
    for p in COUCHE_AMONT:
        assert p.exists(), f"module de la couche amont introuvable : {p}"
        yield p


def _bornes_de_contenu(p: Path):
    texte = p.read_text(encoding="utf-8", errors="replace")
    lignes = texte.splitlines()
    arbre = ast.parse(texte)
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)):
            continue
        hi = n.slice.upper
        if not (isinstance(hi, ast.Constant) and isinstance(hi.value, int)):
            continue
        if hi.value < SEUIL_CONTENU:
            continue
        cible = ast.unparse(n.value)[:70].lower()
        if not any(m in cible for m in NOMS_CONTENU):
            continue
        fen = "\n".join(lignes[max(0, n.lineno - 6): n.lineno + 4]).lower()
        parlante = any(k in fen for k in MARQUES_PARLANTES)
        yield {"ligne": n.lineno, "coupe_a": hi.value, "cible": cible,
               "parlante": parlante}


@pytest.mark.parametrize("chemin", list(_sources()), ids=lambda p: p.name)
def test_aucune_borne_MUETTE_sur_du_contenu_recupere(chemin):
    """Le coeur. Une borne sur du contenu recupere doit dire ce qu'elle jette,
    sinon le contenu disparait sans laisser de trace nulle part."""
    muettes = [f"L{b['ligne']} coupe {b['cible']} a {b['coupe_a']}"
               for b in _bornes_de_contenu(chemin) if not b["parlante"]]
    assert not muettes, (
        f"{chemin.name} : borne(s) MUETTE(s) sur du contenu recupere — "
        + " | ".join(muettes)
        + ". Une troncature a la source est invisible en aval : le chunker "
          "redecoupe ce qui reste, donc aucune mesure du corpus ne la revelera."
    )


def test_l_extracteur_web_ne_borne_plus_aucun_de_ses_trois_chemins():
    """`_extract_sync` avait TROIS sorties, toutes coupees a 4000. Un correctif
    partiel — deux chemins sur trois — laisserait le defaut vivant par le repli."""
    src = (RACINE / "app" / "forge_web.py").read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    fn = None
    for n in ast.walk(arbre):
        if isinstance(n, ast.FunctionDef) and n.name == "_extract_sync":
            fn = n
            break
    assert fn is not None, "_extract_sync introuvable — le chemin d'extraction a change"

    fautifs = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Subscript):
            if isinstance(n.value.slice, ast.Slice):
                fautifs.append(n.lineno)
    assert not fautifs, (
        f"_extract_sync rend encore du contenu tranche aux lignes {fautifs} : "
        "une page de 30 000 caracteres y perdait 87 % de son contenu"
    )


def test_le_repli_bs4_ne_garde_plus_seulement_le_haut_de_la_page():
    """`paragraphs[:40]` gardait les 40 PREMIERS paragraphes : menus, titre,
    introduction — et rien du corps technique. Meme biais que le plafond du sweep,
    qui gardait le debut de chaque corpus."""
    src = (RACINE / "app" / "forge_web.py").read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    for n in ast.walk(arbre):
        if not (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)):
            continue
        if "paragraph" not in ast.unparse(n.value).lower():
            continue
        hi = n.slice.upper
        if isinstance(hi, ast.Constant) and isinstance(hi.value, int):
            raise AssertionError(
                f"L{n.lineno} : le repli bs4 ne garde que {hi.value} paragraphes — "
                "une documentation technique en compte des centaines"
            )


def test_un_fetch_qui_echoue_ne_se_tait_pas():
    """Un `except:` nu rendant "" fait passer une page INJOIGNABLE pour une page
    SANS CONTENU. UNKNOWN lu comme NO, dans la couche qui alimente la veille."""
    src = (RACINE / "app" / "forge_research_agent.py").read_text(
        encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    nus = [n.lineno for n in ast.walk(arbre)
           if isinstance(n, ast.ExceptHandler) and n.type is None]
    assert not nus, (
        f"`except:` NU aux lignes {nus} : il avale jusqu'a KeyboardInterrupt et "
        "rend un resultat vide indiscernable d'une absence de contenu"
    )
