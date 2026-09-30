#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/nokido_rename_services.py — renommer les services SCM LaForge* -> Nokido*.

Le code pilote 41 noms de services `Nokido*` dont AUCUN n'existe : le SCM ne
connait que des `LaForge*` (mesure du 2026-08-17, 53 sites de pilotage reels).
La decision owner est d'aligner le SCM sur le code, pas l'inverse.

nssm ne sait pas renommer un service. La seule voie officielle est
dump -> recreation sous le nouveau nom -> suppression de l'ancien. Ce script
l'automatise en copiant les parametres un a un via `nssm get` (valeur BRUTE,
sans les echappements cmd que `nssm dump` ajoute pour l'affichage).

Le mot de passe d'un service tournant sous un compte utilisateur vit dans les
secrets LSA, indexes par NOM DE SERVICE : il ne survit NI a un dump, NI a une
copie de registre. Les services dont `ObjectName` n'est pas `LocalSystem` sont
donc EXCLUS par defaut ; les renommer exige de reposer le mot de passe.

Par defaut : PLAN seul, aucune ecriture. `--apply` pour agir.

  python tools/nokido_rename_services.py                  # plan
  python tools/nokido_rename_services.py --apply          # renomme les eligibles
  python tools/nokido_rename_services.py --only NokidoCapture --apply
"""
from __future__ import annotations

import argparse
import getpass
import re
import subprocess
import sys

NSSM = r"C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"

# Services dont le renommage coupe le canal de pilotage lui-meme (le hub tourne
# sous LaForge-Master) : jamais emportes par un passage global.
PROTECTED = {"LaForge-Master"}

# Parametre pose par `install`, donc jamais recopie par un `set`.
SKIP_PARAMS = {"Application"}


def nssm(*args, check=False):
    """Appelle nssm en argv (jamais via un shell) et rend (rc, sortie)."""
    proc = subprocess.run([NSSM] + list(args), capture_output=True, check=False)
    raw = proc.stdout + proc.stderr
    # nssm ecrit tantot en UTF-16LE, tantot en UTF-8, selon la commande. Un
    # sondage "essaie UTF-16 puis UTF-8" est PIEGE : un ASCII de longueur paire
    # se decode SANS ERREUR en UTF-16LE et rend du mojibake ('.\\user' ->
    # '尮慎牡扯'). On tranche donc sur la presence d'octets nuls, seul indice
    # fiable, et jamais sur le fait qu'un decodage "passe".
    if b"\x00" in raw:
        out = raw.decode("utf-16-le", "replace")
    else:
        out = raw.decode("utf-8", "replace")
    out = out.replace("\x00", "").strip()
    if check and proc.returncode != 0:
        raise RuntimeError("nssm %s -> rc=%s : %s" % (" ".join(args), proc.returncode, out))
    return proc.returncode, out


def list_services():
    """Liste les services LaForge* connus du SCM (autorite sur l'EXISTENCE)."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Service | Where-Object { $_.Name -like 'LaForge*' } | ForEach-Object { $_.Name }"],
        capture_output=True, text=True, errors="replace", check=False,
    ).stdout
    return sorted(n.strip() for n in out.splitlines() if n.strip())


def service_exists(name):
    rc, _ = nssm("get", name, "Application")
    return rc == 0


def target_name(old):
    """LaForgeX -> NokidoX ; LaForge-Master -> NokidoMaster."""
    return "Nokido" + re.sub(r"^LaForge-?", "", old)


def dumped_params(name):
    """Parametres REELLEMENT definis, lus dans le dump (qui seul les enumere).

    On ne garde du dump que les NOMS de parametres ; les valeurs sont relues via
    `nssm get`, qui ne pratique pas l'echappement cmd (`^"`) du dump.
    """
    _, out = nssm("dump", name, check=True)
    params = []
    seen = set()
    for line in out.splitlines():
        m = re.search(r"\bset\s+%s\s+(\S+)(?:\s+(\S+))?" % re.escape(name), line)
        if not m:
            continue
        param = m.group(1)
        if param in SKIP_PARAMS:
            continue
        # AppExit se lit et s'ecrit avec une sous-cle (ex: AppExit Default Restart).
        key = (param, m.group(2)) if param == "AppExit" and m.group(2) else (param,)
        if key in seen:
            continue
        seen.add(key)
        params.append(list(key))
    return params


