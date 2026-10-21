# -*- coding: utf-8 -*-
"""NR : l'outillage du reseau de l'owner lit ses adresses depuis la config, jamais en dur.

P1 « la version distribuable ne doit pas etre figee sur mes IP » (owner 2026-10-17).
Mesure du 17/10 : forge_vm_dns (hote de la VM), forge_swarm_team (Ollama distant) et
nokido_netmap (inventaire des appareils) portent des adresses LAN de l'owner EN DUR ; le dist
les generise en `localhost` -- l'outil publie ne vise alors plus rien. Attendu : la valeur est
lue depuis l'environnement ou un `config/*.local.toml` non suivi, avec un repli generique.

Tolere : sous-reseau par defaut (x.x.x.0/24) et passerelle Freebox standard (.254), identiques
chez tous les abonnes -- ce ne sont pas des adresses de l'owner. Les docstrings sont ignorees.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CIBLES = ["tools/forge_vm_dns.py", "app/forge_swarm_team.py", "tools/nokido_netmap.py"]
LAN = re.compile(r"\b192\.168\.\d{1,3}\.(\d{1,3})\b")
TOLERES = {"0", "254"}


def _docstrings(arbre):
    ids = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) \
                    and isinstance(n.body[0].value.value, str):
                ids.add(id(n.body[0].value))
    return ids


def _adresses_en_dur(chemin: Path) -> list:
    arbre = ast.parse(chemin.read_text(encoding="utf-8"), filename=str(chemin))
    docs = _docstrings(arbre)
    trouves = []
    for n in ast.walk(arbre):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            for m in LAN.finditer(n.value):
                if m.group(1) not in TOLERES:
                    trouves.append("L%d" % n.lineno)
    return trouves


@pytest.mark.parametrize("rel", CIBLES)
def test_aucune_adresse_lan_de_l_owner_en_dur(rel):
    chemin = ROOT / rel
    assert chemin.is_file(), "cible absente : %s" % rel
    trouves = _adresses_en_dur(chemin)
    assert not trouves, (
        "%s porte %d adresse(s) LAN en dur (%s) : la lire depuis l'environnement ou "
        "config/*.local.toml, repli generique" % (rel, len(trouves), ", ".join(trouves[:10])))


def test_le_detecteur_voit_une_adresse_et_tolere_sous_reseau_et_passerelle(tmp_path):
    f = tmp_path / "x.py"
    f.write_text('"""doc localhost"""\nA = "http://localhost:11434"\n'
                 'B = "localhost/24"\nC = "http://localhost"\n', encoding="utf-8")
    assert _adresses_en_dur(f) == ["L2"]
