# -*- coding: utf-8 -*-
"""NR -- plan d'homogeneisation de l'interface (owner 1/11, Pole 1 d'abord). Mesure : 177 couleurs en dur (#hex hors
jetons) dans les pages du web_hub ; launcher_html.py en portait 36 (palette Tailwind slate) alors que la page charge
deja /static/nokido.css, source des jetons laforge-ds. Une page migree n'emploie que des jetons (var(--...)).
Une entite HTML (&#9888;) n'est pas une couleur."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "app" / "web_hub"
COULEUR = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b")


def couleurs(chemin: Path) -> list[str]:
    return COULEUR.findall(chemin.read_text(encoding="utf-8", errors="replace"))


def test_une_entite_html_n_est_pas_une_couleur():
    assert COULEUR.findall("&#9888; color:#94a3b8") == ["#94a3b8"]


BIBLIOTHEQUES = re.compile(r"\.min\.js$|redoc|swagger|hub-compiled|babel|react|tailwind|vega|cytoscape|vis-network|lucide")
JETONS = {"nokido.css", "laforge-tokens.css"}       # definitions des jetons : legitimement en #hex
# Cliquet : le total ne peut que DESCENDRE. Mesure du 1/11 apres migration du lanceur ; abaisser a chaque page migree.
PLAFOND = 286   # 1/11 : 322 -> 286 (launcher_html.py 36 -> 0) ; pires : swarm.html 32, rbac_views.py 31


def _pages():
    for p in sorted(WEB.rglob("*")):
        if (p.is_file() and p.suffix in (".html", ".py", ".css", ".js") and not BIBLIOTHEQUES.search(p.name)
                and p.name not in JETONS and "laforge-ds" not in p.parts):
            yield p


def test_cliquet_couleurs_en_dur_du_web_hub():
    par = {p.relative_to(WEB).as_posix(): len(couleurs(p)) for p in _pages()}
    total = sum(par.values())
    pires = sorted(((n, f) for f, n in par.items() if n), reverse=True)[:8]
    assert total <= PLAFOND, "%d couleurs en dur (plafond %d) ; pires : %s" % (total, PLAFOND, pires)


def test_le_lanceur_n_emploie_que_des_jetons():
    assert couleurs(WEB / "launcher_html.py") == []
    assert '/static/nokido.css' in (WEB / "launcher_html.py").read_text(encoding="utf-8")
