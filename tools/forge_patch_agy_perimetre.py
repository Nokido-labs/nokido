# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "immunitaire/perimetre-agy"
PATCH app/forge_mcp_security.py (CRITICAL_FILE) : aligner le perimetre
d'ecriture d'ANTIGRAVITY sur le SSoT des identites.

POURQUOI UN SCRIPT
==================
`app/forge_mcp_security.py` est CRITICAL_FILE : `governed_edit` le refuse et
`LAFORGE_ALLOW_CRITICAL_WRITE` vit dans l'environnement du hub, qui ne se
recharge pas a chaud. Voie prevue : script git-tracke lance en `trusted_script`
-- doctrine << privilege = code revu >>. Meme patron que
`tools/forge_patch_muted_paths.py` et `tools/forge_patch_sse_leak.py`.

CE QU'IL CORRIGE
================
DEUX verites coexistaient pour le MEME agent :

  - `config/agent_identities.json` (SSoT) accorde a ANTIGRAVITY :
    app/ tools/ proxy_deno/ src/ tests/ docs/ config/ migrations/ logs/ sandbox/
  - `AGENT_WRITE_PATHS` ci-dessous le confinait a :
    sandbox/ docs/ tests/ logs/ migrations/ config/

C'est la version RESTRICTIVE qu'AGY recitait de lui-meme le 2026-08-14, en se
croyant ring 2 alors que le registre le donne ring 1 depuis longtemps (1 943
appels journalises, TOUS en ring 1). Une divergence de perimetre qui dure finit
par produire ce qu'on a constate le 13/08 : l'agent edite les gardes lui-meme,
hors canal hub, pour se donner ce qu'il croit lui manquer. On aligne donc la
liste sur le SSoT -- decision owner du 2026-08-14 : << AGY en ring 1, et que ca
tienne >>.

Ce patch n'accorde AUCUN privilege nouveau : il fait dire au garde ce que le
SSoT dit deja. `app/` et `tools/` restent couverts par les autres filets
(CRITICAL_FILES, SecretGuard, validation AST, tree_lock).

GARANTIES
=========
Sentinelle d'idempotence, ancre devant apparaitre EXACTEMENT une fois sinon
abandon, fins de ligne preservees, `compile()` avant ecriture, sauvegarde
horodatee, relecture verifiee, dry-run par defaut. Le hub doit etre redemarre
pour recharger le module.

    LAFORGE_PYTHON tools/forge_patch_agy_perimetre.py            # dry-run
    LAFORGE_PYTHON tools/forge_patch_agy_perimetre.py --apply
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "app" / "forge_mcp_security.py"

SENTINELLE = "PERIMETRE_AGY_ALIGNE_SSOT"

ANCRE = '''    "ANTIGRAVITY": [  # Antigravity CLI (agy) — pair de code (= GEMINI) ; hook-less -> gouverné hub-only
        "sandbox/",
        "docs/",
        "tests/",
        "logs/",
        "migrations/",
        "config/",
    ],'''

REMPLACEMENT = '''    # PERIMETRE_AGY_ALIGNE_SSOT (2026-08-14) — cette liste doit rester le miroir
    # de config/agent_identities.json. Deux listes divergentes pour le meme agent,
    # c'est l'agent qui finit par editer les gardes lui-meme (constate le 13/08).
    "ANTIGRAVITY": [  # Antigravity CLI (agy) — pair de code, ring 1 (decision owner)
        "app/",
        "tools/",
        "proxy_deno/",
        "src/",
        "tests/",
        "docs/",
        "config/",
        "migrations/",
        "logs/",
        "sandbox/",
    ],'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="ecrit (defaut : dry-run)")
    args = ap.parse_args()

    brut = CIBLE.read_bytes()
    txt = brut.decode("utf-8")
    crlf = "\r\n" in txt
    if crlf:
        txt = txt.replace("\r\n", "\n")

    if SENTINELLE in txt:
        print(f"[deja applique] sentinelle '{SENTINELLE}' presente -- rien a faire")
        return 0

    n = txt.count(ANCRE)
    if n != 1:
        print(f"[ABANDON] ancre trouvee {n} fois (attendu 1) -- aucune ecriture.")
        return 2
    out = txt.replace(ANCRE, REMPLACEMENT, 1)

    try:
        compile(out, str(CIBLE), "exec")
    except SyntaxError as e:
        print(f"[ABANDON] le resultat ne compile pas : {e}")
        return 3
    print("  [ok] ancre unique, compile() du resultat")

    if not args.apply:
        print(f"\n[dry-run] pret, {len(out) - len(txt):+d} caracteres. "
              f"Relancer avec --apply.")
        return 0

    horodatage = time.strftime("%Y%m%d_%H%M%S")
    sauvegarde = CIBLE.with_suffix(f".py.bak.{horodatage}")
    sauvegarde.write_bytes(brut)
    print(f"  [ok] sauvegarde : {sauvegarde.name}")

    final = out.replace("\n", "\r\n") if crlf else out
    CIBLE.write_bytes(final.encode("utf-8"))

    relu = CIBLE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    if SENTINELLE not in relu or '"proxy_deno/",' not in relu:
        print("[ECHEC] relecture : le remplacement n'est pas sur le disque")
        return 4
    print(f"  [ok] relu : {CIBLE.stat().st_size} octets, perimetre aligne")
    print("\n[applique] Le hub doit etre REDEMARRE pour recharger le module.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
