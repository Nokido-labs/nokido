#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_docker_agent.py - broker d'actions Docker GOUVERNE : pont hub <-> docker.

Probleme resolu : le pipe Docker Windows (npipe docker_engine) n'est accessible
qu'aux membres du groupe `docker-users`. Les comptes service Nokido (sandbox,
LaForgeTrusted) n'y sont PAS -> tout `docker ...` lance par le hub/agents =
"permission denied". L'humain (token complet, docker-users) passe, pas le hub.

Solution (l'agent docker) :
  1. ENABLING (une fois, admin) : `net localgroup docker-users LaForgeTrusted /add`
     -> LaForgeTrusted gagne l'acces pipe au prochain logon (trusted_script
     refait un LogonUser a chaque appel -> pris en compte direct).
  2. Ce module tourne en contexte LaForgeTrusted (via spawn_as_trusted /
     trusted_script) = le SEUL a parler a docker. Tout agent -> hub verbe
     `docker_action` -> handler valide DockerPolicy -> spawn trusted -> ici.

Securite (meme template que ConsolePolicy/console_exec, defense en profondeur) :
DockerPolicy.decide() = default-DENY. La validation tourne 2x (handler hub +
ce process trusted). Audit JSONL. Reutilise forge_searxng_keeper /
forge_docker_keeper pour les actions haut-niveau (ensure_*).

CLI (appele par le handler hub en trusted) :
  LAFORGE_PYTHON app/forge_docker_agent.py --argv '["ps","-a"]'
  -> imprime un JSON {ok, decision, reason, rc, stdout}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "sandbox" / "docker_agent_audit.jsonl"
WANT_FLAG = ROOT / "sandbox" / "docker.wanted"  # flag on-demand lu par forge_docker_keeper

# ── Politique (default-DENY) ────────────────────────────────────────────────
# 1. Lecture seule : toujours autorise (aucune mutation).
_RO_VERBS = {
    "ps", "images", "inspect", "logs", "stats", "version", "info",
    "port", "top", "events", "df", "history",
}
# 2. Cycle de vie : autorise UNIQUEMENT sur conteneurs Nokido-geres (prefixe).
_LIFECYCLE_VERBS = {"start", "stop", "restart", "rm", "pause", "unpause", "kill"}
_CONTAINER_PREFIXES = (
    "searxng-laforge", "nokido-", "nokido_", "exegol", "ollama",
    "clawhub", "searxng", "lobehub", "deno",
)
# 3. run/create : images Nokido connues + BLOCAGE des evasions hote.
_IMAGE_PREFIXES = (
    "searxng/searxng", "ollama/ollama", "clawhub", "lobehub/lobe-chat",
    "nokrahaboof/exegol", "exegol", "ghcr.io/",
)
# Flags qui cassent l'isolation (evasion vers l'hote) -> jamais en auto.
# Liste NOIRE : refus immediat, avec un motif nomme. Elle reste utile pour DIRE
# pourquoi, mais elle ne suffit pas -- voir `_ALLOW_RUN_FLAGS` juste en dessous.
_BLOCK_RUN_FLAGS = (
    "--privileged", "--pid=host", "--pid", "--ipc=host", "--uts=host",
    "--cap-add", "--device", "--network=host", "--net=host",
    "--security-opt", "--userns=host", "--cgroupns", "--runtime",
    "--device-cgroup-rule", "--volumes-from", "--group-add", "--sysctl",
    "--cap-drop=ALL",  # piege : souvent accompagne d'un --cap-add cible
)

