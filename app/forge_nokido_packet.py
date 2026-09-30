# -*- coding: utf-8 -*-
"""
forge_nokido_packet.py — Nokido Packet Header v1.0
=====================================================
Format : LF[S][D][R][P][AAA]  — 10 chars, 3-4 tokens

  LF       : magic (1 token)
  S        : Source  C=Claude G=Gemini H=Hub B=Browser W=Worker V=Vibe M=Mistral
  D        : Dest    (même alphabet)
  R        : Ring    0-9
  P        : Priorité 0-9  (9=urgence, 0=background)
  AAA      : Action  ING=Ingest QUE=Query EVO=Evolve NOT=Notify
                     ERR=Error  ACK=Ack   FLW=Flow   URL=UrlRead
                     SCH=Search RUN=Run   WRT=Write  MEM=Memory

Exemples :
  LFGC09ING    Gemini→Claude  ring=0 prio=9 Ingest
  LFCH03QUE    Claude→Hub     ring=0 prio=3 Query
  LFHH00ERR    Hub→Hub        ring=0 prio=0 Error
  LFBC13URL    Browser→Claude ring=1 prio=3 UrlRead

Reject Policy par ring :
  ring 0 : correct silencieusement (confiance totale)
  ring 1 : reject + log audit
  ring 2+: drop pur

Usage :
  from forge_nokido_packet import LFPacket, parse_header, make_header, reject_policy

  hdr = make_header(src="C", dst="H", ring=0, prio=5, action="QUE")
  # → "LFCH05QUE"

  pkt = parse_header("LFGCH09ING reste du message")
  # → LFPacket(src="G", dst="C", ring=0, prio=9, action="ING", body="reste du message")
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Optional

# ── Alphabets ─────────────────────────────────────────────────────────────────
AGENTS = {
    "C": "CLAUDE",
    "G": "GEMINI",
    "H": "HUB",
    "B": "BROWSER",
    "W": "WORKER",
    "V": "VIBE",
    "M": "MISTRAL",
    "I": "INSPECTOR",
    "X": "EXTERNAL",
}
AGENT_TO_CODE = {v: k for k, v in AGENTS.items()}

ACTIONS = {
    "ING": "ingest",
    "QUE": "query",
    "EVO": "evolve",
    "NOT": "notify",
    "ERR": "error",
    "ACK": "ack",
    "FLW": "flow",
    "URL": "url_read",
    "SCH": "search",
    "RUN": "run",
    "WRT": "write",
    "MEM": "memory",
    "HBT": "heartbeat",
    "TLM": "telemetry",
}

MAGIC = "LF"
HEADER_RE = re.compile(r"^LF([CGHBWVMIX])([CGHBWVMIX])([0-9])([0-9])([A-Z]{3})(.*)", re.DOTALL)


# ── Dataclass ─────────────────────────────────────────────────────────────────
@dataclass
class LFPacket:
    src: str  # lettre agent source
    dst: str  # lettre agent dest
    ring: int  # 0-9
    prio: int  # 0-9 (9=urgence)
    action: str  # 3 lettres
    body: str = ""  # reste du message
    raw: str = ""  # header brut original

    @property
    def src_name(self) -> str:
        return AGENTS.get(self.src, self.src)

    @property
    def dst_name(self) -> str:
        return AGENTS.get(self.dst, self.dst)

    @property
    def action_name(self) -> str:
        return ACTIONS.get(self.action, self.action.lower())

    @property
    def is_critical(self) -> bool:
        return self.ring == 0 or self.prio >= 8

    def to_header(self) -> str:
        return f"LF{self.src}{self.dst}{self.ring}{self.prio}{self.action}"

    def __str__(self) -> str:
        return f"[{self.to_header()}] {self.src_name}→{self.dst_name} ring={self.ring} prio={self.prio} act={self.action_name}"


# ── Parsing ────────────────────────────────────────────────────────────────────
def parse_header(text: str) -> Optional[LFPacket]:
    """
    Parse un message commençant par un header LF.
    Retourne None si le message n'a pas de header LF valide.
    """
    m = HEADER_RE.match(text.strip())
    if not m:
        return None
    src, dst, ring, prio, action, body = m.groups()
    return LFPacket(
        src=src,
        dst=dst,
        ring=int(ring),
        prio=int(prio),
        action=action,
        body=body.lstrip(),
        raw=text[:10],
    )


def make_header(
    src: str = "H",
    dst: str = "C",
    ring: int = 0,
    prio: int = 5,
    action: str = "NOT",
) -> str:
    """
    Forge un header LF compact (10 chars, 3-4 tokens).
    src/dst : lettre (C G H B W V M I X) ou nom complet (CLAUDE GEMINI HUB...)
    """
    s = AGENT_TO_CODE.get(src.upper(), src[0].upper()) if len(src) > 1 else src.upper()
    d = AGENT_TO_CODE.get(dst.upper(), dst[0].upper()) if len(dst) > 1 else dst.upper()
    r = max(0, min(9, int(ring)))
    p = max(0, min(9, int(prio)))
    a = action[:3].upper()
    return f"LF{s}{d}{r}{p}{a}"


# ── Reject Policy ──────────────────────────────────────────────────────────────
REJECT_POLICY = {
    0: "correct",  # ring 0 : Hub corrige silencieusement
    1: "reject_log",  # ring 1 : retour ERR + log audit
    2: "drop",  # ring 2+: drop pur
}


def reject_policy(ring: int) -> str:
    return REJECT_POLICY.get(ring, "drop")


def make_error_response(original: LFPacket, reason: str) -> str:
    """
    Forge un paquet ERR en réponse à un paquet invalide.
    Ring 1 only — ring 2+ → retour None (drop pur).
    """
    if original.ring >= 2:
        return ""  # drop pur, pas d'info au caller
    err_hdr = make_header(
        src="H",
        dst=original.src,
        ring=original.ring,
        prio=9,
        action="ERR",
    )
    return f"{err_hdr} REJECT:{reason[:80]}"


# ── Spike Router — décision en 20 premiers chars ─────────────────────────────
class SpikeRouter:
    """
    Intercepte les messages entrants et prend une décision de routage
    SANS lire le body complet — exactement comme Gemini l'a décrit.
    """

    def __init__(self):
        self._routes: dict[str, list] = {}  # action → [handlers]

    def register(self, action: str, handler):
        self._routes.setdefault(action, []).append(handler)

    def route(self, text: str) -> tuple[Optional[LFPacket], Optional[object]]:
        """
        Lit les 20 premiers chars, prend une décision immédiate.
        Retourne (packet, handler) ou (None, None) si pas de header.
        """
        pkt = parse_header(text[:200])  # parse léger sur le début
        if pkt is None:
            return None, None
        handlers = self._routes.get(pkt.action, [])
        if not handlers:
            return pkt, None
        # Priorité : prendre le handler le plus récent
        return pkt, handlers[-1]

    def should_inhibit(self, pkt: LFPacket, system_load: float) -> bool:
        """
        Inhibition corticale : suspend les packets non-critiques
        si system_load > 80% (gestion énergie endocrine).
        """
        if pkt.is_critical:
            return False
        if system_load > 0.8 and pkt.prio < 5:
            return True
        return False


# ── Instance globale ──────────────────────────────────────────────────────────
_router = SpikeRouter()


def get_router() -> SpikeRouter:
    return _router


# ── Injection dans les messages hub ──────────────────────────────────────────
def inject_header(
    message: str, src: str = "H", dst: str = "C", ring: int = 0, prio: int = 5, action: str = "NOT"
) -> str:
    """Préfixe un message texte avec un header LF si pas déjà présent."""
    if message.startswith("LF"):
        return message  # déjà headérisé
    hdr = make_header(src=src, dst=dst, ring=ring, prio=prio, action=action)
    return f"{hdr} {message}"


def strip_header(text: str) -> tuple[Optional[LFPacket], str]:
    """Sépare header et body. Retourne (None, text) si pas de header."""
    pkt = parse_header(text)
    if pkt:
        return pkt, pkt.body
    return None, text


if __name__ == "__main__":
    # Test rapide
    tests = [
        ("LFGCH09ING payload here", True),
        ("LFCHG03QUE SELECT * FROM rag_chunks", True),
        ("LFHH00ERR REJECT:invalid_ring", True),
        ("pas de header", False),
        ("LFX invalid", False),
    ]
    print("=== Nokido Packet Header Tests ===")
    for txt, expect in tests:
        pkt = parse_header(txt)
        ok = (pkt is not None) == expect
        status = "✓" if ok else "✗"
        print(f"  {status} '{txt[:30]}' → {pkt}")

    print()
    hdr = make_header("CLAUDE", "HUB", ring=0, prio=7, action="QUE")
    print(f"make_header CLAUDE→HUB ring=0 prio=7 QUE : {hdr}")
    print(f"inject: {inject_header('SELECT * FROM rag_chunks', src='C', dst='H', ring=0, prio=5, action='QUE')}")
