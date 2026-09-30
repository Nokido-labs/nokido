"""NR — la façade Streamlit reste sans importeur, et sa blocklist ne s'étend pas.

Audit du 2026-09-19, classe « injection de commande ». `app/forge_web_service.py`
expose `run_local(command)` et `workflow_run(name)`, qui passent leur chaîne à
`subprocess.run(..., shell=True)`. Le seul garde est `_SSH_BLOCKLIST`, une liste
NOIRE de douze motifs.

Trois faits mesurés :

- le module n'a **aucun importeur** (AST, 1884 fichiers, 0 non parsable) ;
- il **est publié** dans le dist (suivi par git, sans `export-ignore`, non bloqué
  par les 66 motifs du profil public) ;
- son en-tête promet que « toutes les entrées utilisateur sont validées ».

Une liste noire sur un interpréteur de commandes n'est pas une sécurité :
l'espace des formulations est infini, et celle-ci ne couvre ni la lecture de
fichiers ni l'exfiltration. Le module est donc **gelé**, pas supprimé.

⚠️ CE TEST N'AFFIRME PAS QUE LA BLOCKLIST EST SUFFISANTE. Il empêche deux
régressions : qu'on câble ce module sans décision, et qu'on « renforce » la
sécurité en allongeant la liste noire — ce qui donnerait l'illusion d'un progrès.
"""
from __future__ import annotations

import ast
import glob
import os
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture + ast de app/,
#   tools/, web_hub (l.43)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

MODULE = RACINE / "app" / "forge_web_service.py"


def _importeurs() -> tuple[list[str], int, list]:
    trouve, lus, illisibles = [], 0, []
    for sub in ("app", "tools", os.path.join("app", "web_hub")):
        for f in glob.glob(str(RACINE / sub / "*.py")):
            rel = os.path.relpath(f, RACINE)
            if rel.replace("\\", "/").endswith("app/forge_web_service.py"):
                continue
            try:
                arbre = ast.parse(Path(f).read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, OSError) as e:  # muet-ok : compte et rendu
                illisibles.append((rel, type(e).__name__))
                continue
            lus += 1
            for n in ast.walk(arbre):
                if isinstance(n, ast.ImportFrom) and n.module and "forge_web_service" in n.module:
                    trouve.append("%s:%d" % (rel, n.lineno))
                elif isinstance(n, ast.Import):
                    for a in n.names:
                        if "forge_web_service" in a.name:
                            trouve.append("%s:%d" % (rel, n.lineno))
    return trouve, lus, illisibles


def test_la_facade_n_a_toujours_aucun_importeur():
    trouve, lus, illisibles = _importeurs()
    assert lus > 500, "denominateur suspect : %d fichiers lus" % lus
    assert trouve == [], (
        "forge_web_service a acquis un importeur (%s). Ce module expose une "
        "execution shell gardee par une liste NOIRE : le cabler elargit la "
        "surface d'execution et doit etre decide, pas subi. Lus=%d, illisibles=%s"
        % (trouve, lus, illisibles))


def test_la_reponse_n_est_PAS_d_allonger_la_liste_noire():
    """Un garde qu'on « renforce » en allongeant sa blocklist n'a pas progressé.

    Ce test fige le nombre de motifs. S'il augmente, c'est qu'on a traité le
    symptome. La bonne reponse est une liste BLANCHE de commandes nommees, sans
    `shell=True` et avec des arguments passes en LISTE — auquel cas ce test doit
    etre RECRIT, pas ajuste.
    """
    src = MODULE.read_text(encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    motif = None
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign):
            for c in n.targets:
                if isinstance(c, ast.Name) and c.id == "_SSH_BLOCKLIST":
                    for s in ast.walk(n.value):
                        if isinstance(s, ast.Constant) and isinstance(s.value, str) and "|" in s.value:
                            motif = (motif or "") + s.value
    assert motif, "_SSH_BLOCKLIST introuvable : le module a change de forme"
    # ⚠️ Ne compter que les `|` d'ALTERNATION. Un `\|` est un pipe LITTERAL —
    # la regex en contient trois (`curl ... | sh`, `wget ... | sh`,
    # `base64 -d ... | sh`). Un comptage naif donnait 17 au lieu de 14 et
    # faisait echouer ce test sur son propre defaut de lecture.
    import re as _re
    alternatives = len(_re.findall(r"(?<!\\)\|", motif)) + 1
    assert alternatives <= 14, (
        "la liste noire est passee a %d motifs. Allonger une blocklist sur du "
        "shell ne ferme rien : passer a une liste BLANCHE, et recrire ce test."
        % alternatives)


def test_le_module_AVERTIT_de_ce_qu_il_ne_garantit_pas():
    """Son en-tete d'origine promet une validation des entrees. Le contredire
    dans le fichier meme est ce qui protege le prochain lecteur."""
    src = MODULE.read_text(encoding="utf-8", errors="replace")
    assert "liste NOIRE" in src or "liste noire" in src.lower(), (
        "l'avertissement sur la nature du garde a disparu")
    assert "aucun importeur" in src.lower(), (
        "le fait que le module soit orphelin doit rester ecrit : c'est ce qui "
        "distingue une dette d'une faille")


def test_shell_True_n_a_pas_gagne_de_sites_dans_ce_module():
    """Cliquet de surface : le nombre de `shell=True` ne doit pas croitre ici."""
    arbre = ast.parse(MODULE.read_text(encoding="utf-8", errors="replace"))
    n_shell = 0
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    n_shell += 1
    assert n_shell <= 2, (
        "%d appels shell=True dans ce module (2 connus et geles) : toute "
        "addition elargit la surface" % n_shell)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
