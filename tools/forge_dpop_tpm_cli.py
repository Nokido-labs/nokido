"""forge_dpop_tpm_cli.py — ecrit sur stdout une preuve DPoP signee par la cle TPM d'un agent.

__FORGE_COLOR__ = 'immunitaire/preuve de possession : DPoP adossee au TPM pour les appels sensibles'

Chantier d'authentification (2026-09-24), etape TPM. Le superviseur (Deno) ne sait pas
parler au TPM ; il appelle cet outil juste avant un appel d'administration du hub et pose
la sortie dans l'en-tete `DPoP`.

    LAFORGE_PYTHON tools/forge_dpop_tpm_cli.py --agent SUPERVISOR --htm POST \\
        --htu http://127.0.0.1:8766/admin/run_job

- Le credential de l'agent est lu AU COFFRE, jamais en argument (un argument finit dans
  les journaux de processus) ; il sert a l'autorisation avant signature et au champ `ath`.
- Magasin MACHINE force (cles d'agent = cles machine).
- Echec = RIEN sur stdout, motif sur stderr, code non nul : l'appelant n'envoie alors pas
  d'en-tete, et le hub en tire son verdict (observation, ou refus en mode applique).
- `--sortie FICHIER` (2026-09-24) : la preuve va dans FICHIER (cree en EXCLUSIF), le motif
  d'echec dans FICHIER.err. Raison MESUREE : sous Windows, chaque pipe lu par le
  superviseur Deno immobilise un thread de son pool bloquant ; avec ~67 services pipes le
  pool est plein, et un `.output()` sur ce CLI n'aboutissait jamais. Un fichier se lit en
  synchrone apres la fin du process, sans pipe.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parent.parent
if str(_RACINE) not in sys.path:
    sys.path.insert(0, str(_RACINE))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Preuve DPoP adossee au TPM (stdout)")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--htm", required=True, help="methode HTTP de la requete a prouver")
    ap.add_argument("--htu", required=True, help="URI de la requete a prouver")
    ap.add_argument("--sortie", default="", help="fichier de sortie (sinon stdout)")
    a = ap.parse_args(argv)
    os.environ["FORGE_TPM_MACHINE"] = "1"

    def _echec(motif: str) -> int:
        print(motif, file=sys.stderr)
        if a.sortie:
            try:
                Path(a.sortie + ".err").write_text(motif, encoding="utf-8")
            except OSError:  # muet-ok : le motif est deja sur stderr, le code non nul suffit
                pass
        return 1

    try:
        from nokido_agent.app.forge_dpop import creer_preuve_tpm
        from nokido_agent.app.forge_m2m_protocol import _resoudre_agent
        from nokido_agent.app.forge_secrets import get_secret

        canon, _surface = _resoudre_agent(a.agent)
        jeton = get_secret("FORGE_TOKEN_%s" % canon) if canon else ""
        if not jeton:
            return _echec("[dpop_tpm] credential propre de %s absent du coffre" % a.agent)
        preuve = creer_preuve_tpm(canon, a.htm, a.htu, jeton)
        if a.sortie:
            with open(a.sortie, "x", encoding="ascii") as fh:  # exclusif : jamais un fichier d'autrui
                fh.write(preuve)
        else:
            sys.stdout.write(preuve)
        return 0
    except Exception as exc:  # noqa: BLE001 -- aucune preuve partielle en sortie
        return _echec("[dpop_tpm] preuve impossible : %s: %s" % (type(exc).__name__, str(exc)[:120]))


if __name__ == "__main__":
    raise SystemExit(main())
