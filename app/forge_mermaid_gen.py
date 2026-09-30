"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_mermaid_gen
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = (
    "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
)

"""
app/forge_mermaid_gen.py
==========================
Génération de diagrammes Mermaid.js via Qwen2.5-Coder (llama_cpp).

Utilise le participant qwen_coder du SwarmTeam — température 0.1
pour maximiser la cohérence syntaxique Mermaid.

Fonctions exportées :
  generate_mermaid(prompt)      → str (code mermaid brut)
  generate_mermaid_async(prompt) → coroutine → str
  validate_mermaid(code)        → {"ok": bool, "error": str}

Types supportés :
  flowchart, sequenceDiagram, classDiagram, erDiagram,
  stateDiagram-v2, gantt, gitGraph, C4Component, mindmap

Fallback : si llama_cpp indisponible → template statique.
"""

import asyncio
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Prompt système optimisé pour Mermaid syntaxiquement correct
_MERMAID_SYSTEM = """Tu es un expert Mermaid.js. Tu génères UNIQUEMENT du code Mermaid valide.
Règles absolues :
1. Répondre avec UN SEUL bloc ```mermaid ... ```
2. Zéro texte avant ou après le bloc
3. Respecter strictement la syntaxe Mermaid.js v10
4. Utiliser des identifiants sans espaces (ex: node_A pas "node A")
5. Limiter à 20 nœuds max pour la lisibilité
6. Pour les labels avec espaces : utiliser ["texte avec espaces"]
7. flowchart TD pour les flux verticaux, LR pour les horizontaux"""

_DIAGRAM_TEMPLATES = {
    "flowchart": "flowchart TD\n    A[Début] --> B{Décision}\n    B -->|Oui| C[Action]\n    B -->|Non| D[Fin]",
    "sequence": "sequenceDiagram\n    participant A\n    participant B\n    A->>B: Message\n    B-->>A: Réponse",
    "class": "classDiagram\n    class Animal {\n        +String name\n        +makeSound()\n    }",
    "er": "erDiagram\n    USER ||--o{ ORDER : places\n    ORDER ||--|{ ITEM : contains",
    "state": "stateDiagram-v2\n    [*] --> IDLE\n    IDLE --> THINKING\n    THINKING --> STREAMING\n    STREAMING --> IDLE",
}