# LISTE BLANCHE DES OPTIONS (audit securite 2026-09-18, finding #1).
#
# Le defaut : les IMAGES etaient en liste blanche, les OPTIONS en liste noire.
# Une option absente des deux tombait donc en ALLOW. Or une liste noire finie
# laisse toute valeur inattendue tomber du cote sain -- c'est le corollaire
# explicite de la constitution semantique du depot, applique ici a l'envers.
#
# Contournement NOMME qui l'a demontre : `_bad_volume` n'examinait que `-v` et
# `--volume`. La forme `--mount type=bind,source=C:\,target=/host` n'etait
# examinee par PERSONNE -- ni par la liste noire, ni par le controle de volume.
#
# POURQUOI `PARK` ET NON `DENY` pour l'inconnu. `decide()` a TROIS etats, et le
# troisieme existe pour ce cas : une option qu'on ne connait pas n'est pas
# forcement hostile, elle est NON INSTRUITE. La refuser casserait un usage
# legitime au premier flag nouveau ; l'accepter est le defaut qu'on corrige.
# `PARK` retient et laisse un humain trancher -- et un garde qui crie a faux se
# fait desarmer, donc on ne crie pas, on retient.
#
# Le contenu vient de l'USAGE REEL mesure ce jour (`forge_docker_transient` :
# `-d --rm --init --name -v -w`), elargi aux options sans effet sur l'isolation
# de l'hote. Toute addition ici est une DECISION, pas un effet de bord.
_ALLOW_RUN_FLAGS = (
    "-d", "--detach", "--rm", "--init", "--name", "-w", "--workdir",
    "-v", "--volume",              # le CONTENU reste juge par `_bad_volume`
    "-e", "--env", "--env-file", "--label", "-l",
    "-p", "--publish", "-i", "--interactive", "-t", "--tty",
    "--entrypoint", "--restart", "--memory", "-m", "--cpus", "--pull",
    "--network", "--net",          # la valeur `host` est refusee par la liste noire
    "--platform", "--hostname", "-h", "--add-host", "--dns",
)
# 4. compose : seulement up/down/ps/logs (pas de build arbitraire ici).
_COMPOSE_VERBS = {"up", "down", "ps", "logs", "stop", "start", "restart"}


# Options qui CONSOMMENT la valeur suivante. Sans cette table, l'image d'un
# `docker run` ne peut pas etre localisee : voir `_image_de_run`.
_FLAGS_A_VALEUR = {
    "--name", "-v", "--volume", "-w", "--workdir", "-e", "--env", "--env-file",
    "-p", "--publish", "-l", "--label", "--entrypoint", "--restart", "--memory",
    "-m", "--cpus", "--network", "--net", "--platform", "--hostname", "-h",
    "--add-host", "--dns", "--mount", "--pull", "--user", "-u",
}


def _racine_de_source(src: str) -> str:
    """Racine normalisee d'une source de montage, LETTRE DE LECTEUR COMPRISE.

    DEFAUT CORRIGE le 2026-09-18, trouve par le premier NR jamais ecrit sur ce
    garde. L'ancienne forme faisait `src.split(":", 1)[0]` : sur `C:\\:/host`
    elle rendait `"c"`, parce que le separateur de `-v` est le MEME caractere que
    celui d'une lettre de lecteur Windows. Aucun controle ne matchait ensuite, et
    la docstring affirmait pourtant detecter `-v C:\\ : /`.

    Consequence : sur cette machine, AUCUN bind-mount de racine de disque n'etait
    vu. Le trou `--mount` que l'audit avait nomme n'en etait que la moitie --
    la cause commune est ici.
    """
    s = src.strip().replace("\\", "/")
    # `C:/...` ou `C:` -> on garde la lettre AVEC son deux-points
    if len(s) >= 2 and s[1] == ":" and s[0].isalpha():
        reste = s[2:]
        # `C:/x:/cible` -> on coupe la CIBLE, pas le lecteur
        racine = ("%s:%s" % (s[0], reste.split(":", 1)[0])) if reste else s[:2]
        return racine.lower().rstrip("/") + ("/" if racine.endswith("/") or len(racine) == 2 else "")
    return s.split(":", 1)[0].strip().lower()


