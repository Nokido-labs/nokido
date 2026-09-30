"""
FORGE INTELLIGENCE — forge_parity_gate [GREEN]
================================================
Gate DÉTERMINISTE générique : un registre de SIGNAUX (fonctions pures) émettant
chacun un Finding gradé (RED / YELLOW / UNKNOWN) à partir de features
STRUCTURELLES/mesurables, puis une agrégation CONSERVATRICE :

    any RED   -> RED      (hard-fail, block)
    any YELLOW-> YELLOW    (warn, le caller décide)
    any UNKNOWN-> UNKNOWN  (données insuffisantes — JAMAIS certifié vert)
    sinon     -> GREEN
    0 signal exécuté -> UNKNOWN (on ne certifie pas vert sans contrôle)

Principe clé : un signal qui ne peut pas évaluer renvoie UNKNOWN (pas None) ;
None = « ce signal a regardé et ne voit pas de problème ». => never-false-GREEN.

Pourquoi un nouveau module (anti-dup CLAUDE.md §3) :
- forge_quality_gate = pipeline FIXE (AST + pylint + coverage + TODO), verdict
  binaire ok/ko. PAS un registre pluggable, PAS de graduation RED/YELLOW/GREEN.
- forge_scorecard = JUGE (gate déterministe + LLM-judge, stratégie AND-min) qui
  COMPOSE/peut compromettre ; aucune règle « un RED = hard-fail », pas de
  never-false-GREEN, pas de signaux pluggables.
Inspiration : parity-engine de auto-re-agent (signals.py + verification/objective.py),
généralisé hors reverse-engineering.

Réutilisé par : scan du gate egress git (gitleaks/entropie/manifeste = signaux),
acceptation de patch SWE, vérification structurelle de sorties LLM.
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    GREEN = "green"
    YELLOW = "yellow"
    UNKNOWN = "unknown"
    RED = "red"


@dataclass
class Finding:
    """Émis par un signal. `signal` est rempli automatiquement par evaluate()
    si laissé vide. level ∈ {RED, YELLOW, UNKNOWN} (None côté signal = OK)."""
    level: Severity
    reason: str
    signal: str = ""
    meta: dict = field(default_factory=dict)


# Fabriques courtes (le nom du signal est injecté par evaluate()).
def red(reason: str, **meta: Any) -> Finding:
    return Finding(Severity.RED, reason, meta=meta)


def yellow(reason: str, **meta: Any) -> Finding:
    return Finding(Severity.YELLOW, reason, meta=meta)


def unknown(reason: str, **meta: Any) -> Finding:
    return Finding(Severity.UNKNOWN, reason, meta=meta)


@dataclass
class GateResult:
    status: Severity
    findings: list[Finding]
    ran: int

    @property
    def ok(self) -> bool:
        """True seulement si certifié GREEN (contrôles passés, données suffisantes)."""
        return self.status is Severity.GREEN

    @property
    def blocked(self) -> bool:
        """True si au moins un signal RED -> hard-fail."""
        return self.status is Severity.RED

    def reasons(self, level: Severity | None = None) -> list[str]:
        return [f"{f.signal}: {f.reason}" for f in self.findings
                if level is None or f.level is level]

    def summary(self) -> str:
        return (f"[{self.status.value.upper()}] {self.ran} signaux, "
                f"{len(self.findings)} findings"
                + (f" :: {'; '.join(self.reasons())}" if self.findings else ""))


Signal = Callable[[Mapping[str, Any]], Optional[Finding]]
_REGISTRY: dict[str, dict] = {}


def register_signal(name: str, group: str = "default") -> Callable[[Signal], Signal]:
    """Décorateur : enregistre un signal pur sous (name, group)."""
    def deco(fn: Signal) -> Signal:
        _REGISTRY[name] = {"fn": fn, "group": group}
        return fn
    return deco


def signals(group: str | None = None) -> dict[str, dict]:
    return {n: s for n, s in _REGISTRY.items() if group is None or s["group"] == group}


def _coerce(r: Any, name: str) -> Finding | None:
    if r is None:
        return None
    if isinstance(r, Finding):
        if not r.signal:
            r.signal = name
        return r
    if isinstance(r, tuple) and len(r) >= 2:  # (level, reason)
        lvl = r[0] if isinstance(r[0], Severity) else Severity(str(r[0]).lower())
        return Finding(lvl, str(r[1]), signal=name)
    raise TypeError(f"signal {name} a renvoyé un type invalide: {type(r)}")


def _aggregate(findings: list[Finding], ran: int) -> GateResult:
    if ran == 0:
        return GateResult(Severity.UNKNOWN, findings, 0)
    levels = {f.level for f in findings}
    for sev in (Severity.RED, Severity.YELLOW, Severity.UNKNOWN):
        if sev in levels:
            return GateResult(sev, findings, ran)
    return GateResult(Severity.GREEN, findings, ran)


def evaluate(ctx: Mapping[str, Any], group: str | None = None,
             extra: list[Signal] | None = None) -> GateResult:
    """Exécute les signaux (registre filtré par `group` + `extra` ad hoc) sur
    `ctx` et agrège conservativement. Un signal qui crashe -> UNKNOWN (jamais
    de faux vert silencieux)."""
    fns: list[tuple[str, Signal]] = [(n, s["fn"]) for n, s in signals(group).items()]
    if extra:
        fns += [(getattr(f, "__name__", f"extra_{i}"), f) for i, f in enumerate(extra)]
    findings: list[Finding] = []
    for name, fn in fns:
        try:
            f = _coerce(fn(ctx), name)
        except Exception as e:  # noqa: BLE001 — un signal cassé ne certifie pas vert
            findings.append(Finding(Severity.UNKNOWN, f"signal crash: {e}", signal=name))
            continue
        if f is not None:
            findings.append(f)
    return _aggregate(findings, len(fns))


class ParityError(Exception):
    """Levée par block_if_red() quand le gate est RED."""


def block_if_red(result: GateResult) -> GateResult:
    if result.blocked:
        raise ParityError("PARITY RED :: " + "; ".join(result.reasons(Severity.RED)))
    return result


# === Briques réutilisables (vérification structurelle conservatrice) =========

def structural_mismatch(observed: float | int | None, expected: float | int | None,
                        tolerance: float = 0, *, directional: bool = True,
                        label: str = "value", level: Severity = Severity.RED) -> Finding | None:
    """FAIL (Finding) seulement sur écart FORT. `directional` ne pénalise que la
    sous-implémentation (observed < expected). UNKNOWN si une valeur manque.
    Conservateur comme verification/objective.py d'auto-re-agent."""
    if observed is None or expected is None:
        return unknown(f"{label}: donnée manquante (observed={observed}, expected={expected})")
    diff = (expected - observed) if directional else abs(observed - expected)
    if diff > tolerance:
        return Finding(level, f"{label} mismatch: observed={observed} expected={expected} "
                              f"(diff {diff} > tol {tolerance})",
                       meta={"observed": observed, "expected": expected, "diff": diff})
    return None


