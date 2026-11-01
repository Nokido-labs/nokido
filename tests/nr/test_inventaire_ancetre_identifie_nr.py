# -*- coding: utf-8 -*-
"""NR (28/10, owner : « prouver l'origine SYSTEMATIQUEMENT ») : un processus herite de l'identite de son ANCETRE
identifie, a n'importe quelle profondeur, quel que soit son nom.

Mesure 28/10 : docker-mcp.exe (port 8811) sortait « ECOUTANT non revendique, nokido=None » alors qu'il descend du
service NokidoDockerMcpGateway : lanceur runas (pid du superviseur) -> gardien python -> docker.exe ->
docker-mcp.exe. L'heritage ne remontait qu'UN parent ; la remontee profonde n'etait faite que pour les RUNTIMES."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_process_inventory as inv  # noqa: E402

VIVANTS = {
    10: {"nom": "python.exe", "ppid": 1, "cree": 100.0},       # lanceur runas : pid connu du superviseur
    11: {"nom": "python.exe", "ppid": 10, "cree": 101.0},      # gardien
    12: {"nom": "docker.exe", "ppid": 11, "cree": 102.0},      # CLI docker
    13: {"nom": "docker-mcp.exe", "ppid": 12, "cree": 103.0},  # gateway (ecoute 8811)
    20: {"nom": "inconnu.exe", "ppid": 1, "cree": 104.0},      # sans ancetre identifie
}


def test_descendant_profond_rattache_au_service():
    ident = inv.ancetre_identifie(13, VIVANTS, {10: "NokidoDockerMcpGateway"}, {})
    assert ident == {"identite": "descendant de NokidoDockerMcpGateway", "preuve": "parente", "profondeur": 3}


def test_sans_ancetre_identifie_reste_none():
    assert inv.ancetre_identifie(20, VIVANTS, {10: "NokidoDockerMcpGateway"}, {}) is None


def test_identite_prouvee_par_ailleurs_reprise():
    ident = inv.ancetre_identifie(13, VIVANTS, {}, {"11": {"identite": "gardien gateway", "preuve": "battement"}})
    assert ident["identite"] == "descendant de gardien gateway" and ident["profondeur"] == 2


def test_cycle_de_parente_ne_boucle_pas():
    cyc = {1: {"nom": "a.exe", "ppid": 2}, 2: {"nom": "b.exe", "ppid": 1}}
    assert inv.ancetre_identifie(1, cyc, {}, {}) is None


def test_collect_n_appelle_plus_inconnu_un_descendant():
    src = (ROOT / "tools" / "forge_process_inventory.py").read_text(encoding="utf-8")
    assert "ancetre_identifie(pid, vivants, pid_service" in src, "collect() ne consulte pas l'ancetre identifie"