def account_of(name):
    _, out = nssm("get", name, "ObjectName")
    return out or "?"


def state_of(name):
    _, out = nssm("status", name)
    return out or "?"


def snapshot(name):
    """Les champs qui prouvent qu'un service rend bien le meme travail."""
    snap = {}
    for param in ("Application", "AppParameters", "AppDirectory", "ObjectName", "Start"):
        rc, val = nssm("get", name, param)
        if rc == 0:
            snap[param] = val
    return snap


def copy_config(old, new, log, password=""):
    """Recree `new` a l'identique de `old`, parametre par parametre.

    `password` : mot de passe du compte de service, saisi par l'OWNER et jamais
    journalise. Il n'est utilise que pour reposer `ObjectName`, le secret LSA
    d'origine etant indexe par NOM de service et donc perdu a la recreation.
    ⚠️ nssm recoit ce mot de passe en argument : il est visible dans la cmdline
    du process le temps de l'appel (meme limite que `migrate_services_user.ps1`).
    """
    _, application = nssm("get", old, "Application", check=True)
    log("    install %s -> %s" % (new, application))
    nssm("install", new, application, check=True)
    for param in dumped_params(old):
        rc, value = nssm("get", old, *param)
        if rc != 0:
            log("    ! %s illisible (rc=%s) — laisse par defaut" % (" ".join(param), rc))
            continue
        # Une valeur multi-ligne (AppEnvironmentExtra) se pose ligne par ligne.
        values = [v for v in value.splitlines() if v.strip()] or [""]
        # Un compte utilisateur exige son mot de passe, sinon le service est
        # recree sans pouvoir demarrer. LocalSystem n'en demande aucun.
        if param[0] == "ObjectName" and values and values[0].lower() != "localsystem":
            if not password:
                raise RuntimeError(
                    "%s tourne sous %s : mot de passe requis (--user-account)" % (old, values[0])
                )
            nssm("set", new, "ObjectName", values[0], password, check=True)
            log("    set ObjectName = %s (mot de passe repose, non journalise)" % values[0])
            continue
        # DisplayName porte l'ancien nom : le laisser tel quel fait echouer la
        # creation (Windows refuse deux services de meme nom affiche tant que
        # l'ancien existe). Description suit, par coherence.
        if param[0] in ("DisplayName", "Description"):
            values = [v.replace(old, new).replace("LaForge", "Nokido") for v in values]
        # Une dependance doit SUIVRE le renommage de sa cible, sinon elle
        # devient fantome en silence et le service ne demarre plus. Et une
        # dependance qui pointait deja dans le vide (ex: 'laforge_hub', jamais
        # installe) fait echouer nssm : on la signale au lieu de tout perdre.
        if param[0] == "DependOnService":
            resolved = []
            for dep in values:
                cible = dep if service_exists(dep) else target_name(dep)
                if service_exists(cible):
                    resolved.append(cible)
                else:
                    log("    ! dependance FANTOME ignoree : %s (aucun service de ce nom)" % dep)
            values = resolved
            if not values:
                continue
        nssm(*(["set", new] + param + values), check=True)
        # NE JAMAIS afficher la valeur d'un parametre qui peut porter un secret.
        # Vecu le 2026-08-17 : `AppEnvironmentExtra` de NokidoDenoProxy contient
        # un ADMIN_TOKEN, imprime en clair dans la console de l'owner par cette
        # ligne. Le journal doit prouver que le parametre a ete pose, pas en
        # divulguer le contenu.
        sensible = param[0] in ("AppEnvironmentExtra", "ObjectName") or re.search(
            r"(?i)(token|secret|password|passwd|pwd|api[_-]?key|bearer)", values[0]
        )
        apercu = "*** valeur masquee (%d car.) ***" % len(values[0]) if sensible else values[0][:70]
        log("    set %s = %s" % (" ".join(param), apercu))


def verify(old_snapshot, new):
    """Preuve d'EFFET : on relit le nouveau service et on le compare a l'ancien."""
    problems = []
    for param, expected in old_snapshot.items():
        rc, got = nssm("get", new, param)
        if rc != 0:
            problems.append("%s illisible sur %s" % (param, new))
        elif got.strip() != expected.strip():
            problems.append("%s diverge : attendu %r, obtenu %r" % (param, expected, got))
    return problems


