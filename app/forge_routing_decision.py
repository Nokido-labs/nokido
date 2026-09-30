# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = routing/contract
CONTRAT DE DECISION commun aux routeurs Nokido.

POURQUOI (anti-dup, CLAUDE.md §3) :
  Quatre routeurs coexistent et rendent chacun une forme differente :
    - forge_llm_router_dt.route_with_dt   -> (provider, confidence, source)
    - forge_snn_router.SNNRouter          -> taux de spikes par provider
    - app.services.intent_router.route    -> dict {action, confidence, plan, ...}
    - forge_spike_router.SpikeRouter      -> SpikeResult (etiquette de systeme)
  Un tuple ne peut pas porter l'incertitude, et c'est exactement ce qui manquait :
  le 2026-08-20, `route_with_dt` rendait "orchestrator" -- une ETIQUETTE prise pour
  un provider -- parce que la forme de retour n'obligeait a rien.

PRINCIPE :
  Un routeur peut se tromper. Il ne doit jamais se tromper SANS DIRE a quel point
  il sait qu'il peut se tromper. `confidence` seule ne suffit pas : un score eleve
  dont le second est a egalite designe une FAMILLE, pas une reponse. D'ou
  `uncertainty` et `alternatives`, qui portent ce que le scalaire ecrase.

  L'incertitude est le signal qui fait MONTER d'un niveau (cascade L0 -> L5),
  au lieu de lancer du swarm a l'aveugle.

NIVEAUX (cout croissant) :
  L0 regles/exact-match · L1 SNN (sub-ms) · L2 intention (embedding)
  L3 provider (statistique) · L4 LLM unique · L5 swarm multi-agents

  LAFORGE_PYTHON app/forge_routing_decision.py   # selftest
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Ordre = cout croissant. `next_level` doit toujours pointer plus haut.
LEVELS = ("L0", "L1", "L2", "L3", "L4", "L5")
LEVEL_NAMES = {
    "L0": "regles / exact match",
    "L1": "SNN spiking (sub-ms)",
    "L2": "intention (embedding)",
    "L3": "provider (statistique)",
    "L4": "LLM unique",
    "L5": "swarm multi-agents",
}


@dataclass
class RoutingDecision:
    """Ce qu'un routeur rend, quel que soit son etage.

    route        : action retenue ("bypass", "provider", "abstain", "escalate"...)
    provider     : provider concret, ou None si le routeur n'en designe pas
    confidence   : [0,1] — a quel point la reponse retenue est soutenue
    uncertainty  : [0,1] — a quel point le routeur DOUTE. Pas 1-confidence :
                   on peut etre confiant ET incertain (deux candidats a egalite
                   tres bien notes), ou peu confiant et certain (rien ne matche).
    evidence     : ce sur quoi la decision repose, lisible par un humain
    alternatives : [(candidat, score)] tries, top1 inclus — c'est ce qui permet
                   a l'appelant de recalculer une marge sans refaire le travail
    reason       : une phrase, la cause de CETTE decision
    level        : etage qui a decide
    next_level   : etage a essayer si l'appelant refuse cette decision, ou None
                   si le routeur estime qu'aucune escalade n'aiderait
    source       : module concret ayant produit la decision (tracabilite)
    """

    route: str
    provider: Optional[str] = None
    confidence: float = 0.0
    uncertainty: float = 1.0
    evidence: list[str] = field(default_factory=list)
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    reason: str = ""
    level: str = "L4"
    next_level: Optional[str] = None
    source: str = ""

    def __post_init__(self) -> None:
        # Un contrat qui n'est pas verifie n'est pas un contrat.
        if self.level not in LEVELS:
            raise ValueError(f"level inconnu: {self.level!r} (attendu {LEVELS})")
        if self.next_level is not None:
            if self.next_level not in LEVELS:
                raise ValueError(f"next_level inconnu: {self.next_level!r}")
            if LEVELS.index(self.next_level) <= LEVELS.index(self.level):
                # Sans cette garde, une cascade peut boucler entre deux etages.
                raise ValueError(
                    f"next_level {self.next_level} n'est pas au-dessus de {self.level}"
                )
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        self.uncertainty = max(0.0, min(1.0, float(self.uncertainty)))

    @property
    def margin(self) -> float:
        """Ecart top1 - top2. 1.0 si un seul candidat : rien ne le conteste."""
        if len(self.alternatives) < 2:
            return 1.0
        return float(self.alternatives[0][1] - self.alternatives[1][1])

    def should_escalate(self, max_uncertainty: float = 0.35) -> bool:
        """Monter d'un etage se decide sur l'INCERTITUDE, jamais sur la seule
        confiance : c'est ce qui evite de lancer le swarm a l'aveugle."""
        return self.next_level is not None and self.uncertainty > max_uncertainty

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["margin"] = self.margin
        d["level_name"] = LEVEL_NAMES.get(self.level, "")
        return d

    def __str__(self) -> str:
        p = self.provider or "-"
        return (
            f"[{self.level}] {self.route} -> {p} "
            f"conf={self.confidence:.2f} unc={self.uncertainty:.2f} "
            f"marge={self.margin:.2f} ({self.reason})"
        )


