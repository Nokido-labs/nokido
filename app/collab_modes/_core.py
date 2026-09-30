# -*- coding: utf-8 -*-
"""
app.collab_modes._core - Core helpers pour collab_modes.

Contient les utilitaires partages par tous les modes :
- Detection dev mode, session ID
- Logging (ligne, mode, fin, headers)
- CollabSession dataclass

Voir docs/REFACTO_COLLAB_MODES_SPEC.md pour le refacto.
Part du package app.collab_modes.

NOTE : ce module vit dans app/collab_modes/_core.py (3 niveaux sous repo root),
l'original forge_collab_modes.py vivait dans app/ (2 niveaux). Les chemins
__file__.parent.parent.parent compensent cette profondeur.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field as _dc_field

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("Nokido.Collab")


def _is_dev_mode() -> bool:
    """True si LAFORGE_ENV=dev dans Nokido.env ou os.environ."""
    import os

    val = os.environ.get("LAFORGE_ENV", "")
    if not val:
        try:
            from pathlib import Path as _P

            root = _P(__file__).resolve().parent.parent.parent
            for line in (root / "Nokido.env").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("LAFORGE_ENV"):
                    val = line.split("=", 1)[-1].strip()
                    break
        except Exception:
            pass
    return val.lower() == "dev"


def _spl_log(
    session_id: str,
    agent_id: str,
    content: str,
    role: str = "assistant",
    mode: str = "dev:collab",
    is_private: int = 0,
) -> None:
    """
    Log d'un tour LLM dans shared_prompt_log.
    Activé uniquement si LAFORGE_ENV=dev.

    Fail-Safe : si le contenu contient un pattern de clé/secret détecté
    par _redact(), is_private est forcé à 1 même si mode='dev:llm'.
    La sécurité l'emporte toujours sur la visibilité DEV.
    """
    if not _is_dev_mode():
        return
    if not content or not session_id:
        return
    try:
        from nokido_agent.app.forge_conv_sanitizer import log_secure, _REDACT_PATTERNS

        # ── Fail-Safe : détection de secrets → forcer is_private=1 ───────────
        _safe_private = is_private
        if _safe_private == 0:
            for pattern, _ in _REDACT_PATTERNS:
                if pattern.search(content):
                    _safe_private = 1
                    logger.debug(f"[spl_log] Fail-Safe: secret détecté ({pattern.pattern[:30]}) → is_private=1 forcé")
                    break
            # Vérification supplémentaire : données ring=0
            from nokido_agent.app.forge_conv_sanitizer import _contains_ring0_data

            if _contains_ring0_data(content):
                _safe_private = 1
                logger.debug("[spl_log] Fail-Safe: ring=0 data → is_private=1 forcé")

        log_secure(
            session_id=session_id,
            agent_id=agent_id,
            content=content[:2000],
            role=role,
            mode=mode,
            is_private=_safe_private,
        )
    except Exception as _e:
        logger.debug(f"[spl_log] {_e}")


def _get_session_id() -> str:
    """Récupère la session_id courante depuis l'app TUI."""
    try:
        import sys as _s

        for mod_name in ("__main__", "Nokido", "app.Nokido"):
            mod = _s.modules.get(mod_name)
            if mod:
                ctx = getattr(mod, "context", None) or getattr(getattr(mod, "_app", None), "context", None)
                if ctx and hasattr(ctx, "session_id"):
                    return ctx.session_id
                sn = getattr(mod, "session_name", "")
                if sn:
                    return sn
    except Exception:
        pass
    return "collab"


def _log_turn(mode: str, turn: int, agent: str, duration: float, length: int, empty: bool = False) -> None:
    """Log structuré pour chaque tour d'un mode collab."""
    if empty:
        logger.warning(f"[collab:{mode}] tour {turn} agent={agent} VIDE (indisponible) durée={duration:.1f}s")
    else:
        logger.info(f"[collab:{mode}] tour {turn} agent={agent} durée={duration:.1f}s chars={length}")


def _log_mode(mode: str, task: str, **kwargs) -> None:
    """Log de démarrage d'un mode."""
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info(f"[collab:{mode}] START task='{task[:60]}' {extra}")


def _log_end(mode: str, task_id: str, status: str, total_turns: int, synth_len: int) -> None:
    """Log de fin de mode."""
    logger.info(f"[collab:{mode}] END task_id={task_id} status={status} turns={total_turns} synth_chars={synth_len}")


def _header(chat: object, title: str, subtitle: str) -> None:
    """Affiche un en-tête de session dans le chat log."""
    w = 60
    chat.write(f"[bold #58a6ff]╔{'═' * (w - 2)}╗[/]")
    chat.write(f"[bold #58a6ff]║  {title:<{w - 4}}║[/]")
    chat.write(f"[bold #58a6ff]║  [dim]{subtitle:<{w - 6}}[/][bold #58a6ff]  ║[/]")
    chat.write(f"[bold #58a6ff]╚{'═' * (w - 2)}╝[/]")


def _turn_header(chat: object, turn: int, total: int, agent: str, color: str, icon: str) -> None:
    """Turn header."""
    chat.write(f"\n[{color}]{icon} Tour {turn}/{total} — [bold]{agent}[/] :[/{color}]")


@dataclass
class CollabSession:
    """Parametres d une session de collaboration orchestree par Nokido."""

    prompt: str
    mode: str = "ping"
    chef_model: str = "auto"  # modele Ollama pour Nokido
    participants: list = _dc_field(default_factory=lambda: ["ollama"])
    turns: int = 3
    delay_claude: float = 2.5  # secondes entre tours Claude
    delay_gemini: float = 1.0  # secondes entre tours Gemini
    delay_ollama: float = 0.3
    session_id: str = ""
