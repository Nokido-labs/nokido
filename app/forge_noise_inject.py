"""
app/forge_noise_inject.py — Semantic Noise Injector v1.0
=========================================================
Injecte du bruit sémantique dans un snippet avant envoi à un LLM cloud.
But : casser le fingerprinting de code propriétaire.

Usage :
    from app.forge_noise_inject import inject_noise, strip_noise
    noisy_prompt = inject_noise(prompt, level="medium")
    # → envoie à DeepSeek/GPT/etc.
    clean_result = strip_noise(result)  # (optionnel, LLM ignore le bruit)

Niveaux :
    light  → variables bidon + imports faux (détection difficile)
    medium → variables + fonctions vides + commentaires parasites (défaut)
    heavy  → tout + restructuration syntaxique légère

LIMITATIONS (documentées honnêtement) :
- Inefficace contre un attaquant qui compare les outputs LLM
- Ne protège PAS les données structurelles (noms de classes, logique)
- Utile surtout pour casser les index automatisés (télémétrie LLM)
- Inutile pour les modèles locaux (Ollama)
"""

from __future__ import annotations

import hashlib
import random
import re
import string
from typing import Literal

# Seed basée sur l'heure pour reproductibilité partielle
_RNG = random.Random()

# Marqueur invisible pour identifier les sections bruitées
NOISE_MARKER_START = "# __LAFORGE_NOISE_START__\n"
NOISE_MARKER_END = "\n# __LAFORGE_NOISE_END__"


def _random_name(length: int = 6) -> str:
    """Génère un nom de variable/fonction aléatoire réaliste."""
    prefixes = ["_tmp", "_buf", "_ref", "_aux", "_ctx", "_meta", "_val"]
    suffixes = ["".join(random.choices(string.ascii_lowercase, k=length))]
    return random.choice(prefixes) + "_" + suffixes[0]


def _fake_import() -> str:
    """Génère un faux import plausible."""
    modules = [
        "from typing import Optional",
        "import os.path as _osp",
        "from pathlib import PurePath",
        "import functools as _ft",
        "from collections import OrderedDict",
        "import itertools as _it",
        "from contextlib import suppress",
        "import weakref as _wr",
    ]
    return random.choice(modules)


def _fake_variable() -> str:
    """Génère une assignation de variable bidon."""
    name = _random_name()
    values = [
        "None",
        "0",
        "[]",
        "{}",
        '""',
        "True",
        "object()",
        f'"{hashlib.md5(_random_name().encode()).hexdigest()[:8]}"',
    ]
    return f"{name} = {random.choice(values)}"


def _fake_function() -> str:
    """Génère une fonction vide réaliste."""
    name = _random_name(8)
    args = ", ".join([_random_name(4) for _ in range(random.randint(0, 2))])
    return f'def {name}({args}):\n    """Internal utility."""\n    pass'


def _fake_comment() -> str:
    """Génère un commentaire parasite."""
    comments = [
        "# TODO: optimize later",
        "# FIXME: check edge cases",
        "# NOTE: see issue #" + str(random.randint(100, 9999)),
        "# Legacy compatibility layer",
        "# Temporary — to be refactored",
        "# Performance: O(n) expected",
        "# Thread-safe via GIL",
        "# Validated against spec v" + str(random.randint(1, 5)) + "." + str(random.randint(0, 9)),
    ]
    return random.choice(comments)


# ── Niveaux de bruit ──────────────────────────────────────────────────────────
def _noise_light(seed: int = 0) -> str:
    """Bruit léger : 2-3 imports faux + variables."""
    _RNG.seed(seed)
    lines = [
        NOISE_MARKER_START,
        _fake_import(),
        _fake_import(),
        _fake_variable(),
        _fake_variable(),
        NOISE_MARKER_END,
    ]
    return "\n".join(lines)


def _noise_medium(seed: int = 0) -> str:
    """Bruit moyen : imports + variables + fonction vide + commentaires."""
    _RNG.seed(seed)
    lines = [
        NOISE_MARKER_START,
        _fake_import(),
        _fake_import(),
        _fake_import(),
        "",
        _fake_variable(),
        _fake_variable(),
        _fake_variable(),
        "",
        _fake_comment(),
        _fake_function(),
        "",
        _fake_comment(),
        NOISE_MARKER_END,
    ]
    return "\n".join(lines)


def _noise_heavy(seed: int = 0) -> str:
    """Bruit lourd : tout ce qui précède + restructuration."""
    _RNG.seed(seed)
    lines = [
        NOISE_MARKER_START,
        _fake_import(),
        _fake_import(),
        _fake_import(),
        _fake_import(),
        "",
        _fake_variable(),
        _fake_variable(),
        _fake_variable(),
        _fake_variable(),
        _fake_variable(),
        "",
        _fake_comment(),
        _fake_function(),
        "",
        _fake_comment(),
        _fake_function(),
        "",
        _fake_comment(),
        NOISE_MARKER_END,
    ]
    return "\n".join(lines)


NOISE_LEVELS = {
    "light": _noise_light,
    "medium": _noise_medium,
    "heavy": _noise_heavy,
}


# ── API publique ──────────────────────────────────────────────────────────────
def inject_noise(
    text: str,
    level: Literal["light", "medium", "heavy"] = "medium",
    seed: int | None = None,
    only_code_blocks: bool = True,
) -> str:
    """
    Injecte du bruit sémantique dans un texte/prompt.

    Args:
        text:             Le prompt ou snippet à bruiter
        level:            Intensité du bruit ("light"/"medium"/"heavy")
        seed:             Graine aléatoire (None = timestamp)
        only_code_blocks: Si True, bruite uniquement les blocs ```code```
                          Sinon bruite le texte complet

    Returns:
        Le texte bruité (LLM target ignorera le bruit, humain/script non)
    """
    import time

    effective_seed = seed if seed is not None else int(time.time()) % 10000
    noise_fn = NOISE_LEVELS.get(level, _noise_medium)
    noise_block = noise_fn(effective_seed)

    if only_code_blocks:
        # Bruite uniquement à l'intérieur des blocs de code
        def _add_noise_to_block(m: re.Match) -> str:
            lang = m.group(1) or ""
            code = m.group(2)
            return f"```{lang}\n{noise_block}\n{code}```"

        result = re.sub(r"```(\w*)\n(.*?)```", _add_noise_to_block, text, flags=re.DOTALL)
        if result == text:
            # Pas de blocs code → ajoute en fin de texte
            result = text + "\n\n" + noise_block
    else:
        # Bruite le texte complet (avant le contenu)
        result = noise_block + "\n\n" + text

    return result


def strip_noise(text: str) -> str:
    """
    Supprime les blocs de bruit d'un texte (si le LLM les a inclus
    dans sa réponse — rare mais possible).
    """
    return re.sub(
        r"# __LAFORGE_NOISE_START__.*?# __LAFORGE_NOISE_END__\n?",
        "",
        text,
        flags=re.DOTALL,
    ).strip()


def noise_stats(text: str) -> dict:
    """Retourne des statistiques sur le bruit injecté."""
    noisy_blocks = re.findall(r"# __LAFORGE_NOISE_START__.*?# __LAFORGE_NOISE_END__", text, re.DOTALL)
    total_noise_chars = sum(len(b) for b in noisy_blocks)
    return {
        "noise_blocks": len(noisy_blocks),
        "noise_chars": total_noise_chars,
        "total_chars": len(text),
        "noise_ratio_pct": round(100 * total_noise_chars / max(len(text), 1), 1),
    }
