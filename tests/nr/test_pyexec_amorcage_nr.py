# -*- coding: utf-8 -*-
"""Non-regression — la cellule WASM ne peut plus mourir en silence.

Mesure du 2026-09-08 : `NokidoPyExec` (:7402) etait muet depuis le 2026-08-01, soit
38 jours. Le service repondait `starting: true` a `ensure`, le port n'ouvrait jamais,
et RIEN n'etait ecrit — ni dans son journal, ni en stderr. Trois defauts empiles :

1. **Racine figee sur l'ANCIEN nom du depot.** `LAFORGE_ROOT` n'est posee NULLE PART
   (ni machine, ni utilisateur, ni `services.toml`), donc le repli
   `"…/Script python IA/LaForge"` s'appliquait TOUJOURS — alors que le depot s'appelle
   `Nokido` depuis. Present a DEUX endroits : la dist Pyodide ET le journal, ce qui a
   rendu la panne doublement invisible (ni port, ni trace).

2. **`URL.pathname` rend un chemin URL-ENCODE.** "Script python IA" y devient
   "Script%20python%20IA", que `Deno.stat` ne trouve pas. Le fichier annoncait deja ce
   piege plus bas sans l'appliquer a la racine.

3. **Le garde `[FATAL-absorbe]` avalait les erreurs d'AMORCAGE.** Il est juste pour la
   CELLULE — absorber une rejection du code etranger permet l'apoptose sans tuer
   l'organe. Il etait faux pour le TISSU : un organe survivait sans pouvoir servir.
   Une panne d'amorcage doit TUER, fort et nommee.

APRES correctif, mesure reelle : cellule montee, `print(6*7)` en 59 ms, stdlib en 4 ms,
Python 3.12.1 — et l'isolation PROUVEE : `os.listdir('C:/')` REFUSE, acces a `:8766`
REFUSE. C'etait la question qu'aucune documentation ne pouvait trancher.

PORTEE DE CE TEST, dite franchement : il lit la SOURCE TypeScript. Il ne peut pas
lancer deno (binaire dans le profil owner, hors ACL des comptes sandbox). Il verrouille
donc les trois invariants la ou ils se lisent — meme patron que le parse-check `.ts`
de `forge_git_gate`. Un test de comportement exigerait deno et sortirait de la suite pure.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "proxy_deno" / "organs" / "pyexec_server.ts"


def _source() -> str:
    return SRC.read_text(encoding="utf-8", errors="replace")


def test_le_fichier_existe():
    assert SRC.is_file(), "organe introuvable : %s" % SRC


def test_plus_aucun_repli_sur_l_ancien_nom_du_depot():
    """`LaForge` en dur = un chemin qui n'existe plus, applique par defaut."""
    src = _source()
    fautifs = [ligne.strip() for ligne in src.splitlines()
               if "Script python IA/LaForge" in ligne and not ligne.strip().startswith("//")]
    assert not fautifs, "repli fige sur l'ancien nom :\n" + "\n".join(fautifs)


def test_la_racine_est_DERIVEE_du_fichier():
    src = _source()
    assert "import.meta.url" in src, "la racine doit se deriver du fichier, pas se deviner"


def test_le_chemin_est_DECODE_avant_usage_disque():
    """Sans decodage, les espaces ressortent en %20 et Deno.stat ne trouve rien."""
    src = _source()
    assert "decodeURIComponent" in src
    i_dec = src.index("decodeURIComponent")
    i_url = src.index("import.meta.url")
    assert abs(i_dec - i_url) < 400, "le decodage doit envelopper le pathname derive"


def test_l_amorcage_est_FATAL_et_non_absorbe():
    """Une rejection avant que Pyodide soit pret vient du TISSU : elle doit tuer."""
    src = _source()
    assert "PRET" in src, "il faut un drapeau distinguant amorcage et service"
    assert re.search(r"if\s*\(\s*!\s*PRET\s*\)", src), \
        "le garde doit tester l'etat d'amorcage AVANT d'absorber"
    assert "Deno.exit(3)" in src, "une panne d'amorcage doit sortir, pas continuer"


def test_l_asset_manquant_se_dit_avec_son_chemin():
    """Un refus qui ne nomme pas le chemin attendu oblige a re-chercher."""
    src = _source()
    assert "dist Pyodide introuvable" in src
    assert "Deno.exit(2)" in src
    assert "LAFORGE_PYODIDE_DIST" in src, "le message doit nommer le levier de reprise"


def test_le_garde_d_apoptose_est_CONSERVE():
    """Le correctif ne doit pas desarmer ce qui protegeait deja : la cellule qui
    part en boucle doit toujours mourir sans emporter l'organe."""
    src = _source()
    assert "preventDefault" in src
    assert "APOPTOSE" in src