def _image_de_run(rest: list) -> str:
    """L'image d'un `run`, c'est le PREMIER token non-flag apres les options.

    DEFAUT CORRIGE le 2026-09-18. L'ancienne heuristique prenait le DERNIER
    token non-flag ; or `docker run ... <image> sleep infinity` en porte trois,
    et elle rendait `infinity`. L'unique invocation reelle du depot
    (`forge_docker_transient:61`) etait donc retenue par la route gouvernee,
    « image hors whitelist ».

    Un token qui SUIT une option a valeur n'est pas un candidat : c'est sa valeur.
    """
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok.startswith("-"):
            if "=" not in tok and tok in _FLAGS_A_VALEUR:
                i += 2          # l'option ET sa valeur
            else:
                i += 1
            continue
        return tok              # premier non-flag = l'image ; la suite est la commande
    return ""


def _source_de_mount(spec: str) -> str:
    """Extrait la source d'un `--mount type=bind,source=X,target=Y`.

    Ajoute le 2026-09-18 : cette forme n'etait examinee par PERSONNE. Elle est
    strictement equivalente a `-v X:Y` du point de vue de l'evasion, et c'est
    exactement le genre d'angle mort qu'une liste noire produit -- elle protege
    les formes qu'on a pensees, pas la capacite.
    """
    for champ in spec.split(","):
        cle, _, valeur = champ.partition("=")
        if cle.strip().lower() in ("source", "src"):
            return valeur.strip()
    return ""


def _bad_volume(argv: list) -> bool:
    """Detecte un bind-mount dangereux (-v C:\\ : / : //./pipe ..., ou --mount)."""
    for i, tok in enumerate(argv):
        src = ""
        if tok in ("-v", "--volume") and i + 1 < len(argv):
            src = argv[i + 1]
        elif tok.startswith("-v") and len(tok) > 2:
            src = tok[2:]
        elif tok.startswith("--volume="):
            src = tok.split("=", 1)[1]
        elif tok == "--mount" and i + 1 < len(argv):
            src = _source_de_mount(argv[i + 1])
        elif tok.startswith("--mount="):
            src = _source_de_mount(tok.split("=", 1)[1])
        if not src:
            continue
        s = _racine_de_source(src)
        # racine disque (c:/, d:/...), racine unix, pipe docker, dossiers systeme
        if (len(s) == 2 and s[1] == ":") or s in ("c:/", "/", "//./pipe", ""):
            return True
        if s.endswith(":/") or "//./pipe" in s or s in ("/var/run/docker.sock",):
            return True
        if s.startswith(("c:/windows", "c:/users", "/etc", "/var/run")):
            return True
    return False


def decide(argv: list) -> tuple:
    """Retourne (ALLOW|PARK|DENY, reason). default-DENY."""
    if not argv:
        return ("DENY", "argv vide")
    verb = argv[0].lower()
    rest = argv[1:]

    if verb in _RO_VERBS:
        return ("ALLOW", f"read-only:{verb}")

    if verb in _LIFECYCLE_VERBS:
        targets = [a for a in rest if not a.startswith("-")]
        if not targets:
            return ("PARK", f"{verb} sans cible explicite")
        for t in targets:
            if not any(t.lower().startswith(p) for p in _CONTAINER_PREFIXES):
                return ("PARK", f"{verb} sur conteneur non-Nokido: {t}")
        return ("ALLOW", f"lifecycle:{verb} sur {targets}")

    if verb in ("run", "create"):
        if _bad_volume(argv):
            return ("DENY", "bind-mount hote interdit (evasion)")
        for f in rest:
            if not f.startswith("-"):
                continue
            fl = f.split("=", 1)[0]
            if f in _BLOCK_RUN_FLAGS or fl in _BLOCK_RUN_FLAGS:
                return ("DENY", f"flag d'evasion interdit: {f}")
            # Liste BLANCHE : ce qui n'y figure pas est NON INSTRUIT, donc retenu.
            # `-v` colle (`-vC:/x`) et `--env=X` sont reconnus par leur prefixe.
            connu = (fl in _ALLOW_RUN_FLAGS
                     or any(f.startswith(a) for a in _ALLOW_RUN_FLAGS if len(a) == 2))
            if not connu:
                return ("PARK", f"option hors liste blanche, non instruite: {f}")
        image = _image_de_run(rest)
        if not any(image.startswith(p) for p in _IMAGE_PREFIXES):
            return ("PARK", f"image hors whitelist: {image!r}")
        return ("ALLOW", f"run image:{image}")

    if verb == "compose":
        sub = next((a for a in rest if not a.startswith("-")), "")
        if sub not in _COMPOSE_VERBS:
            return ("PARK", f"compose {sub} non autorise (up/down/ps/logs)")
        return ("ALLOW", f"compose:{sub}")

    return ("PARK", f"verbe docker hors politique: {verb}")