def shannon_entropy(data: str | bytes) -> float:
    """Entropie de Shannon (bits/octet). Sert au scan secrets/données encodées."""
    if not data:
        return 0.0
    if isinstance(data, str):
        data = data.encode("utf-8", "ignore")
    freq: dict[int, int] = {}
    for b in data:
        freq[b] = freq.get(b, 0) + 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def entropy_signal(text: str, threshold: float = 4.5, *, label: str = "entropy",
                   level: Severity = Severity.YELLOW) -> Finding | None:
    """Finding si l'entropie dépasse le seuil (secret/blob chiffré probable)."""
    e = shannon_entropy(text)
    if e > threshold:
        return Finding(level, f"{label} élevée {e:.2f} > {threshold} (secret/encodé probable)",
                       meta={"entropy": round(e, 3)})
    return None


def _selftest() -> int:
    @register_signal("demo_struct", group="_selftest")
    def _r(ctx):
        return structural_mismatch(ctx.get("calls"), ctx.get("expected_calls"),
                                   tolerance=3, label="calls")

    @register_signal("demo_entropy", group="_selftest")
    def _e(ctx):
        return entropy_signal(ctx.get("blob", ""), threshold=4.5)

    cases = {
        "GREEN": {"calls": 10, "expected_calls": 11, "blob": "hello world"},
        "RED": {"calls": 1, "expected_calls": 9, "blob": "hello world"},
        "YELLOW": {"calls": 10, "expected_calls": 10,
                   "blob": "aZ9$kQ2#vX7!mP4&wL1@nR8^bT5*cY3qD6%"},
        "UNKNOWN": {"expected_calls": 9, "blob": "hi"},  # 'calls' absent -> insuffisant
    }
    ok = True
    for expect, ctx in cases.items():
        res = evaluate(ctx, group="_selftest")
        got = res.status.value.upper()
        flag = "OK" if got == expect else "FAIL"
        ok = ok and flag == "OK"
        print(f"[{flag}] attendu={expect} obtenu={got} :: {res.summary()}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
