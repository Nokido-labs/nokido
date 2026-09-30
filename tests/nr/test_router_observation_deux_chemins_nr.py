"""NR — C0 : le journal shadow observe le chemin REELLEMENT emprunte.

Ecrit ROUGE avant correctif.

CE QUE C0 DEMANDAIT. La roadmap `docs/roadmap_ameliorations_veille.md` (item C0,
2026-09-08) mesurait `sandbox/router_observations.jsonl` a **899 octets et UNE
ligne**, qui est la sonde de cablage du 2026-09-03 — donc zero recherche reelle
observee. Elle nommait **deux causes candidates, aucune mesuree**, et exigeait de
trancher AVANT de compter sur ce journal :

  (a) code commite != code charge — le hub sert sa version en memoire ;
  (b) le chemin instrumente (`forge_rag_engine.RAGEngine.search`) n'est pas celui
      qu'emprunte la production (`forge_mcp_registry.handle_rag`).

LES DEUX SONT REFUTEES, mesure du 2026-09-12 :

  (a) le process qui tient :8766 (pid 24204) a demarre le 2026-09-12T00:29, et
      `app/forge_mcp_registry.py` porte un mtime du 2026-09-10T01:58 : le hub
      tourne donc sur du code POSTERIEUR a l'instrumentation.
  (b) le commentaire du code le dit lui-meme — l'observation a ete DEPLACEE sur
      `handle_rag/_rag_dense_search` le 2026-09-03, justement parce que ce chemin
      n'emprunte pas `RAGEngine.search`.

LA VRAIE CAUSE, que la roadmap ne nommait pas. Dans `handle_rag`, l'observation
est posee DANS le `try` de la recherche dense, apres l'appel. Or `except
Exception as e_dense:` retombe sur `_rag_bm25_search` — **et cette branche
n'observe rien**. Les embedders etant eteints, toute recherche reelle prend le
repli. Preuve directe : une recherche emise le 2026-09-12 a rendu des resultats
scores `bm25=...`, et le journal n'a pas bouge (899 o, 1 ligne, mtime du 03/09).

C'est la meme famille que « un garde branche sur un signal que personne n'emet » :
ici, un observateur cable sur le seul chemin qui ne s'execute jamais.

CE QUE CE NR VERROUILLE : les DEUX branches observent, et chacune DIT le chemin
qu'elle a pris. On tranche sur l'AST — une mention du nom dans un commentaire ne
prouve rien, lecon du 2026-09-10.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CIBLE = ROOT / "app" / "forge_mcp_registry.py"
OBSERVATEUR = "_rt_observer"


def _handle_rag() -> ast.AST:
    if not CIBLE.exists():
        pytest.skip(f"{CIBLE} illisible depuis ce compte — INDETERMINE, pas absent")
    arbre = ast.parse(CIBLE.read_text(encoding="utf-8", errors="replace"))
    for n in ast.walk(arbre):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "handle_rag":
            return n
    pytest.fail("handle_rag introuvable — la cible a bouge, le NR doit etre reancre")
    raise AssertionError  # pragma: no cover


def _appelle(noeud, nom: str) -> bool:
    for n in ast.walk(noeud):
        if isinstance(n, ast.Call):
            f = n.func
            if getattr(f, "id", None) == nom or getattr(f, "attr", None) == nom:
                return True
    return False


def _reference(noeud, nom: str) -> bool:
    """Le symbole est-il NOMME ici, appele ou non ?

    ⚠️ Ecrit apres que la premiere version de ce NR a rougi pour une MAUVAISE
    raison : `self._rag_bm25_search` est PASSE a `asyncio.to_thread(...)`, donc
    c'est un `ast.Attribute` et jamais un `ast.Call`. Chercher un appel ne
    pouvait pas le trouver — l'instrument fabriquait une absence. Une fonction
    deportee dans un thread reste un chemin d'execution.
    """
    for n in ast.walk(noeud):
        if isinstance(n, ast.Attribute) and n.attr == nom:
            return True
        if isinstance(n, ast.Name) and n.id == nom:
            return True
    return False


def _branche_repli(fn) -> ast.ExceptHandler:
    """Le `except` qui retombe sur BM25 — identifie par ce qu'il FAIT, pas par son nom."""
    for n in ast.walk(fn):
        if isinstance(n, ast.ExceptHandler) and _reference(n, "_rag_bm25_search"):
            return n
    pytest.fail("aucune branche de repli BM25 trouvee dans handle_rag")
    raise AssertionError  # pragma: no cover


def test_le_detecteur_voit_une_fonction_deportee_dans_un_thread():
    """Contre-epreuve de l'instrument lui-meme : sans elle, ce NR rougirait pour
    la mauvaise raison et on 'corrigerait' un code deja correct."""
    src = "async def f():\n    return await to_thread(self._rag_bm25_search, a, b)\n"
    n = ast.parse(src)
    assert _reference(n, "_rag_bm25_search"), "le detecteur rate une fonction deportee"
    assert not _appelle(n, "_rag_bm25_search"), "…et c'est bien qu'elle n'est PAS un Call"


def test_le_chemin_dense_observe():
    """Acquis du 2026-09-03 — il ne doit pas regresser."""
    fn = _handle_rag()
    assert _appelle(fn, OBSERVATEUR), "handle_rag n'observe plus rien"


def test_le_repli_bm25_observe_aussi():
    """LE DEFAUT C0 : c'est cette branche qui sert les requetes reelles."""
    repli = _branche_repli(_handle_rag())
    assert _appelle(repli, OBSERVATEUR), (
        "le repli BM25 n'observe RIEN — or les embedders etant eteints, c'est LUI "
        "qui sert toutes les recherches reelles : le journal shadow reste donc vide "
        "en accumulant du volume nul. Observateur cable sur le seul chemin qui ne "
        "s'execute jamais."
    )


def test_chaque_branche_dit_le_chemin_qu_elle_a_pris():
    """Observer sans dire QUEL chemin ne vaut rien : le replay ne pourrait pas
    distinguer une mesure dense d'une mesure lexicale, et melangerait deux
    populations dans la meme moyenne."""
    fn = _handle_rag()
    chemins = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and "handle_rag/" in n.value:
            chemins.add(n.value)
    assert len(chemins) >= 2, (
        f"une seule etiquette de chemin trouvee ({chemins or 'aucune'}) : les deux "
        "branches doivent se distinguer dans le journal"
    )
    assert any("bm25" in c.lower() for c in chemins), (
        f"aucune etiquette ne nomme le repli lexical : {sorted(chemins)}"
    )


def test_l_echec_d_observation_reste_audible():
    """Un echec d'observation doit s'ENTENDRE — le code d'origine le disait deja
    (« WARNING et non debug : un echec doit s'entendre, sinon on remesure ce
    silence dans six mois »). On refuse qu'un correctif le rende muet."""
    src = CIBLE.read_text(encoding="utf-8", errors="replace")
    assert "[router] observation shadow impossible" in src, (
        "le message d'echec d'observation a disparu : un observateur qui echoue en "
        "silence est pire qu'un observateur absent"
    )