def _audit(rec: dict) -> None:
    try:
        AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # muet-ok audit file write failure
        pass


def run_docker(argv: list, timeout: int = 120) -> dict:
    """Valide (DockerPolicy) puis execute `docker <argv>`. A appeler en
    contexte trusted (docker-users). Renvoie {ok, decision, reason, rc, stdout}."""
    decision, reason = decide(argv)
    rec = {"ts": time.time(), "argv": argv, "decision": decision, "reason": reason}
    if decision != "ALLOW":
        _audit(rec)
        return {"ok": False, "decision": decision, "reason": reason, "rc": None, "stdout": ""}
    try:
        p = subprocess.run(["docker", *argv], capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        rec["rc"] = p.returncode
        _audit(rec)
        return {"ok": p.returncode == 0, "decision": "ALLOW", "reason": reason,
                "rc": p.returncode, "stdout": out[:8000]}
    except Exception as e:  # noqa: BLE001
        rec["rc"] = -1
        rec["err"] = f"{type(e).__name__}: {e}"
        _audit(rec)
        return {"ok": False, "decision": "ALLOW", "reason": reason, "rc": -1,
                "stdout": f"EXC {type(e).__name__}: {e}"}


def ensure_daemon() -> dict:
    """Demande le demarrage de Docker au keeper SOUVERAIN (NokidoDockerKeeper,
    service LocalSystem) : pose/rafraichit sandbox/docker.wanted -> le keeper lance
    Docker Desktop EN SESSION USER au prochain tick (il a SeTcbPrivilege/WTS ; nous
    non). On-demand, gouverne, anti-gaspillage RAM. Retour immediat (daemon up ~60-90s).
    Si deja up -> no-op cote keeper."""
    import time as _t

    if daemon_up():
        return {"ok": True, "action": "already_up"}
    try:
        WANT_FLAG.parent.mkdir(parents=True, exist_ok=True)
        WANT_FLAG.write_text(str(_t.time()), encoding="utf-8")
        # CONSTATER l'emission. Mesure 2026-08-02 : `docker.wanted` est le seul flag
        # d'intention qui ait toujours eu un ecrivain — le registre le cite comme « le
        # seul qui marchait » — et pourtant le capteur de couplage le voyait a
        # `emetteurs_connus: 0`. Poser le drapeau et le DECLARER sont deux gestes
        # distincts : sans le second, un emetteur bien vivant reste invisible et son
        # signal passe pour mort.
        try:
            import sys as _s
            _s.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_signal_coupling import emit_signal

            emit_signal(WANT_FLAG.name, emitter="forge_docker_agent.poser_intention")
        except Exception:  # noqa: BLE001 - muet-ok: declarer ne doit pas empecher de poser
            pass
        return {"ok": True, "action": "docker_wanted_posted", "flag": str(WANT_FLAG),
                "note": "keeper lance Docker en ~60-90s ; re-tester ensuite"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"ensure_daemon: {e}"}


def declarer_usage(par: str = "inconnu") -> bool:
    """Prolonge le BAIL de la prothese : quelqu'un s'en sert MAINTENANT.

    Distinct de `ensure_daemon`, qui DEMANDE UN LANCEMENT et sort en `already_up`
    SANS toucher le drapeau quand Docker tourne deja. Ce raccourci laissait le bail
    expirer PENDANT l'usage : passe TTL (900 s) + grace (900 s) sans demande, le
    keeper relachait Docker sous les pieds d'une veille en cours, puis un
    consommateur le redemandait — la dent de scie observee de longue date.

    Le meme drapeau porte donc DEUX sens : « lance-le » et « je m'en sers encore ».
    `ensure_daemon` couvre le premier, cette fonction le second (cf. la lecon
    `llama.wanted`, ou un signal a deux sens produisait les deux pannes opposees).

    N'allume JAMAIS rien : on ne declare un usage qu'apres avoir ete SERVI, donc
    le daemon est deja debout. Retour booleen, jamais d'exception : une declaration
    ratee ne doit pas casser le travail qu'elle accompagne.
    """
    import time as _t

    # UN BAIL NE SURVIT PAS A SA PROTHESE. Mesure 2026-09-05 : cette fonction a
    # prolonge `docker.wanted` a chaque test E2E servi, pendant que le moteur mourait
    # seul quelques minutes plus tard. Le drapeau restant frais, le keeper relancait
    # a chaque mort — la boucle que l'owner a vue. Chacun des deux mecanismes est
    # correct isolement ; ensemble ils s'entretiennent.
    #
    # On exige donc que la prothese soit DEBOUT au moment de prolonger. Ce n'est pas
    # une precaution theorique : declarer un usage sur un moteur mort, c'est demander
    # un LANCEMENT en croyant prolonger un bail — deux actes que tout ce module
    # s'attache a distinguer.
    if not daemon_up():
        return False
    try:
        WANT_FLAG.parent.mkdir(parents=True, exist_ok=True)
        WANT_FLAG.write_text(str(_t.time()), encoding="utf-8")
    except Exception:  # noqa: BLE001 - muet-ok: le bail est un confort, pas un SPOF
        return False
    try:
        import sys as _s
        _s.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_signal_coupling import emit_signal

        emit_signal(WANT_FLAG.name, emitter="forge_docker_agent.declarer_usage:%s" % par)
    except Exception:  # noqa: BLE001 - muet-ok: declarer ne doit pas empecher de poser
        pass
    return True


def release_daemon() -> dict:
    """Retire la DEMANDE Docker (supprime sandbox/docker.wanted) -> le keeper cesse
    de relancer Docker. RESPECTE un arret manuel par l'utilisateur (ne pas le forcer)."""
    try:
        if WANT_FLAG.exists():
            WANT_FLAG.unlink()
        return {"ok": True, "action": "docker_wanted_cleared"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"release_daemon: {e}"}


def daemon_up() -> bool:
    try:
        p = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                           capture_output=True, text=True, errors="replace", timeout=6)
        return p.returncode == 0 and bool(p.stdout.strip())
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--argv", help="JSON list des arguments docker (ex: '[\"ps\",\"-a\"]')")
    ap.add_argument("--argv-b64", dest="argv_b64", help="meme JSON encode base64 (shell-safe, voie hub)")
    ap.add_argument("--check", action="store_true", help="check daemon + identite")
    ap.add_argument("--ensure-daemon", dest="ensure_daemon", action="store_true",
                    help="demande au keeper de lancer Docker (pose docker.wanted)")
    ap.add_argument("--release-daemon", dest="release_daemon", action="store_true",
                    help="retire la demande Docker (respecte un arret manuel)")
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args()

    if a.check:
        import getpass
        print(json.dumps({"daemon_up": daemon_up(), "user": getpass.getuser()}))
        return 0
    if a.ensure_daemon:
        print(json.dumps(ensure_daemon(), ensure_ascii=False))
        return 0
    if a.release_daemon:
        print(json.dumps(release_daemon(), ensure_ascii=False))
        return 0
    raw = a.argv
    if a.argv_b64:
        import base64
        raw = base64.b64decode(a.argv_b64).decode("utf-8")
    if not raw:
        print(json.dumps({"ok": False, "reason": "--argv ou --argv-b64 requis"}))
        return 1
    try:
        argv = json.loads(raw)
        assert isinstance(argv, list)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "reason": f"argv parse: {e}"}))
        return 1
    print(json.dumps(run_docker([str(x) for x in argv], timeout=a.timeout), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
