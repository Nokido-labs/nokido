"""
app/web_hub/envfile.py - Loader .env minimal, zero dependance.

Lit Nokido.env (ou .env) a la racine du projet et injecte dans os.environ
les cles qui n y sont pas deja (respecte l env shell existant).

Syntaxe supportee :
  KEY=value                  simple
  KEY="value with spaces"    guillemets doubles ou simples
  KEY=value # comment         commentaire inline retire
  # full line comment         ignore
  KEY=                        valeur vide (injecte "")

NON supporte (volontairement) :
  - Interpolation ${OTHER}   (on ne veut pas d expansion recursive)
  - export KEY=value         (syntaxe shell)
  - Multiline values

SECURITY :
  - override=False par defaut : l env shell prime sur le fichier
  - Ne leak jamais les valeurs dans les logs (log juste les cles)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

log = logging.getLogger("nokido.hub.envfile")

# Chemins candidats par ordre de preference
ROOT = Path(__file__).resolve().parent.parent.parent
_CANDIDATES = (
    ROOT / "Nokido.env",
    ROOT / ".env",
)


def _parse_line(line: str) -> Optional[tuple[str, str]]:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if "=" not in s:
        return None
    k, v = s.split("=", 1)
    k = k.strip()
    if not k or not k.replace("_", "").replace(".", "").isalnum():
        # cle invalide -> skip
        return None
    v = v.strip()
    # Retire commentaire inline UNIQUEMENT si la valeur n est pas quotee
    if v and v[0] not in ("'", '"'):
        hash_idx = v.find(" #")
        if hash_idx >= 0:
            v = v[:hash_idx].strip()
    # Retire les quotes
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    return (k, v)


def load_env_file(path: Optional[Path] = None, override: bool = False) -> dict[str, str]:
    """Charge un fichier .env dans os.environ.

    Args :
        path : chemin explicite (sinon detection auto via _CANDIDATES)
        override : si True, ecrase meme les vars deja dans l env

    Retour : dict des cles effectivement injectees (sans valeur, pour audit).
    """
    if path is None:
        for c in _CANDIDATES:
            if c.exists():
                path = c
                break
        else:
            return {}
    if not path.exists():
        return {}

    injected: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parsed = _parse_line(line)
                if not parsed:
                    continue
                k, v = parsed
                if k in os.environ and not override:
                    continue
                os.environ[k] = v
                injected[k] = "***"  # shadow
    except OSError as e:
        log.warning("envfile load failed (%s): %s", path, e)
        return {}

    if injected:
        log.info("envfile loaded %d vars from %s", len(injected), path.name)
    return injected


__all__ = ["load_env_file"]
