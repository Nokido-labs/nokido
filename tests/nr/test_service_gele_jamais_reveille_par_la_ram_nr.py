"""NR -- un service GELE (`disabled = true`) ne revient que par INTENTION, jamais par la RAM.

Mesure du 2026-09-24 : la branche de reveil de `resourceLoop` (RAM < RAM_WAKE_PCT) rallumait
TOUT non-essentiel endormi, sans regarder `def.disabled`. QdrantSync -- ecrivain de la base RAG,
gele sur decision owner le temps du chantier « retirer les ecrivains du verrou RAG » -- aurait
ete relance des la premiere baisse de RAM : le gel ne tenait qu'au hasard du seuil.
Le rallumage volontaire reste possible (`/supervisor/service/start`, `/supervisor/wake` HTTP
authentifie) : c'est une intention, pas une regulation.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"
TOML = ROOT / "proxy_deno" / "core" / "services.toml"


def _sans_commentaires(s: str) -> str:
    return re.sub(r"(?m)^\s*//.*$|\s//\s.*$", "", s)


def _reveils_ram(src: str) -> list[str]:
    """Conditions `if (...)` qui precedent un `Waking ${...}` dans resourceLoop."""
    i = src.index("async function resourceLoop()")
    corps = _sans_commentaires(src[i:src.index("\n}", i)])
    return re.findall(r"if \(([^{]*?status === \"sleeping\"[^{]*?)\)\s*\{\s*log\(`Waking", corps, re.S)


def test_le_reveil_ram_ignore_les_services_geles():
    conds = _reveils_ram(SUP.read_text(encoding="utf-8"))
    assert conds, "branche de reveil RAM introuvable : le lecteur ne voit plus resourceLoop"
    for c in conds:
        assert "!state.def.disabled" in c, "reveil RAM sans garde `disabled` : un gel ne tient plus :\n" + c


def test_qdrant_sync_reste_gele_jusqu_a_decision_explicite():
    """Reactiver QdrantSync = decision owner apres le chantier des ecrivains RAG :
    modifier ce test DANS LE MEME COMMIT que le TOML, jamais en silence."""
    s = next(x for x in tomllib.load(TOML.open("rb"))["service"] if x["name"] == "NokidoQdrantSync")
    assert s.get("disabled") is True
    brut = TOML.read_text(encoding="utf-8")
    bloc = brut[brut.index('name = "NokidoQdrantSync"'):]
    assert "GELE 2026-09-24" in bloc[:1800] and "STOCK" in bloc[:1800], "la raison du gel a quitte la declaration"


def test_garde_du_garde():
    faux = ('async function resourceLoop() {\n  if (\n    !state.def.essential &&\n'
            '    state.status === "sleeping"\n  ) {\n    log(`Waking ${n}`);\n  }\n}\n')
    conds = _reveils_ram(faux)
    assert len(conds) == 1 and "!state.def.disabled" not in conds[0]
