"""NR — aucun gabarit de prompt `.format()` casse dans app/ et tools/ (cliquet, veille lot_B_09).

DEFAUT DEJA PAYE : `forge_veille_digest._PROMPT` contenait une accolade JSON non echappee ;
`str.format()` lisait « suggestions » comme un champ -> KeyError, avale par un best-effort :
0 suggestion depuis le 22/07, masque seulement par le garde DIGEST_SUSPECT. Haystack elimine
cette classe par construction (variables REQUISES par defaut) ; ici on l'interdit par un cliquet.

Portee DECLAREE (et pas depassee) : constantes chaine de NIVEAU MODULE dont le nom contient
PROMPT / TEMPLATE / GABARIT et utilisees par `NOM.format(`. Les f-strings et gabarits en ligne
ne sont PAS couverts. Un appel `.format(**kw)` ou positionnel n'est pas juge (non decidable
statiquement) — il est COMPTE.

Mesure a l'ecriture (24/09) : 16 gabarits dans la portee, 0 casse. Le controle positif prouve
que l'instrument SAIT voir le cas du 22/07 : un zero sans lui ne prouverait rien.
"""
from __future__ import annotations

import ast
import re
import string
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les app/*.py
#   et tools/*.py (l.51)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
NOM = re.compile(r"(PROMPT|TEMPLATE|GABARIT)", re.I)
IDENT = re.compile(r"^[A-Za-z_]\w*(\.\w+|\[\w+\])*$")


def defauts_du_gabarit(texte: str, appels: list) -> list:
    """Defauts d'un gabarit donne et de ses appels `.format` (noeuds ast.Call)."""
    try:
        champs = [f for _l, f, _s, _c in string.Formatter().parse(texte) if f is not None]
    except ValueError as e:
        return ["illisible par str.format : %s" % e]
    out = []
    mauvais = [f for f in champs if f and not IDENT.match(f.strip())]
    if mauvais:
        out.append("champ(s) non identifiant(s) (accolade litterale non echappee) : %s" % mauvais[:3])
    noms = {re.split(r"[.\[]", f)[0] for f in champs if f and IDENT.match(f.strip())}
    for c in appels:
        if c.args or any(k.arg is None for k in c.keywords):
            continue
        fournis = {k.arg for k in c.keywords}
        if noms - fournis:
            out.append("l.%d : champ(s) non fourni(s) -> KeyError : %s" % (c.lineno, sorted(noms - fournis)))
    return out


def recenser():
    vus, casses = [], []
    for d in ("app", "tools"):
        for p in sorted((RACINE / d).glob("*.py")):
            src = p.read_text(encoding="utf-8", errors="replace")
            if "format(" not in src:
                continue
            arbre = ast.parse(src)
            consts = {n.targets[0].id: n.value.value for n in arbre.body
                      if isinstance(n, ast.Assign) and len(n.targets) == 1
                      and isinstance(n.targets[0], ast.Name) and NOM.search(n.targets[0].id)
                      and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
            appels = {}
            for n in ast.walk(arbre):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr == "format" and isinstance(n.func.value, ast.Name) \
                        and n.func.value.id in consts:
                    appels.setdefault(n.func.value.id, []).append(n)
            for nom, texte in consts.items():
                if nom in appels:
                    cle = "%s/%s::%s" % (d, p.name, nom)
                    vus.append(cle)
                    dd = defauts_du_gabarit(texte, appels[nom])
                    if dd:
                        casses.append((cle, dd))
    return vus, casses


def test_controle_positif_le_cas_du_22_07_est_vu():
    """L'instrument doit SAVOIR voir le defaut paye : sinon son zero ne prouve rien."""
    casse = 'Reponds en JSON : {"suggestions": [...]} pour le lot {lot}'
    appel = ast.parse('P.format(lot=1)').body[0].value
    assert defauts_du_gabarit(casse, [appel]), "le gabarit fautif du 22/07 n'est pas detecte"
    sain = 'Reponds en JSON : {{"suggestions": [...]}} pour le lot {lot}'
    assert defauts_du_gabarit(sain, [appel]) == [], "accolades echappees : faux positif"


def test_controle_positif_champ_non_fourni():
    appel = ast.parse('P.format(a=1)').body[0].value
    assert defauts_du_gabarit("{a} et {b}", [appel])


def test_le_digest_est_dans_la_portee():
    vus, _ = recenser()
    assert "app/forge_veille_digest.py::_PROMPT" in vus, (
        "le gabarit qui a deja casse n'est plus scanne : portee a revoir (%d vus)" % len(vus))


def test_aucun_gabarit_casse():
    vus, casses = recenser()
    assert not casses, "gabarit(s) de prompt casse(s) sur %d : %s" % (len(vus), casses)
