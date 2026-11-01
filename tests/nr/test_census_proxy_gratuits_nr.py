"""NR -- bancs du proxy : gratuits verifies d'abord (cost_tier 0), inconnu jamais 0, illisible exclu."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import forge_free_tier_census as C  # noqa: E402


class P:
    def __init__(self, t=None, lisible=True):
        if lisible:
            self.cost_tier = t


REG = {"loc": P(0), "cher": P(3), "flou": P(lisible=False), "neg": P(-1)}


def _reg(m):
    m.setattr(C, "_registre_proxy", lambda: REG)
    m.setattr(C, "surface_cible", lambda c: {"etat": "DISPONIBLE"})


def test_payant_exclu_illisible_exclu(monkeypatch):
    _reg(monkeypatch)
    r, e = C.filtrer_proxy(sorted(REG))
    assert r == ["loc"] and {n for n, _ in e} == {"cher", "flou", "neg"}


def test_drapeau_inclut_payant_mais_pas_illisible(monkeypatch):
    _reg(monkeypatch)
    r, e = C.filtrer_proxy(sorted(REG), True)
    assert r == ["cher", "loc"] and {n for n, _ in e} == {"flou", "neg"}


def test_abonnements_mort_metarouteurs_exclus_noms_reels(monkeypatch):
    noms = ["claude_agent_sdk", "claude_cli", "codex_cli", "copilot_cli", "gemini_cli",
            "router", "router_local", "swarm", "agent", "nervous", "ollama"]
    reg = {n: P(0) for n in noms}
    monkeypatch.setattr(C, "_registre_proxy", lambda: reg)
    r, e = C.filtrer_proxy(sorted(reg))
    assert r == ["ollama"] and len(e) == 10
    motifs = dict(e)
    assert "abonnement" in motifs["claude_cli"] and "client mort" in motifs["gemini_cli"]
    assert "meta-routeur" in motifs["swarm"]
    assert C.filtrer_proxy(sorted(reg), True)[0] == ["ollama"]


def test_cout_inconnu_jamais_zero(monkeypatch, capsys):
    _reg(monkeypatch)
    base = ["--dimensions", "swarm:forge_agent_proxy", "--bancs", "code", "--dry-run"]
    C.main_bancs(base + ["--inclure-payants"])
    out = capsys.readouterr().out
    assert "inconnu (" in out and "0.00 USD" not in out and "exclu flou" in out
    C.main_bancs(base)
    out = capsys.readouterr().out
    assert "0.00 USD" in out and "exclu cher" in out and "retenus (1) : loc" in out