def _extract_mermaid(text: str) -> str:
    """Extrait le code Mermaid d'un bloc ```mermaid ... ```."""
    # Pattern strict : ```mermaid\n...\n```
    m = re.search(r"```mermaid\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback : si le modèle a oublié les backticks mais commence par un keyword
    keywords = [
        "flowchart",
        "sequenceDiagram",
        "classDiagram",
        "erDiagram",
        "stateDiagram",
        "gantt",
        "gitGraph",
        "C4Component",
        "mindmap",
        "graph ",
        "graph\n",
    ]
    for kw in keywords:
        if text.strip().startswith(kw):
            return text.strip()
    return text.strip()


def validate_mermaid(code: str) -> dict:
    """
    Validation syntaxique légère sans rendu.
    Vérifie les patterns les plus communs d'erreur.
    """
    if not code or len(code.strip()) < 5:
        return {"ok": False, "error": "Code vide"}

    lines = code.strip().splitlines()
    first = lines[0].strip()

    # Doit commencer par un keyword valide
    valid_starts = [
        "flowchart",
        "graph ",
        "sequenceDiagram",
        "classDiagram",
        "erDiagram",
        "stateDiagram",
        "gantt",
        "gitGraph",
        "mindmap",
        "C4",
    ]
    if not any(first.startswith(kw) for kw in valid_starts):
        return {"ok": False, "error": f"Keyword manquant, trouve: '{first[:30]}'"}

    # Vérifications basiques
    errors = []
    for i, line in enumerate(lines[1:], 2):
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        # Parenthèses non fermées
        if stripped.count("(") != stripped.count(")"):
            errors.append(f"L{i}: parenthèses non équilibrées")
        # Guillemets non fermés
        if stripped.count('"') % 2 != 0:
            errors.append(f"L{i}: guillemets non fermés")

    if errors:
        return {"ok": False, "error": " | ".join(errors[:3])}

    return {"ok": True, "error": ""}


def generate_mermaid(
    prompt: str,
    diagram_type: str = "flowchart",
    max_tokens: int = 800,
    timeout_s: float = 30.0,
) -> dict:
    """
    Génère un diagramme Mermaid via Qwen2.5-Coder (llama_cpp natif).

    Returns:
        {"ok": bool, "code": str, "type": str,
         "elapsed_ms": float, "source": str}
    """
    t0 = time.monotonic()

    # Construire le prompt Mermaid
    type_hints = {
        "flowchart": "flowchart TD ou LR",
        "sequence": "sequenceDiagram",
        "class": "classDiagram",
        "er": "erDiagram",
        "state": "stateDiagram-v2",
        "c4": "C4Component",
        "git": "gitGraph",
        "mind": "mindmap",
    }
    type_str = type_hints.get(diagram_type, "flowchart TD")
    full_prompt = (
        f"{_MERMAID_SYSTEM}\n\n"
        f"Génère un diagramme {type_str} pour : {prompt}\n\n"
        f"Réponds avec UNIQUEMENT le bloc ```mermaid```."
    )

    source = "llamacpp"
    raw = ""

    # Tentative llama_cpp natif (llamacpp_call est ASYNC + attend messages[])
    try:
        import sys as _sys

        if str(ROOT / "app") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_llamacpp import LlamaCppBridge, llamacpp_call

        bridge = LlamaCppBridge()
        if not bridge.is_available():
            raise RuntimeError("LlamaCppBridge not available")

        # Format OpenAI-style messages attendu par llamacpp_call
        _messages = [{"role": "user", "content": prompt}]

        # Gerer contexte sync ET async (si deja dans un event loop)
        try:
            _running = asyncio.get_running_loop()
        except RuntimeError:
            _running = None

        if _running is None:
            # Contexte sync : on peut utiliser asyncio.run()
            raw = asyncio.run(
                llamacpp_call(
                    _messages,
                    system=_MERMAID_SYSTEM,
                    max_tokens=max_tokens,
                    temperature=0.1,
                )
            )
        else:
            # Contexte async : executer dans un thread dedie pour ne pas bloquer
            import concurrent.futures as _cf

            def _runner():
                return asyncio.run(
                    llamacpp_call(
                        _messages,
                        system=_MERMAID_SYSTEM,
                        max_tokens=max_tokens,
                        temperature=0.1,
                    )
                )

            with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
                raw = _pool.submit(_runner).result(timeout=timeout_s * 2)

        source = "qwen2.5-coder-llamacpp"
    except Exception as e:
        # Fallback : template statique
        raw = "```mermaid\n" + _DIAGRAM_TEMPLATES.get(diagram_type, _DIAGRAM_TEMPLATES["flowchart"]) + "\n```"
        source = f"template_fallback({type(e).__name__})"

    code = _extract_mermaid(raw)
    validation = validate_mermaid(code)
    elapsed = (time.monotonic() - t0) * 1000

    return {
        "ok": validation["ok"],
        "code": code,
        "type": diagram_type,
        "raw": raw[:200],
        "elapsed_ms": round(elapsed, 1),
        "source": source,
        "error": validation.get("error", ""),
    }


async def generate_mermaid_async(
    prompt: str,
    diagram_type: str = "flowchart",
    max_tokens: int = 800,
) -> dict:
    """Version async — non-bloquante pour le SwarmTeam."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: generate_mermaid(prompt, diagram_type, max_tokens))


# ── Intégration forge_web_service ─────────────────────────────────────────────


def svc_generate_mermaid(prompt: str, diagram_type: str = "flowchart") -> dict:
    """Wrapper pour forge_web_service.svc.*"""
    try:
        return generate_mermaid(prompt, diagram_type)
    except Exception as e:
        return {"ok": False, "code": "", "error": str(e)[:120], "source": "error"}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    prompt = " ".join(sys.argv[1:]) or "architecture microservices avec auth et base de données"
    dtype = "flowchart"
    result = generate_mermaid(prompt, dtype)
    print(f"Source : {result['source']}  ({result['elapsed_ms']}ms)")
    print(f"Valid  : {result['ok']}" + (f"  ERR: {result['error']}" if not result["ok"] else ""))
    print("---")
    print(result["code"])
