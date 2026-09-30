"""app/forge_rag_via_hub.py -- le RAG de la TUI v13 passe par le HUB, sans rien charger en local.

__FORGE_COLOR__ declare plus bas (le census lit la premiere ligne ancree).

POURQUOI (decision owner 1 du 2026-09-25, sur mesure). La sonde headless de la TUI v13
(tools/forge_tui_sonde.py, pile faulthandler a l'echeance) a PROUVE que son montage
construisait `RAGEngine()` dans la boucle de l'interface : `_load_embeddings` parcourt TOUTES
les lignes actives de rag_chunks (SELECT non borne) -- ecran gele au-dela de 45 s, plusieurs
Go en RAM, et un lecteur long sur la base de 45 Go a CHAQUE ouverture (la classe de cause du
P0 WAL). `forge_mixin_ui` rechargeait meme toute la base a chaque modification du fichier.
Doctrine : un client est transitoire, le hub est le systeme -- la TUI interroge le RAG du hub.

ANTI-DOUBLON. Le transport existe : `forge_hub_client.HubClient` (jeton resolu POUR l'identite,
jamais le maitre). Ce module n'est qu'un ADAPTATEUR : la meme interface que RAGEngine pour les
consommateurs de la TUI (search / add_session_message / get_embeddings / chunks / index_pending /
_load_embeddings / _save_embeddings / close), rien de plus.

CE QU'IL DIT, AU LIEU DE LE TAIRE. Un refus du hub (401, ring insuffisant -- la TUI n'a pas
d'identite propre et parle en SERVICES, ring 4, quand l'outil `rag` exige 3) rend une liste
VIDE, mais `etat()` le NOMME : le panneau RAG de la TUI n'affiche plus « 0 chunks » (qui se
lirait « base vide ») mais « RAG du hub -- refuse : ... ». UNKNOWN n'est pas NO.
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/rag-client-via-hub"

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

_log = logging.getLogger("forge.rag_via_hub")

# En-tete d'un resultat rendu par l'outil `rag action=search` du hub :
#   [chemin/source] (domaine, bm25=-37.2)
_ENTETE = re.compile(r"^\[(?P<source>[^\]\n]+)\] \((?P<meta>[^)\n]*)\)\s*$", re.M)
_MARQUES_REFUS = ("GATE_DENIED", "[Hub] Erreur", "unauthorized", "no_auth", "RBAC")


def analyser_resultats(texte: str) -> List[Dict[str, Any]]:
    """Texte de `rag action=search` -> [{content, source, domain, score}] (meme forme que RAGEngine)."""
    entetes = list(_ENTETE.finditer(texte or ""))
    out = []
    for i, m in enumerate(entetes):
        fin = entetes[i + 1].start() if i + 1 < len(entetes) else len(texte)
        meta = m.group("meta")
        domaine = meta.split(",")[0].strip() if meta else ""
        sc = re.search(r"bm25=(-?[\d.]+)", meta or "")
        out.append({
            "content": texte[m.end():fin].strip(),
            "source": m.group("source").strip(),
            "domain": domaine,
            "score": float(sc.group(1)) if sc else None,
        })
    return out


class RAGViaHub:
    """Meme interface que RAGEngine pour la TUI v13 ; toute la memoire vit dans le hub."""

    via_hub = True
    PLAFOND_SESSION = 400  # messages de session gardes en local, par session

    def __init__(self, client: Any = None, agent: str = "TUI") -> None:
        self.agent = agent
        self._client = client
        self.chunks: List[Dict] = []  # JAMAIS la base : seulement les docs locaux du warmup
        self.faiss_index = None
        self.bm25_index = None
        self.expected_dim: Optional[int] = None
        self.session_ctxs: Dict[str, List[Dict]] = {}
        self.sessions_ecartees = 0
        self.derniere_panne = ""
        self.recherches = 0

    def _hub(self):
        if self._client is None:
            from nokido_agent.app.forge_hub_client import HubClient

            self._client = HubClient(agent=self.agent)
        return self._client

    def etat(self) -> str:
        """Ce que le panneau RAG doit AFFICHER (jamais « 0 chunks »)."""
        if self.derniere_panne:
            return "refuse : " + self.derniere_panne[:90]
        return "joint" if self.recherches else "pas encore interroge"

    async def search(self, query: str, k: Optional[int] = None, include_sessions: bool = False,
                     role_hint: Optional[str] = None, domain: Optional[str] = None, **_: Any) -> List[Dict]:
        limite = int(k or 5)
        texte = await asyncio.to_thread(
            self._hub().tool, "rag", {"action": "search", "topic": query, "limit": limite})
        self.recherches += 1
        if texte is None:
            self.derniere_panne = "hub injoignable ou refus HTTP (journal hub_client)"
            return []
        if any(m in texte[:300] for m in _MARQUES_REFUS):
            self.derniere_panne = " ".join(texte.split())[:200]
            _log.warning("[rag_via_hub] agent=%s recherche REFUSEE par le hub : %s",
                         self.agent, self.derniere_panne)
            return []
        self.derniere_panne = ""
        return analyser_resultats(texte)[:limite]

    async def add_session_message(self, session_name: str, role: str, content: str,
                                  meta: Optional[Dict] = None) -> None:
        """Contexte de session LOCAL et borne (jamais ecrit dans la base) ; ce qui deborde est COMPTE."""
        lst = self.session_ctxs.setdefault(session_name, [])
        lst.append({"role": role, "content": content, "meta": meta or {}})
        if len(lst) > self.PLAFOND_SESSION:
            trop = len(lst) - self.PLAFOND_SESSION
            del lst[:trop]
            self.sessions_ecartees += trop

    async def get_embeddings(self, texts: List[str]) -> List:
        return []  # aucun embedder local : la vectorisation est le travail du hub

    def _load_embeddings(self) -> None:
        return None  # c'etait le lecteur long de toute la base : volontairement inerte

    def _save_embeddings(self) -> None:
        return None

    async def index_pending(self) -> None:
        return None  # l'ingestion passe par le hub, pas par la TUI

    async def close(self) -> None:
        return None
