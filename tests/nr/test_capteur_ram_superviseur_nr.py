"""NR -- le capteur RAM du superviseur ne rend pas 100 % parce qu'un champ vaut 0.

MESURE 2026-09-25 (epreuve « medecin ») : journal du superviseur, lectures « RAM x% > 88% » par heure.
Avant le 2026-09-24 20h : rares (89-96 %, une fois tous les quelques jours). Depuis : 100.0 EXACTEMENT,
chaque minute, ~1200 lectures -- pendant que psutil mesurait 52,0 % (11,4 Go libres). Le correctif
6a1f7a1bc (24/09 19:49, « boucle de vitalite sans promesse pendue ») calculait
`(1 - available / total) * 100` sur `Deno.systemMemoryInfo()` ; sous Windows Deno range la memoire
disponible dans `free` et laisse `available` a 0 (mecanisme probable : le binaire Deno vit dans le
profil owner, illisible par les comptes de mesure -- le correctif tient donc QUEL QUE SOIT le champ).
Effet : la rafale RAM endormait TOUS les non-essentiels 5 min apres leur reveil, depuis 20 heures.

Le capteur est du TypeScript sous Deno, non executable ici : ce NR lit sa STRUCTURE. Le verdict
reel se lit dans le journal du superviseur apres rechargement (les lectures doivent quitter 100.0).
"""
from __future__ import annotations

import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SRC = (RACINE / "proxy_deno" / "core" / "platform.ts").read_text(encoding="utf-8")
WINDOWS = SRC.split("export async function memUsagePct", 1)[1].split('if (OS === "linux")', 1)[0]
CODE = "\n".join(l.split("//", 1)[0] for l in WINDOWS.splitlines())   # sans les commentaires


def test_available_nul_ne_devient_pas_cent_pour_cent():
    assert not re.search(r"return\s*\(\s*1\s*-\s*m\.available\s*/\s*m\.total\s*\)", CODE), \
        "calcul direct sur `available`, qui vaut 0 sous Windows -> 100 % perpetuel"
    assert "m.free" in CODE, "le repli sur `free` (ou Deno range la memoire disponible sous Windows) manque"


def test_une_lecture_saturee_est_suspecte_et_recoupee():
    """Une lecture >= 99,5 % venant de l'API Deno n'est pas crue seule : une sonde unique ne decide pas,
    et c'est elle qui endort le corps entier."""
    assert "99.5" in CODE, "aucun garde sur une lecture saturee de l'API Deno"
    assert "outputSync" in CODE, "le recoupement doit rester SYNCHRONE (pool bloquant sature, 24/09)"
