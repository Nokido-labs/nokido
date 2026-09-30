"""Patch CRITICAL_FILE : le journal d'autorisation distingue MAITRE et DERIVE.

__FORGE_COLOR__ = "immunitaire/tracabilite-des-appelants"

DEFAUT MESURE le 2026-09-02 : le middleware d'observation calcule `via`
lui-meme, a partir de la seule FORME de l'en-tete (`bearer` / `header_agent` /
`anonyme`). Il ne voit donc pas la distinction qui compte :

    credential MAITRE  -> son porteur peut se declarer n'importe quel agent
                          et HERITER de son ring (mesure : porteur du maitre
                          se declarant CLAUDE -> ring 1, via=master_token)
    credential DERIVE  -> un nom non apparie retombe au plancher (ring 4)

Autrement dit, un organe au maitre est un PASSE-PARTOUT, et le journal ne
permettait pas de le voir : `via=bearer` dans les deux cas. Diagnostic mesure a
la main ce jour-la : sur 12 identites qui s'authentifient reellement, QUATRE
portent le maitre (CLAUDE_HOOK, STATE_ENCODER, OPENAI_PROXY, DENOHUBMCP).
Ce patch rend ce diagnostic AUTOMATIQUE et continu.

Le jeton n'est JAMAIS journalise : on compare en temps constant
(`hmac.compare_digest`) et on n'ecrit que le VERDICT.

Usage :
    run action=trusted_script path=tools/forge_patch_authz_via_reel.py
    run action=trusted_script path=tools/forge_patch_authz_via_reel.py script_args="--apply"
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = (ROOT / "tools" / "nokido_hub.py").resolve()

ANCRE = '''                    _via = "bearer" if _auth.lower().startswith("bearer ") else (
                        "header_agent" if request.headers.get("LaForge-Agent-Name")
                        or request.headers.get("X-Agent-Name") else "anonyme")
'''

REMPLACEMENT = '''                    # `via` doit distinguer le MAITRE du credential DERIVE :
                    # le porteur du maitre peut se declarer n'importe quel agent
                    # et heriter de son ring, le derive non. Avec un `via` calcule
                    # sur la seule FORME de l'en-tete, les deux se lisaient
                    # `bearer` et le journal ne montrait pas les passe-partout.
                    # Le jeton n'est jamais ecrit : on compare, on garde le verdict.
                    if _auth.lower().startswith("bearer "):
                        _tok = _auth[7:].strip()
                        try:
                            if HUB_TOKEN and hmac.compare_digest(
                                    _tok.encode(), HUB_TOKEN.encode()):
                                _via = "bearer_maitre"
                            elif any(hmac.compare_digest(_tok.encode(), str(_t).encode())
                                     for _t in _AGENT_TOKENS.values() if _t):
                                _via = "bearer_derive"
                            else:
                                _via = "bearer_inconnu"
                        except Exception:  # muet-ok : comparaison best-effort, la FORME reste juste
                            _via = "bearer"
                        finally:
                            _tok = ""
                    elif (request.headers.get("LaForge-Agent-Name")
                          or request.headers.get("X-Agent-Name")):
                        _via = "header_agent"
                    else:
                        _via = "anonyme"
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="ecrire (defaut : dry-run)")
    a = ap.parse_args()

    if not CIBLE.exists():
        print("ABSENT : %s" % CIBLE)
        return 2
    src = CIBLE.read_text(encoding="utf-8")

    if "bearer_maitre" in src:
        print("DEJA PATCHE. Rien a faire.")
        return 0

    n = src.count(ANCRE)
    if n != 1:
        print("ANCRE TROUVEE %d FOIS (attendu 1) -- refus d'ecrire." % n)
        return 3

    neuf = src.replace(ANCRE, REMPLACEMENT, 1)
    try:
        compile(neuf, str(CIBLE), "exec")
    except SyntaxError as e:
        print("AST INVALIDE apres patch (%s) -- refus d'ecrire." % e)
        return 4

    # Les trois symboles references doivent exister au module, sinon l'erreur
    # n'apparaitrait qu'a la premiere requete, c'est-a-dire en production.
    for nom in ("import hmac", "HUB_TOKEN", "_AGENT_TOKENS"):
        if nom not in neuf:
            print("SYMBOLE MANQUANT : %r -- refus." % nom)
            return 6

    # Le jeton ne doit apparaitre dans AUCUNE ecriture de journal.
    # Le garde a CRIE A FAUX en premiere version : il cherchait `_tok` apres le
    # `finally:` et tombait sur `_tok = ""`, c'est-a-dire sur le nettoyage
    # lui-meme. Un garde qui crie a faux se fait desarmer -- corrige tout de
    # suite. On coupe APRES la ligne de nettoyage, et on verifie qu'aucune
    # autre mention ne subsiste dans la zone patchee.
    apres_nettoyage = REMPLACEMENT.split('_tok = ""', 1)
    if len(apres_nettoyage) != 2:
        print("garde inapplicable : la ligne de nettoyage a disparu -- refus.")
        return 7
    if "_tok" in apres_nettoyage[1]:
        print("ATTENTION : `_tok` reutilise APRES son nettoyage -- refus (fuite possible).")
        return 7
    # et le verdict journalise ne doit jamais etre le jeton
    if "_via = _tok" in REMPLACEMENT or "_tok)" in REMPLACEMENT.split("finally:")[-1]:
        print("ATTENTION : le jeton alimente le journal -- refus.")
        return 7

    print("ancre unique OK | AST OK | symboles presents | delta = +%d octets"
          % (len(neuf) - len(src)))
    if not a.apply:
        print("DRY-RUN : rien ecrit. Relancer avec --apply.")
        return 0

    fd, tmp = tempfile.mkstemp(dir=str(CIBLE.parent), suffix=".patchtmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(neuf)
        os.replace(tmp, str(CIBLE))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:  # muet-ok : nettoyage best-effort, l'erreur reelle est relancee
            pass
        raise

    relu = CIBLE.read_text(encoding="utf-8")
    ok = "bearer_maitre" in relu and len(relu) == len(neuf)
    print("ECRIT | relecture disque : %s" % ("identique" if ok else "DIVERGENTE"))
    print("Effet au PROCHAIN redemarrage du hub.")
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
