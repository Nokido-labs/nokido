"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
sandbox_nlu.py — Test NLU patterns Nokido v0.13.2
Sans import Nokido — charge directement les patterns depuis le source.
"""
import sys, time, re

sys.path.insert(0, "app")

from typing import List, Tuple, Optional
from enum import Enum


class AgentType(Enum):
    """Agenttype."""

    CHAT = "chat"
    ACTION = "action"
    RAG = "rag"


# ── Charger _NLU_ACTION_PATTERNS depuis Nokido.py ───────────────────────────
src = open("Nokido.py", encoding="utf-8").read()

# Extraire le bloc _NLU_ACTION_PATTERNS
start = src.index("_NLU_ACTION_PATTERNS: List")
end = src.index("\n# Pattern d'extraction", start)
block = src[start:end]

ns = {"re": re, "List": List, "Tuple": Tuple, "Optional": Optional}
exec(block, ns)
ACTION_PATS = ns["_NLU_ACTION_PATTERNS"]

# Extraire _NLU_RAG_PATTERNS
start2 = src.index("_NLU_RAG_PATTERNS: List")
end2 = src.index("\n\n", start2)
block2 = src[start2:end2]
exec(block2, ns)
RAG_PATS = ns["_NLU_RAG_PATTERNS"]

# Extraire _CHAT_Q_PAT et _CONV_PAT
ns2 = {"re": re}
for pat_name in ["_CHAT_Q_PAT", "_CONV_PAT", "_CHAT_STARTERS"]:
    idx = src.index(f"{pat_name} = ")
    end3 = src.index("\n    _", idx) if "_CHAT_STARTERS" not in pat_name else src.index("\n\n", idx)
    exec(src[idx:end3].strip(), ns2)

CHAT_Q = ns2.get("_CHAT_Q_PAT")
CONV_PAT = ns2.get("_CONV_PAT")
CHAT_STARTS = ns2.get("_CHAT_STARTERS", frozenset())

SHELL_CMDS = frozenset(
    {
        "ls",
        "df",
        "ps",
        "top",
        "cat",
        "grep",
        "tail",
        "head",
        "find",
        "systemctl",
        "journalctl",
        "netstat",
        "ss",
        "nmap",
        "htop",
        "iotop",
        "apt",
        "pip",
        "docker",
        "kubectl",
        "chmod",
        "chown",
        "kill",
        "pkill",
        "free",
        "uptime",
        "uname",
        "lsof",
        "ip",
        "ifconfig",
        "ping",
        "traceroute",
        "curl",
        "wget",
        "ssh",
        "scp",
        "rsync",
    }
)


def classify(text: str) -> Tuple[str, float]:
    """Classify."""
    words = text.lower().split()
    first = words[0].rstrip(".,;:!?") if words else ""

    # 0. CHAT starters forts (premier mot conversationnel)
    if first in CHAT_STARTS:
        return "chat", 0.88

    # 1. Commande shell directe (premier mot = binaire)
    if first in SHELL_CMDS:
        return "action", 0.92

    # 2. Chars shell vrais
    if re.search(r"[|><&;$`\\*]", text):
        return "action", 0.78

    # 3. Patterns NLU ACTION — AVANT les questions françaises
    # ("quel est l'état" doit partir en ACTION, pas CHAT)
    for pat, _ in ACTION_PATS:
        if pat.search(text):
            return "action", 0.75

    # 4. Questions françaises → CHAT (sauf si déjà capturé ACTION)
    if CHAT_Q and CHAT_Q.search(text):
        return "chat", 0.80
    if CONV_PAT and CONV_PAT.search(text):
        return "chat", 0.82

    # 5. Patterns NLU RAG
    for pat in RAG_PATS:
        if pat.search(text):
            return "rag", 0.72

    return "chat", 0.58


# ── Tests ─────────────────────────────────────────────────────────────────────
tests = [
    # ACTION claires
    ("liste les fichiers dans /var/log", "action"),
    ("liste les processus actifs", "action"),
    ("liste les services", "action"),
    ("redémarre nginx", "action"),
    ("df -h", "action"),
    ("ps aux | grep python", "action"),
    ("quel est l'état du disque", "action"),
    ("quel est l'espace disque", "action"),
    ("quelle est la mémoire disponible", "action"),
    ("quel est le statut de nginx", "action"),
    ("montre les logs nginx", "action"),
    # CHAT claires
    ("explique moi asyncio", "chat"),
    ("comment fonctionne docker", "chat"),
    ("pourquoi le bat ne fonctionnait pas", "chat"),
    ("merci", "chat"),
    ("ok", "chat"),
    ("bonjour", "chat"),
    # RAG
    ("cherche dans le code _protect_source", "rag"),
    ("trouve la fonction _dispatch_ai", "rag"),
    # Ambigus importants
    ("optimise brain_worker", "action"),
    ("aide moi", "chat"),
]

print()
print("═══ NLU ROUTING TEST v0.13.2 ═══════════════")
print(f"  {'Input':42s} {'Attendu':8s} {'Got':8s} {'Conf':6s} {'✓'}")
print("  " + "─" * 72)

ok = 0
total_ms = 0
for txt, expected in tests:
    t0 = time.monotonic()
    got, conf = classify(txt)
    ms = (time.monotonic() - t0) * 1000
    total_ms += ms
    match = "✅" if got == expected else "⚠️ "
    flag = "🎯" if conf >= 0.72 else ("~" if conf >= 0.58 else "?")
    if got == expected:
        ok += 1
    print(f"  {match} {txt[:41]:42s} {expected:8s} {got:8s} {conf:.2f}  {flag}")

print("  " + "─" * 72)
acc = ok / len(tests) * 100
avg = total_ms / len(tests)
print(f"  Accuracy : {ok}/{len(tests)} ({acc:.0f}%) | Moy : {avg:.3f}ms")

if acc >= 90:
    print("  ✅ NLU OK — routing rapide et précis")
elif acc >= 80:
    print(f"  ⚠️  NLU correct ({acc:.0f}%) — quelques cas à améliorer")
else:
    print(f"  ❌ NLU insuffisant ({acc:.0f}%)")
print("════════════════════════════════════════════")
sys.exit(0 if acc >= 80 else 1)