def abstention(level: str, next_level: Optional[str], reason: str, source: str = "",
               alternatives: Optional[list[tuple[str, float]]] = None) -> RoutingDecision:
    """Fabrique la decision « je ne sais pas ».

    Un etage qui s'abstient rend PLUS d'information qu'un etage qui devine :
    il dit ou aller ensuite. C'est le seul retour qui ne coute rien et ne
    ment jamais.
    """
    return RoutingDecision(
        route="abstain",
        provider=None,
        confidence=0.0,
        uncertainty=1.0,
        evidence=[],
        alternatives=alternatives or [],
        reason=reason,
        level=level,
        next_level=next_level,
        source=source,
    )


def from_legacy_tuple(provider: str, confidence: float, source: str,
                      known_providers: Optional[list[str]] = None) -> RoutingDecision:
    """Adapte l'ancien `(provider, confidence, source)` de route_with_dt.

    Valide le provider quand la liste est fournie : c'est precisement le
    controle qui manquait quand une etiquette de systeme etait rendue a la
    place d'un provider.
    """
    level = {"hard": "L0", "spike": "L1", "snn": "L1", "dt": "L3"}.get(source, "L3")
    valide = known_providers is None or provider in known_providers
    if not valide:
        return abstention(
            level, "L4", f"provider inconnu rendu par {source}: {provider!r}",
            source=source,
        )
    return RoutingDecision(
        route="provider",
        provider=provider,
        confidence=confidence,
        # L'ancienne forme ne portait pas d'incertitude : ne pas en inventer une
        # basse. 1-confidence est le majorant honnete de ce qu'on ignore.
        uncertainty=max(0.0, 1.0 - float(confidence)),
        evidence=[f"source={source}"],
        alternatives=[(provider, float(confidence))],
        reason=f"decision {source}",
        level=level,
        next_level="L4" if level != "L4" else None,
        source=source,
    )


def _selftest() -> int:
    ok, tot = 0, 0

    def check(label: str, cond: bool) -> None:
        nonlocal ok, tot
        tot += 1
        ok += bool(cond)
        print(f"  [{'OK' if cond else 'FAIL'}] {label}")

    d = RoutingDecision(route="provider", provider="claude", confidence=0.9,
                        uncertainty=0.1, alternatives=[("claude", 0.9), ("groq", 0.2)],
                        level="L1", next_level="L3", source="snn")
    check("marge calculee depuis les alternatives", abs(d.margin - 0.7) < 1e-6)
    check("pas d'escalade quand l'incertitude est basse", not d.should_escalate())

    amb = RoutingDecision(route="provider", provider="claude", confidence=0.9,
                          uncertainty=0.8, alternatives=[("claude", 0.90), ("groq", 0.89)],
                          level="L1", next_level="L3", source="snn")
    check("confiant MAIS incertain -> escalade", amb.should_escalate())
    check("marge quasi nulle sur deux candidats a egalite", amb.margin < 0.02)

    a = abstention("L1", "L3", "taux de spikes trop bas", source="snn")
    check("abstention: pas de provider", a.provider is None)
    check("abstention: incertitude maximale", a.uncertainty == 1.0)
    check("abstention: dit ou aller ensuite", a.next_level == "L3")

    leg = from_legacy_tuple("claude", 1.0, "hard", known_providers=["claude", "groq"])
    check("tuple legacy 'hard' -> L0", leg.level == "L0" and leg.provider == "claude")
    bad = from_legacy_tuple("orchestrator", 0.9, "spike", known_providers=["claude"])
    check("etiquette rendue comme provider -> abstention", bad.route == "abstain")

    try:
        RoutingDecision(route="x", level="L3", next_level="L1")
        check("next_level descendant refuse", False)
    except ValueError:
        check("next_level descendant refuse", True)
    try:
        RoutingDecision(route="x", level="LX")
        check("level inconnu refuse", False)
    except ValueError:
        check("level inconnu refuse", True)

    clamp = RoutingDecision(route="x", confidence=5.0, uncertainty=-3.0, level="L0")
    check("confidence/uncertainty bornees a [0,1]",
          clamp.confidence == 1.0 and clamp.uncertainty == 0.0)

    print(f"\n{ok}/{tot} verifications")
    return 0 if ok == tot else 1


if __name__ == "__main__":
    print("=== forge_routing_decision selftest ===")
    sys.exit(_selftest())
