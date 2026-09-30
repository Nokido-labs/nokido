"""NR 2026-09-27 -- la rafale RAM du superviseur n'endort plus le runner CI en plein job.

MESURE (journal du superviseur, logs/supervisor/laforge-master.log) : deux fois le meme jour,
les deux pendant `pytest-pur` --
  20:01:41 Sleeping NokidoCIRunner                                  (run 36337595514)
  20:47:04 RAM 97.0% > 88% -- sleeping non-essential services
           Sleeping NokidoCIRunner (uptime 1765s)                   (run 36340236121)
Listener et Worker du runner se taisent a la meme seconde (_diag), GitHub le voit `offline`,
le job depasse sa borne et sort `cancelled` : un verdict ILLISIBLE lu comme une CI rouge.

Le NR emprunte le CHEMIN REEL : la cle telle que le TOML la porte, la cle telle que le chargeur
Deno la lit, et la condition de la rafale telle que le superviseur l'evalue. Un `neverSleep`
ecrit sous une autre casse, ou une rafale qui cesserait de le consulter, rouvrirait le trou
sans qu'aucun test de la seule valeur TOML ne le voie.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
CORE = RACINE / "proxy_deno" / "core"


def _runner() -> dict:
    services = tomllib.loads((CORE / "services.toml").read_text(encoding="utf-8"))["service"]
    trouves = [s for s in services if s.get("name") == "NokidoCIRunner"]
    assert len(trouves) == 1, "NokidoCIRunner declare %d fois dans services.toml" % len(trouves)
    return trouves[0]


def test_le_runner_ci_est_exempte_de_la_rafale_ram():
    r = _runner()
    if r.get("disabled", False):
        return  # runner coupe par choix : rien a proteger (DISABLED_BY_POLICY, pas une panne)
    assert r.get("neverSleep") is True, \
        "runner CI endormi par la rafale RAM : il tue le job en cours et le run sort cancelled"
    # l'exemption ne doit pas deguiser le runner en service essentiel : l'eviction CIBLEE
    # et le demarrage sous pression restent regules comme avant
    assert r.get("essential") is False, "neverSleep suffit ; essential changerait la regulation au boot"


def test_le_chargeur_lit_la_cle_sous_cette_casse():
    src = (CORE / "service_loader.ts").read_text(encoding="utf-8")
    assert re.search(r"\bs\.neverSleep\b", src), \
        "service_loader.ts ne lit plus `neverSleep` : la cle du TOML deviendrait lettre morte"


def test_la_rafale_consulte_never_sleep():
    src = (CORE / "supervisor.ts").read_text(encoding="utf-8")
    i = src.find("sleeping non-essential services")
    assert i != -1, "rafale RAM introuvable dans supervisor.ts : relire ce NR contre le nouveau code"
    fenetre = src[i: i + 800]
    assert "state.def.neverSleep" in fenetre, \
        "la rafale RAM n'exempte plus neverSleep : le runner CI serait de nouveau endormi en plein job"
