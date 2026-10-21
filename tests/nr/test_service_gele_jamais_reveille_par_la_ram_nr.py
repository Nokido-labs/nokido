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


# --- Sommeil VOULU (bail de priorite, 17/10) -------------------------------------------------------------------------
# Mesure 16/10 (logs/supervisor/laforge-master.log) : 21:36:16 POST /supervisor/sleep/NokidoDeportEmbed (le bail de la
# CI de reference) ; 21:37:07 « Waking NokidoDeportEmbed (RAM now 69.7%) » SANS trace POST -- le reveil RAM levait un
# sommeil VOULU 51 s apres, en pleine CI. Un sommeil explicite porte une ECHEANCE bornee (jamais eternel : un appelant
# qui compterait sur le reveil RAM ne perd pas son service pour toujours) ; seule une intention (wake, restart) le leve.
def _branche(src: str, action: str) -> str:
    i = src.index('if (action === "%s") {' % action)
    return _sans_commentaires(src[i:src.index("\n    }", i)])


def test_le_reveil_ram_respecte_un_sommeil_voulu():
    conds = _reveils_ram(SUP.read_text(encoding="utf-8"))
    assert conds
    for c in conds:
        assert "sommeilVouluJusquaMs" in c, "reveil RAM sans garde du sommeil voulu : un bail ne tient pas :\n" + c


def test_le_sommeil_explicite_pose_une_echeance_bornee():
    b = _branche(SUP.read_text(encoding="utf-8"), "sleep")
    assert "state.sommeilVouluJusquaMs = Date.now() +" in b and "SOMMEIL_VOULU_TTL_MS" in b, b


def test_une_intention_leve_le_sommeil_voulu():
    src = SUP.read_text(encoding="utf-8")
    for action in ("wake", "restart"):
        assert "state.sommeilVouluJusquaMs = 0" in _branche(src, action), action
