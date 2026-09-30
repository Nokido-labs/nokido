"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_llm
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
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
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_llm.py — extrait automatiquement depuis Nokido.py
Généré par shredder.py
"""

from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
import asyncio
import re

logger = __import__("logging").getLogger(__name__)

# ── Constantes partagées (dupliquées depuis Nokido.py pour autonomie du module) ──
SHELL_COMMANDS: frozenset = frozenset(
    {
        "ls",
        "cd",
        "cat",
        "grep",
        "ps",
        "kill",
        "systemctl",
        "service",
        "apt",
        "apt-get",
        "yum",
        "dnf",
        "docker",
        "kubectl",
        "ssh",
        "scp",
        "rsync",
        "chmod",
        "chown",
        "mv",
        "cp",
        "rm",
        "mkdir",
        "rmdir",
        "touch",
        "echo",
        "export",
        "alias",
        "source",
        "sudo",
        "su",
        "crontab",
        "journalctl",
        "tail",
        "head",
        "less",
        "more",
        "nano",
        "vim",
        "vi",
        "ifconfig",
        "ip",
        "netstat",
        "ss",
        "ping",
        "traceroute",
        "nmap",
        "curl",
        "wget",
        "git",
        "make",
        "python",
        "python3",
        "pip",
        "pip3",
        "reboot",
        "shutdown",
        "halt",
        "poweroff",
        "init",
        "find",
        "awk",
        "sed",
        "tar",
        "zip",
        "unzip",
        "mount",
        "umount",
        "df",
        "du",
        "top",
        "htop",
        "free",
        "uname",
        "whoami",
        "which",
        "env",
        "printenv",
        "hostname",
    }
)
SHELL_SPECIAL_CHARS: frozenset = frozenset({"|", ">", "<", "&", ";", "$", "`", "\\", "*"})

RAG_KEYWORDS: List[str] = [
    "document",
    "doc",
    "manuel",
    "guide",
    "tutorial",
    "howto",
    "documentation",
    "exemple",
    "example",
]

# ── Patterns NLU ACTION — formulations naturelles françaises ──
_NLU_ACTION_PATTERNS: List[Tuple[re.Pattern, Optional[int]]] = [
    (re.compile(r"\b(passe|lance|exécute?|run|fais?|fait|joue)\s+(la\s+)?commande\s+(.+)", re.I), 3),
    (
        re.compile(
            r"\b(passe|lance|mets?|tape|injecte)\s+(.+?)\s+(dans|sur|via)\s+(le\s+)?(terminal|shell|bash|ssh)\b", re.I
        ),
        None,
    ),
    (re.compile(r"\b(dans|sur|via)\s+(le\s+)?(terminal|shell|bash|ssh)\b", re.I), None),
    (
        re.compile(
            r"\b(montre|affiche|donne|montre.moi|donne.moi)\s+(moi\s+)?(le\s+|les\s+|la\s+)?"
            r"(top|ps|df|free|uptime|journaux?|logs?|proc|service|port|netstat|mémoire|cpu|disque|ram|swap)\b",
            re.I,
        ),
        4,
    ),
    (
        re.compile(
            r"\b(interroge|connecte.toi|check|vérifie|inspecte|sonde|monitore)\s+(mon\s+|le\s+|ma\s+)?(serveur|server|machine|vm|vps|host)\b",
            re.I,
        ),
        None,
    ),
    (
        re.compile(
            r"\b(donne.moi|montre.moi|récupère|obtiens?|lis|lit|affiche)\s+(la\s+|le\s+)?(conf|config|configuration|settings?|status|contenu)\b",
            re.I,
        ),
        None,
    ),
    (
        re.compile(r"\b(lit|lis|cat|affiche|montre)\s+(le\s+|la\s+|les\s+|ce\s+)?(fichier|file|contenu)\s+\S+", re.I),
        None,
    ),
    (
        re.compile(
            r"(?:\btu\s+(?:peux|dois|devrais)|\bpeux.tu\b|\bpouvez.vous\b|\bpeux tu\b)\s*"
            r"(redémarre[rz]?|arrête[rz]?|stoppe[rz]?|restart(?:er)?|stop(?:per)?|start(?:er)?"
            r"|reload(?:er)?|enable[rz]?|disable[rz]?)\s+"
            r"(?!pas\b|plus\b|jamais\b|tout\b|seul\b)",
            re.I | re.MULTILINE,
        ),
        None,
    ),
    (
        re.compile(
            r"^\s*(redémarre|arrête|stoppe|restart|stop|start|reload|enable|disable|démarre)\s+"
            r"(?!pas\b|plus\b|jamais\b|tout\b|seul\b)"
            r"(le\s+|la\s+|les\s+)?(\w+)",
            re.I | re.MULTILINE,
        ),
        None,
    ),
    (re.compile(r"^\s*(installe|désinstalle|update|upgrade|purge|remove|supprime|déploie)\s+\w+", re.I), None),
    (
        re.compile(
            r"\b(scan|scanne|analyse)\s+(le\s+|les\s+|mon\s+|la\s+)?(réseau|network|ports?|services?|hôtes?|machines?)\b",
            re.I,
        ),
        None,
    ),
    (re.compile(r"\b(backup|sauvegarde[rz]?|archive[rz]?)\s+(le\s+|la\s+|les\s+)?\S+", re.I), None),
]

_CMD_EXTRACT = re.compile(r"\b(?:passe|lance|exécute?|run|fais?|fait)\s+(?:la\s+)?commande\s+(.+)", re.I)

# ── Patterns NLU RAG — recherche documentaire ──
_NLU_RAG_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(qu['\ s]?est.ce que|c['\ s]?est quoi|explique.?moi|définition de|parle.moi de|kesako)\b", re.I),
    re.compile(r"\b(comment (faire|configurer|installer|utiliser|setup|fonctionne|marche))\b", re.I),
    re.compile(r"\b(documentation|doc|manuel|guide|tuto|tutoriel)\s+(de|sur|pour|d[eu])\b", re.I),
    re.compile(r"\b(cherche|recherche|trouve.moi)\s+(des?\s+)?(doc|info|article|tuto)\b", re.I),
    re.compile(r"\b(c'est quoi|c est quoi|qu'est ce|cest quoi)\b", re.I),
]

from enum import Enum


class AgentType(Enum):
    CHAT = "chat"
    ACTION = "action"
    RAG = "rag"


import sys as _sys_f
from app.core.settings import get_settings as _forge_settings  # noqa: F401


def _debug_log(*a, **kw) -> None:
    """Debug log."""
    m = _sys_f.modules.get("__main__")
    fn = getattr(m, "debug_log", None)
    if fn:
        fn(*a, **kw)


debug_log = _debug_log


class _SettingsProxy:
    def __getattr__(self, k) -> object:
        """Getattr.

        Args:
            k: Description.
        """
        s = _forge_settings()
        return getattr(s, k, None) if s else None


settings = _SettingsProxy()


def _get_ollama_semaphore() -> asyncio.Semaphore:
    """
    Retourne (ou crée) le sémaphore de concurrence Ollama.
    Création lazy dans le bon event loop — évite 'no running event loop'.
    """
    global _ollama_semaphore
    if _ollama_semaphore is None:
        try:
            n = settings.max_concurrent_tasks or 2
            _ollama_semaphore = asyncio.Semaphore(int(n))
        except RuntimeError:
            # Pas encore d'event loop — sera créé au premier await
            _ollama_semaphore = None
            return asyncio.Semaphore(2)  # fallback local non-persisté
    return _ollama_semaphore


async def _ensure_semaphore() -> asyncio.Semaphore:
    """Version async garantie dans le bon event loop."""
    global _ollama_semaphore
    if _ollama_semaphore is None:
        n = settings.max_concurrent_tasks or 2
        _ollama_semaphore = asyncio.Semaphore(int(n))
    return _ollama_semaphore


from nokido_agent.app.forge_ollama import ollama_call, ollama_stream  # noqa: F401
# [ollama_call → forge_ollama.py]


async def ollama_parallel(calls: List[Dict]) -> List[str]:
    """
    Lance N appels Ollama en parallèle via asyncio.gather + sémaphore.
    Chaque call = {"model": str, "messages": list, "system"?: str, "max_tokens"?: int}
    Retourne les réponses dans le même ordre.
    """
    tasks = [
        ollama_call(
            model=c["model"],
            messages=c["messages"],
            system=c.get("system"),
            max_tokens=c.get("max_tokens", 512),
        )
        for c in calls
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r if isinstance(r, str) else f"[Erreur: {r}]" for r in results]


# [ollama_stream → forge_ollama.py]


class IntentClassifier:
    """
    Classifieur d'intention NLU.
    Comprend les formulations naturelles françaises + commandes directes.
    """

    def __init__(self) -> None:
        """Init."""
        pass

    def classify(self, text: str) -> AgentType:
        """Classify.

        Args:
            text: Description.
        """
        intent, _ = self.classify_with_cmd(text)
        debug_log(
            hypothesis_id="H2",
            location="IntentClassifier.classify",
            message="Classification d'intention",
            data={"text_preview": text[:80], "agent": intent.value},
        )
        return intent

    # classify_hybrid — voir forge_core_models.py

    # Patterns compilés une fois au niveau classe (performance)
    _CHAT_Q_PAT = re.compile(
        r"^(quel[les]*\s|quand\s|combien\s|pourquoi\s|comment\s+(?!faire\s+pour\s+)?"
        r"est.ce\s+que\s|est-ce\s+que\s|"
        r"qu['\u2019]est|c['\u2019]est\s+quoi|"
        r"peux.tu\s|pourrais.tu\s|sais.tu\s|connais.tu\s|"
        r"explique\s|raconte\s|dis.moi\s|parle.moi\s|"
        r"je\s+veux\s+savoir|j['\u2019]ai\s+besoin\s+de\s+savoir|"
        r"sur\s+quel\s|sur\s+quoi\s|d['\u2019]o[u\u00f9]\s|"
        r"qu['\u2019]il|qu['\u2019]elle|"
        r"c['\u2019]est\s+quoi|kesako|"
        r"(je\s+(veux|voudrais|souhaite|cherche|demande)\s+(?!(?:que\s+tu\s+)?(?:lancer?|ex\u00e9cuter?|stopper?|red\u00e9marrer?|installer?|supprimer?))))",
        re.I,
    )
    _CONV_PAT = re.compile(
        r"^(merci|ok\b|okay\b|oui\b|non\b|nope\b|ouais\b|yep\b|d['\u2019]accord|"
        r"parfait|super|bien\s+s[uû]r|nickel|génial|cool|bravo|"
        r"tu\s+es|tu\s+as|tu\s+peux\s+(me\s+)?(?!(?:lancer?|ex\u00e9cuter?|stopper?))|"
        r"c['\u2019]est\s+(?!la\s+commande|un\s+service|le\s+service)|"
        r"j['\u2019]ai\s+|j['\u2019]aurais\s+|j['\u2019]aimerai|"
        r"bonjour|salut|bonsoir|coucou|hello|hi\b|"
        r"d['\u2019]o[u\u00f9]\s+viens|tu\s+t['\u2019]appelles|"
        r"tu\s+connais|tu\s+sais\s+quoi\b)",
        re.I,
    )
    # Outils système — si présents dans une question, la reroutent vers ACTION
    _SYS_TOOLS = frozenset(
        {
            "top",
            "ps",
            "df",
            "free",
            "uptime",
            "netstat",
            "ss",
            "tail",
            "grep",
            "cat",
            "ls",
            "journalctl",
            "nmap",
            "htop",
            "iotop",
        }
    )
    # Starters conversationnels forts (premier mot) → CHAT immédiat
    _CHAT_STARTERS = frozenset(
        {
            "oui",
            "non",
            "ok",
            "okay",
            "ouais",
            "nope",
            "si",
            "ah",
            "merci",
            "parfait",
            "super",
            "génial",
            "cool",
            "nickel",
            "bonjour",
            "salut",
            "bonsoir",
            "coucou",
            "hello",
            "pourquoi",
            "quand",
            "combien",
            "lequel",
            "laquelle",
        }
    )

    def classify_with_cmd(self, text: str) -> Tuple[AgentType, Optional[str]]:
        """
        Retourne (AgentType, commande_extraite_ou_None).
        ORDRE DE PRIORITÉ v3 :
          0. CHAT_STARTERS (premier mot conversationnel fort) → CHAT immédiat
          1. Commande shell directe (premier mot dans SHELL_COMMANDS)
          2. Questions/conversations françaises → CHAT  ← AVANT les chars shell
          3. Chars shell vrais (|><&;$`\\*)
          4. Patterns NLU ACTION (formulations naturelles)
          5. Patterns NLU RAG
          6. Keywords RAG legacy
          7. CHAT fallback
        """
        # ── MARQUEUR DEBUG — détecte si [CONTEXTE CIBLE] passe encore ici ───
        _ctx_leak = "[CONTEXTE CIBLE]" in text or "[DEMANDE]" in text
        if _ctx_leak:
            debug_log(
                "ROUTE",
                "classify_with_cmd",
                "⚠ BUG DETECTE: contexte enrichi reçu au lieu du raw_input",
                {"preview": text[:80], "len": len(text)},
            )
        lower = text.lower().strip()
        words = lower.split()
        first = words[0] if words else ""

        # ── 0. CHAT_STARTERS : premier mot conversationnel fort → CHAT immédiat ─
        # Ex: "oui bien sûr", "ok merci", "non pas ça", "bonjour"
        if first in self._CHAT_STARTERS and len(words) <= 8:
            # Court + commence par mot conv → pas une commande
            debug_log(
                "ROUTE",
                "IntentClassifier.classify_with_cmd",
                "CHAT_STARTER priority",
                {"first": first, "len": len(words), "text": text[:80]},
            )
            return AgentType.CHAT, None

        # ── 1. Premier mot = commande shell directe ───────────────────────────
        if first in SHELL_COMMANDS:
            debug_log(
                "ROUTE", "IntentClassifier.classify_with_cmd", "SHELL_CMD direct", {"first": first, "text": text[:80]}
            )
            return AgentType.ACTION, text.strip()

        # ── 2. Question / conversation française → CHAT (prioritaire) ─────────
        # NB : vérifie AVANT les chars shell pour éviter que "?" piège les questions
        is_question = bool(self._CHAT_Q_PAT.match(lower))
        is_conv = bool(self._CONV_PAT.match(lower))
        # ── 2b. Phrase se terminant par "?" sans contenir de vrai char shell ──
        # Ex: "quel jour sommes nous ?", "peux tu agir sur le poste ?"
        # Le "?" seul ne fait pas d'une phrase une commande shell
        _has_real_shell = any(c in text for c in {"|", ">", "<", "&", ";", "$", "`", "\\", "*"})
        _ends_with_q = lower.rstrip().endswith("?")
        if _ends_with_q and not _has_real_shell:
            is_question = True
        # ── 2c. Phrase très courte sans caractère shell → probablement CHAT ───
        if len(words) <= 3 and not _has_real_shell and first not in SHELL_COMMANDS:
            is_conv = True
        if is_question or is_conv:
            has_sys_tool = any(w in words for w in self._SYS_TOOLS)
            if not has_sys_tool:
                debug_log(
                    "ROUTE",
                    "IntentClassifier.classify_with_cmd",
                    "CHAT_QUESTION priority",
                    {"is_question": is_question, "is_conv": is_conv, "ends_with_q": _ends_with_q, "text": text[:80]},
                )
                return AgentType.CHAT, None

        # ── 3. Caractères shell vrais (|><&;$`\*) ─────────────────────────────
        # NB: ?, [, ], (, ), {, } exclus — faux-positifs massifs en français
        found_char = next((c for c in SHELL_SPECIAL_CHARS if c in text), None)
        if found_char:
            debug_log(
                "ROUTE",
                "IntentClassifier.classify_with_cmd",
                "SHELL_CHAR match",
                {"char": found_char, "text": text[:80]},
            )
            return AgentType.ACTION, text.strip()

        # ── 4. Patterns NLU ACTION ────────────────────────────────────────────
        for i, (pattern, cmd_group) in enumerate(_NLU_ACTION_PATTERNS):
            m = pattern.search(text)
            if m:
                cmd = None
                if cmd_group and cmd_group <= len(m.groups()):
                    cmd = m.group(cmd_group).strip()
                else:
                    em = _CMD_EXTRACT.search(text)
                    cmd = em.group(1).strip() if em else None
                debug_log(
                    "ROUTE",
                    "IntentClassifier.classify_with_cmd",
                    f"NLU_ACTION PAT[{i}]",
                    {"match": m.group(0)[:60], "cmd_extracted": cmd, "text": text[:80]},
                )
                return AgentType.ACTION, cmd

        # ── 5. Patterns NLU RAG ───────────────────────────────────────────────
        for pat in _NLU_RAG_PATTERNS:
            m = pat.search(text)
            if m:
                debug_log(
                    "ROUTE",
                    "IntentClassifier.classify_with_cmd",
                    "NLU_RAG match",
                    {"match": m.group(0)[:60], "text": text[:80]},
                )
                return AgentType.RAG, None

        # ── 6. RAG keywords legacy ────────────────────────────────────────────
        matched_kw = next((kw for kw in RAG_KEYWORDS if kw in lower), None)
        if matched_kw:
            debug_log(
                "ROUTE",
                "IntentClassifier.classify_with_cmd",
                "RAG_KEYWORD legacy",
                {"keyword": matched_kw, "text": text[:80]},
            )
            return AgentType.RAG, None

        debug_log("ROUTE", "IntentClassifier.classify_with_cmd", "CHAT fallback", {"text": text[:80]})
        return AgentType.CHAT, None


def looks_like_shell_command(text: str) -> bool:
    """Looks like shell command.

    Args:
        text: Description.
    """
    text = text.strip()
    if not text:
        return False
    first = text.split()[0].lower()
    if first in SHELL_COMMANDS:
        return True
    if any(c in text for c in SHELL_SPECIAL_CHARS):
        return True
    for pat, _ in _NLU_ACTION_PATTERNS:
        if pat.search(text):
            return True
    return False
