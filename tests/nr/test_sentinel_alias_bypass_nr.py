"""NR — le garde Sentinel ne se franchit plus en renommant l'outil.

Revue defensive PROTOCOLS-RPC du 2026-09-19, confusion de protocole. Le pont
stdio comparait le nom BRUT de l'outil a `_SENTINEL_TOOLS`, pendant que le hub,
lui, applique `resolve_tool_name()` AVANT d'executer. Deux lectures du meme
message, et le controle portait sur celle qui ne decide pas.

Mesure avec la vraie table d'alias et la vraie liste de garde : **18 alias**
pointaient vers un outil sous garde tout en passant le pont sans validation —
dont `agy_run` (owner-only), `set_mode`, `trigger_autonomous_evolution`,
`write`, `query` et `run`. Exemple : `forge.run.run` n'est pas dans la liste,
mais le hub le resout en `run` et l'execute.

C'est mot pour mot le motif que ce depot a deja paye ailleurs : « un garde qu'on
franchit en renommant son intention ne garde rien ». La correction n'est pas
d'allonger la liste — il faudrait y ajouter chaque alias present et futur — mais
d'ALIGNER LA LECTURE sur celle qui decide.

🪤 LE PIEGE DU CORRECTIF, mesure avant d'etre ecrit. La premiere version
importait `resolve_tool_name` depuis le registry. Elle ECHOUAIT en silence et le
bypass restait grand ouvert : importer le registry tire `forge_spike_router`,
donc `torch`, dont la chaine `dill` ouvre `os.devnull` et se fait refuser par le
garde d'ecriture. Un pont stdio ne peut pas dependre de la pile ML. La table est
donc LUE par AST, sans executer le module — une seule source de verite, aucun
import lourd.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

BR = pytest.importorskip("tools.mcp_stdio_bridge")


def _sous_garde(nom: str) -> bool:
    return BR._nom_canonique(nom) in BR._SENTINEL_TOOLS


@pytest.fixture(scope="module")
def alias():
    t = BR._alias_canoniques()
    assert t, "table d'alias illisible : ce test ne mesurerait rien"
    return t


def test_aucun_alias_ne_contourne_le_garde(alias):
    """LA MORSURE. Chaque alias qui MENE a un outil garde doit etre garde."""
    fautifs = [
        f"{k} -> {v}" for k, v in alias.items()
        if v in BR._SENTINEL_TOOLS and not _sous_garde(k)
    ]
    assert not fautifs, (
        f"{len(fautifs)} alias franchissent le garde en renommant l'intention :\n  "
        + "\n  ".join(sorted(fautifs)[:12])
    )


@pytest.mark.parametrize(
    "alias_connu", ["forge.run.run", "forge_run", "forge_write", "forge.code.agy_run",
                    "forge.rag.query", "forge_set_mode"]
)
def test_les_alias_mesures_le_2026_09_19_sont_gardes(alias_connu):
    """Les formes EXACTES relevees ce jour-la, nommees une par une : un test qui
    ne cite que la propriete generale ne dit pas ce qui avait ete paye."""
    assert _sous_garde(alias_connu), f"{alias_connu} passe encore sans validation"


@pytest.mark.parametrize("direct", ["run", "write", "query", "agy_run"])
def test_les_noms_directs_restent_gardes(direct):
    """NON-REGRESSION — aligner la lecture ne doit rien retirer au garde."""
    assert _sous_garde(direct)


@pytest.mark.parametrize("libre", ["read", "governed_edit", "get_mode", "poll"])
def test_les_outils_non_sensibles_gardent_leur_bypass(libre):
    """MORSURE SYMETRIQUE — le bypass existe pour une raison (la latence). Tout
    valider serait un durcissement qui se ferait desarmer."""
    assert not _sous_garde(libre), f"{libre} est desormais valide inutilement"


def test_une_table_illisible_fait_VALIDER_et_non_passer(monkeypatch):
    """FAIL-CLOSED. Au doute on valide : la latence est le bon prix. Le contraire
    laisserait passer exactement ce que ce correctif ferme."""
    monkeypatch.setattr(BR, "_ALIAS_CACHE", [None])
    assert _sous_garde("forge.run.run"), (
        "table illisible -> bypass : le repli est fail-OPEN, c'est l'inverse de "
        "l'intention"
    )
    assert BR._FORCER_VALIDATION in BR._SENTINEL_TOOLS, (
        "la sentinelle du repli n'est pas dans la liste gardee : le fail-closed "
        "est decoratif"
    )


def test_le_pont_ne_depend_pas_de_la_pile_ML():
    """Le correctif d'origine importait le registry et echouait en silence a
    cause de torch. Verifie sur la SOURCE : aucun import du registry."""
    src = (RACINE / "tools" / "mcp_stdio_bridge.py").read_text(encoding="utf-8")
    assert "import forge_mcp_registry" not in src and \
           "from nokido_agent.app.forge_mcp_registry" not in src, (
        "le pont importe de nouveau le registry : l'import tire torch, echoue, "
        "et le bypass se rouvre en silence"
    )
