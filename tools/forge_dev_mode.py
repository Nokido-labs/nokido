"""forge_dev_mode.py -- arm/disarm the privileged-execution escape hatch.

When armed, the hub may honour `privileged=true` on run/orchestrate for a
recognised interactive agent (CLAUDE / CODEX / GEMINI) -> that call runs as
the real user instead of the sandbox, for Nokido development work.

sudo-semantics: the window is short-lived (30 min), opened only by this
interactive command (mints an HMAC DEV capability token via forge_integrity
-- a prompt-injected agent cannot mint one), and every privileged execution
is audit-logged by the hub.

    LAFORGE_PYTHON tools/forge_dev_mode.py arm        # open a 30-min window
    LAFORGE_PYTHON tools/forge_dev_mode.py disarm     # close it now
    LAFORGE_PYTHON tools/forge_dev_mode.py status

See docs/sandbox_user_plan.md sections 12-13.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TOKEN_FILE = ROOT / "sandbox" / ".dev_mode_token"
TTL_S = 1800  # 30 minutes


def _manager():
    from nokido_agent.app.forge_integrity import IntegrityManager

    return IntegrityManager.from_env()


def _restrict_acl() -> tuple:
    """Restreint le jeton a SYSTEM + Administrateurs. Rend (pose, motif).

    Mesure 2026-09-19 : cette fonction LANCAIT `icacls` sans jamais lire son
    `returncode`, et avalait toute exception. Sa docstring promettait « readable
    only by SYSTEM + Administrators » ; le code ne verifiait pas que l'ACL avait
    mordu. Lance par un compte NON-ADMIN, `icacls /inheritance:r` echoue -- et le
    jeton restait lisible par le compte qui venait de l'ecrire.

    Une protection tentee n'est pas une protection posee. On rend donc un verdict
    que l'appelant DOIT regarder, au lieu d'un `None` qui se lit comme un succes.
    """
    try:
        r = subprocess.run(
            [
                "icacls",
                str(TOKEN_FILE),
                "/inheritance:r",
                # SID BIEN CONNUS, jamais des noms de groupe. Mesure 2026-09-19 :
                # la version precedente nommait « SYSTEM », « Administrateurs » ET
                # « Administrators » -- et `icacls` s'arrete au PREMIER nom qu'il ne
                # sait pas resoudre. Sur un Windows francais, « Administrators »
                # n'existe pas : rc=1332, « le mappage entre les noms de compte et
                # les ID de securite n'a pas ete effectue ». L'ACL echouait donc
                # pour TOUT LE MONDE, admin compris, et l'echec etait avale.
                # `*S-1-5-18` = SYSTEM, `*S-1-5-32-544` = groupe Administrateurs
                # integre : les SID ne dependent ni de la langue ni du renommage.
                "/grant",
                "*S-1-5-18:(F)",
                "/grant",
                "*S-1-5-32-544:(F)",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            errors="replace",
        )
    except Exception as e:  # noqa: BLE001
        return False, "icacls injoignable (%s)" % type(e).__name__
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip().splitlines()
        return False, "icacls rc=%d : %s" % (
            r.returncode, detail[0][:120] if detail else "sans message")
    return True, ""


def _est_admin() -> bool:
    """True si ce process peut gouverner le jeton (le poser ET le reprendre)."""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def _diagnostic_jeton() -> str:
    """'' si la voie est libre, sinon ce qui bloque ET comment en sortir."""
    if not TOKEN_FILE.exists():
        return ""
    try:
        TOKEN_FILE.read_text(encoding="utf-8")
    except PermissionError:
        return (
            "un jeton PROTEGE subsiste et ce compte n'a pas autorite dessus.\n"
            "  Sortie (console ADMINISTRATEUR) :\n"
            "    & \"%s\" \"%s\" disarm" % (sys.executable, __file__)
        )
    except OSError as e:
        return "jeton illisible (%s) -- etat INDETERMINE, ne pas forcer" % type(e).__name__
    return ""


def arm() -> str:
    from nokido_agent.app.forge_integrity import IntegrityRing

    # VERIFIER AVANT D'ECRIRE. Mesure 2026-09-19 : la version precedente ecrivait
    # le jeton PUIS posait l'ACL PUIS refusait si l'ACL n'avait pas mordu -- en
    # laissant derriere elle un fichier que le compte venait de se rendre
    # inaccessible. Resultat : plus d'armement possible (le fichier existe), plus
    # de desarmement possible (l'ACL l'interdit). Un etat SANS ISSUE, cree par le
    # garde lui-meme.
    #
    # REGLE : ne jamais poser un verrou dont on n'a pas d'abord verifie qu'on
    # saurait le reprendre. On teste donc l'autorite AVANT la moindre ecriture,
    # et un blocage existant est signale AVEC sa voie de sortie.
    bloque = _diagnostic_jeton()
    if bloque:
        raise SystemExit("dev-mode REFUSE : " + bloque)
    if not _est_admin():
        raise SystemExit(
            "dev-mode REFUSE : ce process n'est pas ADMINISTRATEUR.\n"
            "  Le jeton doit etre illisible par les comptes sandbox (c'est TOUTE\n"
            "  sa fonction) ; seul un admin peut poser cette ACL et la reprendre.\n"
            "  Rien n'a ete ecrit -- aucun residu a nettoyer.\n"
            "  Armer depuis une console ADMINISTRATEUR."
        )

    mgr = _manager()
    token = mgr.create_manifest("dev-mode", IntegrityRing.DEV, duration_s=TTL_S)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        TOKEN_FILE.write_text(token, encoding="utf-8")
    except PermissionError:
        # Un jeton PROTEGE existe deja : son ACL interdit l'ecriture a ce compte.
        # C'est le garde qui fonctionne, pas une panne -- on le DIT au lieu de
        # laisser remonter une trace Python que personne ne sait interpreter.
        raise SystemExit(
            "dev-mode REFUSE : un jeton protege existe deja et ce compte ne peut "
            "pas l'ecraser.\n"
            "  C'est le comportement voulu : seul un ADMINISTRATEUR gouverne ce "
            "jeton.\n"
            "  Fermer la fenetre depuis une console admin : "
            "forge_dev_mode.py disarm"
        ) from None

    # PAS D'ACL, PAS DE JETON. Le jeton n'a de sens que s'il est illisible par un
    # process sandboxe : c'est TOUTE sa fonction. Si l'ACL n'a pas pu etre posee,
    # on retire ce qu'on vient d'ecrire plutot que de laisser un secret ouvert,
    # et on refuse en le DISANT.
    #
    # Effet de bord VOULU : un appelant non-admin ne peut plus armer, parce qu'il
    # est incapable de poser la protection -- borne par ce que ca FAIT, jamais par
    # un test d'identite qui se contourne. Un admin arme normalement.
    pose, motif = _restrict_acl()
    if not pose:
        try:
            TOKEN_FILE.unlink()
        except OSError:
            pass
        raise SystemExit(
            "dev-mode REFUSE : le jeton ne peut pas etre protege (%s).\n"
            "  Sans ACL SYSTEM+Administrateurs, un process sandboxe le lirait --\n"
            "  et le mode dev perdrait sa seule garantie.\n"
            "  Armer depuis une console ADMINISTRATEUR." % motif
        )
    return token


def disarm() -> None:
    if not TOKEN_FILE.exists():
        return
    try:
        TOKEN_FILE.unlink()
    except PermissionError:
        # Symetrique de `arm` : le jeton est ACL'd SYSTEM+Administrateurs, donc
        # seul un admin le retire. Un compte sandbox qui echoue ici n'a rien
        # casse -- il n'avait simplement pas autorite sur ce jeton.
        raise SystemExit(
            "dev-mode : ce compte n'a pas autorite sur le jeton (ACL "
            "SYSTEM+Administrateurs).\n"
            "  Desarmer depuis une console ADMINISTRATEUR."
        ) from None


def is_armed() -> tuple[bool, int]:
    """(armed, seconds_remaining). The hub calls this before honouring
    `privileged=true`."""
    if not TOKEN_FILE.exists():
        return False, 0
    try:
        from nokido_agent.app.forge_integrity import CapabilityToken

        mgr = _manager()
        token_str = TOKEN_FILE.read_text(encoding="utf-8").strip()
        tok = CapabilityToken.decode(token_str, mgr._secret)
        remaining = int(tok.exp - time.time())
        if remaining <= 0:
            return False, 0
        if tok.ring != tok.ring.DEV:
            return False, 0
        return True, remaining
    except Exception:  # noqa: BLE001  (expired / tampered / bad secret)
        return False, 0


def main() -> int:
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()

    if action == "arm":
        arm()
        ok, rem = is_armed()
        if ok:
            print(
                f"dev-mode ARMED -- privileged execution allowed for "
                f"{rem // 60} min. Disarm: forge_dev_mode.py disarm"
            )
            return 0
        print("ERROR: armed but token does not verify")
        return 1

    if action == "disarm":
        disarm()
        print("dev-mode DISARMED -- run/orchestrate back to sandbox-only")
        return 0

    if action == "status":
        ok, rem = is_armed()
        if ok:
            print(f"dev-mode: ARMED ({rem // 60}m{rem % 60:02d}s remaining)")
        else:
            print("dev-mode: disarmed (sandbox-only)")
        return 0

    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
