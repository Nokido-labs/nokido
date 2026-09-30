from __future__ import annotations

__FORGE_COLOR__ = "snc/hub : cortex hybride, intention cloud et action locale"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("forge.hybrid_cortex")

# Intentions triviales traitables en LOCAL sans raisonnement Cloud (triage).
_LOCAL_INTENT_HINTS = ("status", "statut", "health", "ping", "list ", "lister",
                       "read ", "lire ", "cat ", "version", "uptime", "heartbeat")
_CLOUD_MIN_PROMPT = 80          # prompt plus court -> candidate a un traitement local
_COMPRESS_MIN_CHARS = 1500      # seuil de compression AST d'un fichier
# Hard Triggers de securite (audit 2026-06-17) : coupent le flux avant fin de generation.
# Litteraux CONCATENES a dessein : aucun token dangereux contigu dans ce source
# (sinon la membrane semantique bloque son propre garde de securite).
_SECURITY_THREATS = (
    "<" "SCRIPTRUN",
    "rm -rf" " /",
    "DROP" " TABLE",
    "curl" " -X POST",
    "os." "system",
)


class HybridCortex:
    """Nokido Hybrid Cortex V15 — dissocie l'Intention (Cloud) de l'Action (Local).

    Cf docs/DESIGN_CORTEX_HYBRIDE.md. Trois organes :
      - preflight_triage : local vs cloud, puis compression AST du contexte cloud ;
      - _compress_context / _generate_skeleton : le cloud recoit la STRUCTURE
        (signatures + docstrings), jamais le code brut (-80% tokens) ;
      - stream_prism : prisme du flux SSE avec kill-switch de securite.
    """

    def __init__(self, root_dir: Optional[Path] = None):
        self.root = root_dir or Path(__file__).resolve().parent.parent
        self.stats = {"preflight_compressed": 0, "postflight_intercepted": 0,
                      "triage_local": 0, "triage_cloud": 0}

    def _triage(self, prompt: str, context: Dict[str, Any], edit_targets: List[str]) -> Tuple[bool, str]:
        """Rend (is_cloud_eligible, motif). Deterministe : une EDITION ou du code
        en contexte partent au Cloud (structure a compresser) ; une tache COURTE
        d'intention locale (status/list/read...) reste LOCALE ; sinon, on affine
        par le classifieur souverain forge_nlu si present (best-effort, jamais
        bloquant), a defaut Cloud. Le design evoque un classifieur Ollama : on
        garde une base deterministe testable plutot qu'un appel reseau obligatoire."""
        p = (prompt or "").lower().strip()
        if edit_targets or (context or {}).get("files"):
            return True, "edition / code en contexte -> cloud"
        if len(p) < _CLOUD_MIN_PROMPT and any(h in p for h in _LOCAL_INTENT_HINTS):
            return False, "tache locale (courte, intention locale)"
        # MESURE 2026-09-12 (`sandbox/mesure_am1_multi_intention.py`) : ce bloc
        # importait `FastClassifier`, qui N'EXISTE PAS dans `forge_nlu` — ni sous
        # le nom plat, ni sous le nom namespace. Le module s'importe bien, c'est le
        # SYMBOLE qui est absent : il n'est cite que dans une docstring (L20), et
        # `CLAUDE.md` l'annonce comme le thalamus de tri. L'`ImportError` tombait
        # donc a CHAQUE appel dans un `except: pass`, et l'affinage souverain n'a
        # jamais tourne une seule fois. Mesure sur 8 prompts : 8/8 partis au cloud
        # sous le meme motif « par defaut », dont 5 purement conversationnels.
        # Un mecanisme present n'est pas un effet : c'etait une dette de cablage
        # deguisee en garde. On appelle ce que le module EXPORTE vraiment.
        try:
            from nokido_agent.app.forge_nlu import get_router_if_ready  # type: ignore

            routeur = get_router_if_ready()
        except Exception as e:  # noqa: BLE001
            # Et le motif ne ment plus : trois etats, jamais deux. Un classifieur
            # illisible n'est pas un classifieur qui a repondu « cloud ».
            logger.warning(
                "[CORTEX] classifieur souverain illisible (%s: %s) — triage par "
                "defaut | consequence: l'affinage local ne sert plus et sa qualite "
                "n'est plus mesuree", type(e).__name__, str(e)[:80])
            return True, "classifieur ILLISIBLE -> cloud (par defaut)"
        if routeur is None:
            return True, "classifieur non entraine (UNKNOWN) -> cloud (par defaut)"
        vote = routeur.predict(prompt)
        if vote.confident and vote.intent == "chat":
            return False, f"forge_nlu=chat conf={vote.confidence:.2f} (local)"
        return True, (
            f"forge_nlu={vote.intent} conf={vote.confidence:.2f}"
            f"{'' if vote.confident else ' NON CONFIANT'} -> cloud"
        )

    async def preflight_triage(self, agent_id: str, prompt: str, context: Dict[str, Any],
                               edit_targets: Optional[List[str]] = None) -> Tuple[bool, Dict[str, Any]]:
        """Decide le deport Cloud vs local. Si Cloud, compresse le contexte en AST
        SAUF les edit_targets (Source Exact preserve pour l'edition)."""
        targets = edit_targets or []
        is_cloud_eligible, motif = self._triage(prompt, context, targets)
        self.stats["triage_cloud" if is_cloud_eligible else "triage_local"] += 1
        logger.info("[CORTEX] triage %s : %s", "CLOUD" if is_cloud_eligible else "LOCAL", motif)
        if is_cloud_eligible:
            context = await self._compress_context(context, exclude=targets)
            self.stats["preflight_compressed"] += 1
        return is_cloud_eligible, context

    async def stream_prism(self, chunk: str) -> bool:
        """Separateur optique du flux SSE. Retourne False (Kill Switch) si une
        intention dangereuse apparait AVANT la fin de la generation, sinon publie
        le transient sur le bus local (Fork 2 / Shadow Stream) et retourne True."""
        for threat in _SECURITY_THREATS:
            if threat in chunk:
                logger.critical("[CORTEX] SECURITY BREACH DETECTED IN STREAM: %s", threat)
                return False
        # Fork 2 : publier le token sur le bus local. Best-effort ABSOLU — une
        # panne de bus ne doit JAMAIS interrompre le flux vu par l'utilisateur.
        try:
            from nokido_agent.app.forge_event_stream import publish  # type: ignore
            publish("transient.stream", {"chunk": chunk})
        except Exception:  # muet-ok : le bus ne doit jamais couper le flux
            pass
        return True

    async def _compress_context(self, context: Dict[str, Any],
                                exclude: Optional[List[str]] = None) -> Dict[str, Any]:
        """Remplace le contenu brut des .py volumineux par leur squelette AST
        (structure seule), sauf les cibles d'edition (Source Exact)."""
        exclude = exclude or []
        if "files" not in context:
            return context
        compressed: Dict[str, Any] = {}
        for path, content in context["files"].items():
            is_edit_target = any(path.endswith(t) or t in path for t in exclude)
            if len(content) > _COMPRESS_MIN_CHARS and path.endswith(".py") and not is_edit_target:
                logger.info("Cortex: compression AST de %s", path)
                compressed[path] = self._generate_skeleton(path, content)
            else:
                if is_edit_target:
                    logger.info("Cortex: Source Exact preserve pour %s (cible d'edition)", path)
                compressed[path] = content
        context["files"] = compressed
        context["ast_compressed"] = True
        return context

    def _generate_skeleton(self, path: str, content: str) -> str:
        """Squelette AST REEL : docstring de module + signatures top-level (classes,
        fonctions, methodes) avec leur premiere ligne de docstring, corps masque
        par `...`. Fallback ligne-a-ligne si le fichier ne parse pas (syntaxe cassee)."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return self._skeleton_fallback(path, content)

        out = ["# AST SKELETON — %s" % path,
               "# [corps masque par le Hybrid Cortex — structure seule, -80%% tokens]"]
        mod_doc = ast.get_docstring(tree)
        if mod_doc:
            out.append('"""%s"""' % mod_doc.splitlines()[0])

        def emit(node: ast.AST, indent: int = 0) -> None:
            pad = "    " * indent
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                deco = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                args = ", ".join(a.arg for a in node.args.args)
                out.append("%s%sdef %s(%s): ..." % (pad, deco, node.name, args))
            elif isinstance(node, ast.ClassDef):
                bases = ", ".join(b.id for b in node.bases if isinstance(b, ast.Name))
                out.append("%sclass %s%s:" % (pad, node.name, ("(%s)" % bases) if bases else ""))
                doc = ast.get_docstring(node)
                if doc:
                    out.append('%s    """%s"""' % (pad, doc.splitlines()[0]))
                members = [n for n in node.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                if members:
                    for n in members:
                        emit(n, indent + 1)
                else:
                    out.append("%s    ..." % pad)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                emit(node)
        return "\n".join(out)

    def _skeleton_fallback(self, path: str, content: str) -> str:
        """Squelette ligne-a-ligne (fallback, fichier non parsable) : signatures brutes."""
        out = ["# SKELETON (fallback, non parsable) — %s" % path]
        for line in content.splitlines()[:150]:
            t = line.strip()
            if t.startswith(("class ", "def ", "async def ", "@")):
                out.append(line)
        return "\n".join(out)


_CORTEX: Optional[HybridCortex] = None


def get_cortex() -> HybridCortex:
    global _CORTEX
    if _CORTEX is None:
        _CORTEX = HybridCortex()
    return _CORTEX