def main():
    ap = argparse.ArgumentParser(description="Renomme les services SCM LaForge* en Nokido*.")
    ap.add_argument("--apply", action="store_true", help="execute (defaut : plan seul)")
    ap.add_argument("--only", action="append", default=[],
                    help="restreint a ce(s) service(s), ancien OU nouveau nom")
    ap.add_argument("--include-protected", action="store_true",
                    help="autorise LaForge-Master (coupe le hub : a lancer DETACHE)")
    ap.add_argument("--allow-user-account", action="store_true",
                    help="tente aussi les services sous compte utilisateur (mot de passe PERDU)")
    ap.add_argument("--user-account", action="store_true",
                    help="idem, mais DEMANDE le mot de passe a l'ecran et le repose "
                         "(saisie masquee, jamais journalisee) — a lancer en console admin")
    args = ap.parse_args()

    def log(msg):
        print(msg, flush=True)

    services = list_services()
    if not services:
        log("Aucun service LaForge* : rien a faire (ou SCM illisible depuis ce compte).")
        return 0

    eligibles, exclus = [], []
    for old in services:
        new = target_name(old)
        if args.only and old not in args.only and new not in args.only:
            continue
        account, state = account_of(old), state_of(old)
        if old in PROTECTED and not args.include_protected:
            exclus.append((old, new, "protege (porte le hub) — --include-protected"))
        elif account.lower() != "localsystem" and not (args.allow_user_account or args.user_account):
            exclus.append((old, new, "compte %s : mot de passe non transferable" % account))
        elif service_exists(new):
            exclus.append((old, new, "%s existe deja" % new))
        else:
            eligibles.append((old, new, account, state))

    log("=== PLAN — %s service(s) eligible(s), %s exclu(s) ===" % (len(eligibles), len(exclus)))
    for old, new, account, state in eligibles:
        log("  %-28s -> %-24s [%s, %s]" % (old, new, account, state))
    for old, new, why in exclus:
        log("  EXCLU %-24s -> %-22s : %s" % (old, new, why))

    if not args.apply:
        log("\n(plan seul — relancer avec --apply pour executer)")
        return 0

    password = ""
    besoin_mdp = sorted({a for (_o, _n, a, _s) in eligibles if a.lower() != "localsystem"})
    if besoin_mdp:
        if not args.user_account:
            log("\n⚠️  %s service(s) sous compte %s : leur mot de passe ne survit pas a la"
                % (len(besoin_mdp), ", ".join(besoin_mdp)))
            log("    recreation. Relancer avec --user-account pour le saisir.")
        else:
            log("\nComptes concernes : %s" % ", ".join(besoin_mdp))
            password = getpass.getpass("Mot de passe du compte de service (saisie masquee) : ")
            if not password:
                log("Aucun mot de passe saisi — abandon (les services seraient recrees inutilisables).")
                return 1

    ok, failed = [], []
    for old, new, account, state in eligibles:
        log("\n--- %s -> %s" % (old, new))
        try:
            snap = snapshot(old)
            if state.upper().startswith("SERVICE_RUNNING"):
                log("    arret de %s (il tourne)" % old)
                nssm("stop", old, check=True)
            copy_config(old, new, log, password)
            problems = verify(snap, new)
            if problems:
                log("    ECHEC de verification : %s" % " | ".join(problems))
                log("    -> %s laisse en place, %s retire" % (old, new))
                nssm("remove", new, "confirm")
                failed.append((old, problems))
                continue
            nssm("remove", old, "confirm", check=True)
            log("    OK : %s cree et verifie, %s supprime" % (new, old))
            ok.append((old, new))
        except Exception as exc:  # on continue sur les autres services
            log("    ERREUR : %s" % exc)
            # Une creation interrompue en cours de route laisse un service
            # a moitie configure : on le retire pour que la reprise soit propre.
            if service_exists(new):
                log("    nettoyage du service partiel %s" % new)
                nssm("remove", new, "confirm")
            failed.append((old, [str(exc)]))

    log("\n=== BILAN === %s renomme(s), %s echec(s)" % (len(ok), len(failed)))
    for old, problems in failed:
        log("  ECHEC %s : %s" % (old, " | ".join(problems)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
