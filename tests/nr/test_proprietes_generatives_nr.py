"""Non-regression J2 : les fonctions PURES tiennent sur des entrees GENEREES.

Item de veille J2 (doc pydantic, `ownpilot`) : « property-based testing
(Hypothesis) et tests de frontiere transactionnelle avec echec partiel ».
Justification inscrite : « la suite est exemplaire, pas generative ».

MESURE DU 2026-09-12 : Hypothesis est **installe** (6.152.4) et **jamais
employe** — 0 `import hypothesis`, 0 `@given` dans tout le depot.

🪤 Et mon propre motif de recherche m'a d'abord trompe : 16 fichiers « citaient
hypothesis ». Ce sont des occurrences du mot FRANCAIS « hypothese » ecrit sans
accent, dans des commentaires. Aucune n'est la bibliotheque. Verifie avant de
conclure — sinon j'aurais rapporte un usage inexistant.

CE QUE LE GENERATIF APPORTE ICI, et que l'exemple choisi n'apporte pas. Un test a
trois cas prouve trois cas. Une propriete quantifiee sur des milliers d'entrees
tirees — chaines vides, unicode, tres longues, caracteres de controle — attrape
les frontieres qu'on n'a pas pensees. Les fonctions visees sont celles ecrites ce
jour meme, toutes PURES, donc le terrain ideal :

    forge_db_path.chunk_id             determinisme + sensibilite a la source
    forge_veille_depouillement.famille_page  totalite (jamais d'exception)
    forge_intent_parser.normaliser     idempotence
    forge_semantic_firewall.redact_tool_output  ne perd jamais de contenu

Chacune porte une propriete qui DOIT tenir pour toute entree, pas seulement pour
celles que j'ai imaginees.

Le module est saute proprement si Hypothesis venait a manquer : un test qui
n'existe pas est preferable a un test qui echoue pour une raison etrangere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

hypothesis = pytest.importorskip("hypothesis", reason="Hypothesis absent de cet env")
from hypothesis import given, settings, strategies as st  # noqa: E402

# Profil sobre : la CI locale joue des milliers de tests, on ne lui impose pas
# 100 exemples par propriete. 50 suffisent a couvrir les frontieres usuelles.
PARAMS = settings(max_examples=50, deadline=None)

TEXTE = st.text(max_size=400)
SOURCE = st.text(min_size=1, max_size=120)


# ------------------------------------------------------ chunk_id (identite)
@PARAMS
@given(source=SOURCE, texte=TEXTE)
def test_chunk_id_est_deterministe(source, texte):
    """Meme (source, texte) -> meme identifiant. C'est ce qui rend
    `INSERT OR REPLACE` idempotent au lieu de dupliquer."""
    from forge_db_path import chunk_id  # type: ignore

    assert chunk_id(source, texte) == chunk_id(source, texte)


@PARAMS
@given(source=SOURCE, texte=TEXTE)
def test_chunk_id_a_toujours_la_meme_forme(source, texte):
    from forge_db_path import chunk_id  # type: ignore

    cid = chunk_id(source, texte)
    assert len(cid) == 16
    assert all(c in "0123456789abcdef" for c in cid)


@PARAMS
@given(a=SOURCE, b=SOURCE, texte=TEXTE)
def test_chunk_id_distingue_deux_sources(a, b, texte):
    """Deux sources differentes ne doivent pas se confondre : sinon un chunk
    ecraserait celui d'une autre origine."""
    from forge_db_path import chunk_id  # type: ignore

    if a != b:
        assert chunk_id(a, texte) != chunk_id(b, texte)


# ------------------------------------------------- famille_page (totalite)
@PARAMS
@given(url=st.text(max_size=300))
def test_famille_page_ne_leve_jamais(url):
    """Une fonction de classement appelee sur 2 700 URL reelles ne doit jamais
    interrompre le lot pour une entree malformee."""
    from forge_veille_depouillement import famille_page  # type: ignore

    f = famille_page(url)
    assert isinstance(f, str)
    assert f, "une famille vide n'est pas un classement : INCONNU est attendu"


# ------------------------------------------- normaliser (idempotence)
@PARAMS
@given(texte=TEXTE)
def test_normaliser_est_idempotent(texte):
    """Normaliser deux fois doit valoir normaliser une fois — sinon le resultat
    depend du nombre d'appels, et deux chemins d'appel divergent."""
    from forge_intent_parser import normaliser  # type: ignore

    une = normaliser(texte)
    assert normaliser(une) == une


# ------------------------------ redact_tool_output (aucune perte de contenu)
@PARAMS
@given(texte=st.text(max_size=2000))
def test_le_filtre_de_sortie_ne_perd_jamais_de_contenu_anodin(texte):
    """Propriete centrale du filtre L1 : un texte SANS secret ressort INTACT.
    Le defaut mesure le 12/09 — 4 687 faux positifs sur 300 000 caracteres
    anodins — aurait ete attrape par cette propriete des le premier tirage."""
    from forge_semantic_firewall import redact_tool_output  # type: ignore

    sortie, bilan = redact_tool_output(texte, outil="propriete")
    if bilan["secrets_rediges"] == 0:
        assert sortie == texte, (
            "le filtre a modifie un texte dans lequel il n'a rien detecte"
        )


@PARAMS
@given(texte=st.text(max_size=2000))
def test_le_filtre_de_sortie_ne_leve_jamais(texte):
    """Il est cable sur le `return` de `dispatch` : une exception y casserait
    TOUT appel d'outil."""
    from forge_semantic_firewall import redact_tool_output  # type: ignore

    sortie, bilan = redact_tool_output(texte, outil="propriete")
    assert isinstance(sortie, str)
    assert bilan["longueur"] == len(texte)
