"""opencode (sst/opencode) servi en LOCAL et sous MOT DE PASSE pour le lanceur :7400.

Decision owner du 2026-09-25 (choix A) : opencode dans l'interface web, lance a la
demande par le lanceur du portail -- donc au nom de l'owner, puisque le portail
tourne en `runAs = "interactive"` -- et jamais demarre par un simple clic de tuile.

Ce que la mesure du 25/09 a fixe :
- `opencode serve` sert l'interface web ET l'API (dont PUT /auth/{providerID} et
  /config) sur le meme port ;
- SANS `OPENCODE_SERVER_PASSWORD`, le serveur etait lisible depuis le compte
  LaForgeSbxOffline : un compte sandbox aurait pu piloter l'agent de code de l'owner
  et reecrire ses identifiants de fournisseurs. AVEC, il rend 401
  `Basic realm="Secure Area"` et 200 pour l'utilisateur `opencode` + mot de passe ;
- l'interface charge ses ressources en chemins ABSOLUS : un proxy a prefixe sous
  :7400 la casserait, d'ou un lien direct vers 127.0.0.1:4096.

Contrat, ferme par defaut :
- ecoute 127.0.0.1:4096 SEULEMENT ; jamais `--mdns` (exposition au reseau local),
  jamais `--auto` (execution sans approbation) ;
- sans mot de passe, REFUS (rc 2) et on le dit. Il vient du Gestionnaire
  d'identification Windows DE L'OWNER (keyring, service `Nokido`) -- illisible par les
  comptes sandbox --, jamais d'un argument, d'un fichier ni d'une variable heritee ;
- le mot de passe n'est ni affiche ni journalise : il ne va qu'a l'environnement de
  l'enfant ; 20 caracteres minimum (port web, tentatives Basic non bornees) ;
- l'AGENT s'authentifie aupres du hub selon les regles en place : jeton DERIVE
  FORGE_TOKEN_OPENCODE (coffre, via forge_secrets), identite OPENCODE au registre, config
  gouvernee versionnee config/clients/opencode/ (OPENCODE_CONFIG_DIR) qui coupe bash et
  edit natifs. Jamais le jeton maitre -- retire de l'env de l'enfant. Sans jeton ou sans
  config : REFUS ;
- l'arbre cmd -> node -> opencode vit dans un Job Object KILL_ON_JOB_CLOSE : l'arret du
  lanceur termine ce wrapper, et le systeme tue l'arbre entier avec lui. Sans Job
  Object, REFUS (rc 3) : un serveur orphelin continuerait d'ecouter apres « Arreter ».

Definir le mot de passe -- dans une console de l'owner, PAS par le `!` de Claude Code,
dont la sortie entre dans la conversation :
    python tools/nokido_opencode_web.py --definir-mot-de-passe
Controler sans rien demarrer (le mot de passe n'est jamais montre, seulement sa presence) :
    python tools/nokido_opencode_web.py --verifier
Diagnostiquer le serveur EN MARCHE, en lecture seule (projet, sessions, fournisseurs, MCP) --
n'affiche que des identifiants, des compteurs et des etats :
    python tools/nokido_opencode_web.py --diagnostiquer
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOTE = "127.0.0.1"
PORT = 4096
CLE = "OPENCODE_SERVER_PASSWORD"
UTILISATEUR = "opencode"  # nom impose par opencode pour l'authentification Basic
ARGS_INTERDITS = ("--mdns", "--auto")
# 20 et non 12 : le port est un port WEB que les comptes sandbox atteignent en loopback,
# et l'authentification Basic d'opencode ne borne pas les tentatives. Ce mot de passe
# garde un agent qui porte une identite du hub : il doit resister a l'essai en masse.
LONGUEUR_MIN = 20

# Authentification de l'AGENT aupres du hub, selon les regles en place : jeton DERIVE
# apparie a OPENCODE seul (via=token, ring prouve), jamais le maitre FORGE_MCP_TOKEN
# (via=master_token conserve l'agent de l'en-tete : passe-partout d'identite). La config
# gouvernee versionnee l'interpole par {env:FORGE_TOKEN_OPENCODE}.
CLE_JETON = "FORGE_TOKEN_OPENCODE"
CONFIG_DIR = ROOT / "config" / "clients" / "opencode"
JETONS_INTERDITS = ("FORGE_MCP_TOKEN",)

RC_OK = 0
RC_SANS_MOT_DE_PASSE = 2
RC_SANS_JOB = 3
RC_INTROUVABLE = 4
RC_PORT_OCCUPE = 5
RC_SANS_JETON = 6
RC_MOT_DE_PASSE_FAIBLE = 7
RC_SANS_CONFIG = 8

# Le handle du Job Object reste vivant jusqu'a la SORTIE du processus : le liberer
# plus tot (fin de fonction, `del`) tuerait ce wrapper lui-meme -- il est membre du
# job -- et son code de retour serait perdu.
_JOBS_VIVANTS: list = []


def service_wcm() -> str:
    """Le service keyring des secrets Nokido, demande a son proprietaire (forge_secrets)."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.forge_secrets import SERVICE
    return SERVICE


def construire_commande(exe: str) -> list:
    """La seule commande lancee. Aucun argument ne vient de l'exterieur."""
    cmd = [exe, "serve", "--port", str(PORT), "--hostname", HOTE]
    for interdit in ARGS_INTERDITS:
        if interdit in cmd:
            raise ValueError("argument interdit dans la commande opencode : %s" % interdit)
    return cmd


def _dossier_shell(csidl: int) -> Path | None:
    """Dossier special de l'utilisateur COURANT (CSIDL), demande au shell Windows. None hors Windows ou
    si le shell refuse. Source unique des deux dossiers ci-dessous (cliquet clones, 26/09)."""
    if sys.platform != "win32":
        return None
    import ctypes
    tampon = ctypes.create_unicode_buffer(260)
    if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, tampon) != 0:
        return None
    return Path(tampon.value) if tampon.value else None


def dossier_appdata() -> Path | None:
    """%APPDATA% de l'utilisateur COURANT, demande au shell Windows.

    Le lanceur ne transmet qu'une liste blanche de variables d'environnement, ou
    APPDATA ne figure pas ; or c'est la que npm installe `opencode`.
    """
    return _dossier_shell(0x1A)  # CSIDL_APPDATA


def dossier_localappdata() -> Path | None:
    return _dossier_shell(0x1C)  # CSIDL_LOCAL_APPDATA


def trouver_opencode(appdata: Path | None) -> str | None:
    """Chemin de `opencode` : le dossier npm global de l'owner d'abord, puis le PATH."""
    chemins = []
    if appdata is not None:
        chemins.append(str(appdata / "npm"))
    chemins.append(os.environ.get("PATH", ""))
    return shutil.which("opencode", path=os.pathsep.join(c for c in chemins if c))


def lire_mot_de_passe() -> tuple:
    """(valeur, raison). Trois etats : present / absent / ILLISIBLE -- jamais deux."""
    try:
        import keyring
        valeur = keyring.get_password(service_wcm(), CLE)
    except Exception as exc:  # noqa: BLE001 -- illisible n'est pas absent
        return None, "ILLISIBLE : gestionnaire d'identification inaccessible (%s)" % type(exc).__name__
    if not valeur:
        return None, "absent du gestionnaire d'identification (service %s, cle %s)" % (service_wcm(), CLE)
    return valeur, "present"


def lire_jeton_agent() -> tuple:
    """(valeur, raison) du jeton derive OPENCODE, demande a l'autorite unique des secrets."""
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from app.forge_secrets import get_secret
        valeur = get_secret(CLE_JETON)
    except Exception as exc:  # noqa: BLE001 -- illisible n'est pas absent
        return None, "ILLISIBLE : coffre inaccessible (%s)" % type(exc).__name__
    if not valeur:
        return None, ("absent du coffre -- semer : tools/forge_vault_seed_agent_tokens.py "
                      "--generate-missing --agents OPENCODE")
    return valeur, "present"


def definir_mot_de_passe() -> int:
    """Saisie masquee, deux fois, puis rangement dans le WCM de l'utilisateur courant."""
    import getpass
    import keyring
    premier = getpass.getpass("Mot de passe opencode (%d caracteres minimum) : " % LONGUEUR_MIN)
    if len(premier) < LONGUEUR_MIN:
        print("REFUS : moins de %d caracteres." % LONGUEUR_MIN)
        return 1
    if getpass.getpass("Confirmer : ") != premier:
        print("REFUS : les deux saisies different.")
        return 1
    keyring.set_password(service_wcm(), CLE, premier)
    print("Enregistre dans le gestionnaire d'identification (service %s, cle %s, %d caracteres)."
          % (service_wcm(), CLE, len(premier)))
    print("Utilisateur a saisir dans le navigateur : %s" % UTILISATEUR)
    return 0


def port_ecoute(hote: str = HOTE, port: int = PORT) -> bool:
    try:
        with socket.create_connection((hote, port), timeout=0.5):
            return True
    except OSError:
        return False


def armer_job():
    """Place CE processus dans un Job Object KILL_ON_JOB_CLOSE ; ses enfants en heritent.

    Le handle rendu doit rester vivant tant que le serveur tourne : c'est sa fermeture,
    a la mort du wrapper, qui tue l'arbre. Leve si l'armement echoue.
    """
    import win32api
    import win32job
    job = win32job.CreateJobObject(None, "")
    info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
    info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
    win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
    return job


def environnement_enfant(mot_de_passe: str, jeton: str) -> dict:
    env = dict(os.environ)
    for interdit in JETONS_INTERDITS:
        env.pop(interdit, None)
    for nom, dossier in (("APPDATA", dossier_appdata()), ("LOCALAPPDATA", dossier_localappdata())):
        if dossier is not None and nom not in env:
            env[nom] = str(dossier)
    env[CLE] = mot_de_passe
    env[CLE_JETON] = jeton
    env["OPENCODE_CONFIG_DIR"] = str(CONFIG_DIR)
    return env


def verifier() -> int:
    """Ce qui serait lance, sans rien lancer. Ne montre jamais le mot de passe."""
    exe = trouver_opencode(dossier_appdata())
    valeur, raison = lire_mot_de_passe()
    if valeur and len(valeur) < LONGUEUR_MIN:
        raison = "TROP COURT (%d caracteres, minimum %d)" % (len(valeur), LONGUEUR_MIN)
    _jeton, raison_jeton = lire_jeton_agent()
    print("executable : %s" % (exe or "INTROUVABLE (npm i -g opencode-ai)"))
    print("mot de passe : %s" % raison)
    print("jeton agent %s : %s" % (CLE_JETON, raison_jeton))
    print("config gouvernee : %s" % ((CONFIG_DIR / "opencode.jsonc") if (CONFIG_DIR / "opencode.jsonc").exists()
                                     else "ABSENTE"))
    print("port %d deja en ecoute : %s" % (PORT, "OUI" if port_ecoute() else "non"))
    if exe:
        print("commande : %s" % " ".join(construire_commande(exe)))
    pret = exe and raison == "present" and raison_jeton == "present"
    return RC_OK if pret else RC_SANS_MOT_DE_PASSE


# Routes interrogees par --diagnostiquer, dans cet ordre. Leur presence est d'abord lue dans
# la specification OpenAPI du serveur (/doc) : une route absente de CETTE version se dit
# « absente de l'API », elle ne se confond pas avec un echec d'appel.
ROUTES_DIAG = ("/project/current", "/project", "/session", "/config/providers", "/provider", "/mcp")
_MOTIF_PORTEUR = re.compile(r"(Bearer|Basic)\s+\S+", re.I)


def _get_json(chemin: str, entete: str, timeout: float = 5.0, corps_post=None) -> tuple:
    """(code HTTP | None, corps JSON | nom d'erreur). GET par defaut ; POST si corps_post."""
    donnees = None if corps_post is None else json.dumps(corps_post).encode()
    req = urllib.request.Request("http://%s:%d%s" % (HOTE, PORT, chemin), data=donnees,
                                 headers={"Authorization": entete, "Accept": "application/json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rep:
            brut = rep.read().decode("utf-8", "replace")
            try:
                return rep.status, json.loads(brut) if brut.strip() else None
            except ValueError:
                return rep.status, "reponse non JSON (%d octets)" % len(brut)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except Exception as exc:  # noqa: BLE001 -- le type suffit, et ne porte aucun secret
        return None, type(exc).__name__


def _ids(elements) -> list:
    if isinstance(elements, dict):
        return sorted(str(k) for k in elements)
    if isinstance(elements, list):
        return [str(e.get("id") or e.get("name") or "?") if isinstance(e, dict) else str(e)
                for e in elements]
    return []


def resumer(chemin: str, corps) -> str:
    """Resume SANS contenu sensible : identifiants, compteurs, etats. Jamais le corps brut."""
    if isinstance(corps, str):
        return corps
    if corps is None:
        return "corps vide"
    if chemin == "/project/current" and isinstance(corps, dict):
        return "worktree=%s id=%s" % (corps.get("worktree") or corps.get("path") or "?", corps.get("id", "?"))
    if chemin == "/project" and isinstance(corps, list):
        return "%d projet(s) : %s" % (len(corps), ", ".join(
            str(p.get("worktree") or p.get("id")) for p in corps[:5] if isinstance(p, dict)))
    if chemin == "/session" and isinstance(corps, list):
        return "%d session(s)" % len(corps)
    if chemin == "/config/providers" and isinstance(corps, dict):
        fournisseurs = corps.get("providers") or []
        return "fournisseurs=%s ; defaut=%s" % (
            ", ".join("%s(%d modeles)" % (f.get("id", "?"), len(f.get("models") or {}))
                      for f in fournisseurs if isinstance(f, dict)) or "AUCUN",
            json.dumps(corps.get("default") or {}, ensure_ascii=False))
    if chemin == "/provider" and isinstance(corps, dict):
        # `default` couvre TOUT le catalogue (223 fournisseurs mesures le 25/09) : on ne
        # garde que les fournisseurs CONNECTES, et on dit combien on en a ecarte.
        connectes = _ids(corps.get("connected"))
        defauts = corps.get("default") or {}
        gardes = {k: v for k, v in defauts.items() if k in connectes} if isinstance(defauts, dict) else {}
        return "connectes=%s ; defaut=%s (%d defaut(s) de fournisseurs non connectes ecartes) ; catalogue=%d" % (
            connectes or "AUCUN", json.dumps(gardes, ensure_ascii=False),
            (len(defauts) - len(gardes)) if isinstance(defauts, dict) else 0, len(corps.get("all") or []))
    if chemin == "/mcp" and isinstance(corps, dict):
        etats = []
        for nom, etat in corps.items():
            if isinstance(etat, dict):
                detail = _MOTIF_PORTEUR.sub(r"\1 <masque>", str(etat.get("error") or ""))[:160]
                etats.append("%s=%s%s" % (nom, etat.get("status", "?"), (" (%s)" % detail) if detail else ""))
            else:
                etats.append("%s=%s" % (nom, etat))
        return "; ".join(etats) or "aucun serveur MCP"
    return "forme inattendue (%s)" % type(corps).__name__


def code_de_sortie(rc) -> int:
    """Code de retour ramene dans l'intervalle d'un int C signe 32 bits.

    Mesure du 25/09 : a l'arret, opencode sort avec 0xC000013A (STATUS_CONTROL_C_EXIT,
    3 221 225 786) et `os._exit` leve OverflowError. Le motif de 32 bits est conserve :
    Windows relit le meme DWORD.
    """
    try:
        code = int(rc) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 1
    return code - 0x100000000 if code >= 0x80000000 else code


def journaux_opencode() -> list:
    """Dossiers ou opencode ecrit son journal (profil de l'utilisateur COURANT)."""
    maison = Path(os.environ.get("USERPROFILE") or Path.home())
    candidats = [maison / ".local" / "share" / "opencode" / "log"]
    local = dossier_localappdata()
    if local is not None:
        candidats.append(local / "opencode" / "log")
    return candidats


def erreurs_du_journal(max_lignes: int = 12) -> list:
    """Dernieres lignes ERROR/WARN du journal opencode le plus recent, porteurs masques.

    Trois etats : lignes trouvees / journal lu sans erreur / aucun journal trouve (dit
    avec les dossiers cherches -- jamais « pas d'erreur » faute d'avoir su lire).
    """
    fichiers = []
    for dossier in journaux_opencode():
        if dossier.is_dir():
            fichiers += [f for f in dossier.glob("*.log") if f.is_file()]
    if not fichiers:
        return ["journal opencode INTROUVABLE (cherche dans : %s)"
                % ", ".join(str(d) for d in journaux_opencode())]
    recent = max(fichiers, key=lambda f: f.stat().st_mtime)
    try:
        taille = recent.stat().st_size
        with open(recent, "rb") as h:
            h.seek(max(0, taille - 400_000))
            texte = h.read().decode("utf-8", "replace")
    except OSError as exc:
        return ["journal %s ILLISIBLE (%s)" % (recent, type(exc).__name__)]
    tout = texte.splitlines()
    lignes = [l for l in tout if re.search(r"\b(ERROR|WARN)\b", l)]
    garde = [_MOTIF_PORTEUR.sub(r"\1 <masque>", l)[:300] for l in lignes[-max_lignes:]]
    # L'interface a-t-elle SEULEMENT essaye ? Zero requete /session = la page n'appelle pas le
    # serveur (panne cote navigateur) ; des requetes sans session = le serveur les recoit.
    session = [l for l in tout if "/session" in l]
    age = int(time.time() - recent.stat().st_mtime)
    entete = ("journal %s (%s, modifie il y a %d s) : %d ligne(s) ERROR/WARN et %d ligne(s) "
              "citant /session dans les 400 derniers Ko" % (recent.name, recent.parent, age,
                                                           len(lignes), len(session)))
    return ([entete] + garde + ["  /session : " + _MOTIF_PORTEUR.sub(r"\1 <masque>", l)[:240]
                                for l in session[-5:]])


def diagnostiquer(get_json=_get_json) -> int:
    """Interroge le serveur EN MARCHE au nom de l'owner. N'imprime ni mot de passe ni corps brut."""
    mot_de_passe, raison = lire_mot_de_passe()
    if not mot_de_passe:
        print("mot de passe : %s -- diagnostic impossible" % raison)
        return RC_SANS_MOT_DE_PASSE
    if not port_ecoute():
        print("%s:%d n'ecoute pas -- demarrer opencode par le lanceur :7400 d'abord" % (HOTE, PORT))
        return RC_INTROUVABLE
    entete = "Basic " + base64.b64encode(("%s:%s" % (UTILISATEUR, mot_de_passe)).encode()).decode()
    code, spec = get_json("/doc", entete)
    chemins = set((spec or {}).get("paths", {})) if isinstance(spec, dict) else set()
    print("/doc : HTTP %s, %d route(s) declaree(s)" % (code, len(chemins)))
    projets: list = []
    if code == 401:
        print("401 : le mot de passe du gestionnaire ne correspond pas a celui du serveur en marche")
        return RC_SANS_MOT_DE_PASSE
    for chemin in ROUTES_DIAG:
        if chemins and chemin not in chemins:
            print("%-18s absente de l'API de cette version" % chemin)
            continue
        code, corps = get_json(chemin, entete)
        print("%-18s HTTP %s : %s" % (chemin, code, resumer(chemin, corps)))
        if chemin == "/project" and isinstance(corps, list):
            projets = [p.get("worktree") for p in corps if isinstance(p, dict) and p.get("worktree")]
    # /session sans parametre ne compte QUE le projet courant : chaque projet connu est
    # compte a part, sinon « 0 session » masque celles des autres (mesure du 25/09).
    for worktree in projets:
        code, corps = get_json("/session?directory=" + urllib.parse.quote(worktree, safe=""), entete)
        print("  sessions de %-40s HTTP %s : %s" % (worktree, code, resumer("/session", corps)))
    for ligne in erreurs_du_journal():
        print(ligne)
    return RC_OK


def nouvelle_session(get_json=_get_json) -> int:
    """Cree UNE session dans le projet du depot, par l'API : prouve ou refute que le serveur
    sait creer une session, independamment de l'interface."""
    mot_de_passe, raison = lire_mot_de_passe()
    if not mot_de_passe:
        print("mot de passe : %s" % raison)
        return RC_SANS_MOT_DE_PASSE
    entete = "Basic " + base64.b64encode(("%s:%s" % (UTILISATEUR, mot_de_passe)).encode()).decode()
    chemin = "/session?directory=" + urllib.parse.quote(str(ROOT), safe="")
    code, corps = get_json(chemin, entete, corps_post={"title": "preuves d'arrivee OPENCODE"})
    if isinstance(corps, dict) and corps.get("id"):
        print("session creee : id=%s projet=%s (HTTP %s)" % (corps.get("id"), corps.get("directory")
                                                             or corps.get("projectID") or "?", code))
        return RC_OK
    print("creation REFUSEE ou illisible : HTTP %s : %s" % (code, corps if isinstance(corps, str)
                                                           else type(corps).__name__))
    return RC_INTROUVABLE


def servir(popen=subprocess.Popen, armer=armer_job) -> int:
    mot_de_passe, raison = lire_mot_de_passe()
    if not mot_de_passe:
        print("REFUS : opencode ne demarre pas sans mot de passe -- %s. "
              "Le definir dans une console de l'owner : "
              "python tools/nokido_opencode_web.py --definir-mot-de-passe" % raison, flush=True)
        return RC_SANS_MOT_DE_PASSE
    if len(mot_de_passe) < LONGUEUR_MIN:
        print("REFUS : mot de passe trop court (%d caracteres, minimum %d) -- le redefinir : "
              "python tools/nokido_opencode_web.py --definir-mot-de-passe"
              % (len(mot_de_passe), LONGUEUR_MIN), flush=True)
        return RC_MOT_DE_PASSE_FAIBLE
    jeton, raison_jeton = lire_jeton_agent()
    if not jeton:
        print("REFUS : opencode ne demarre pas sans SON jeton du hub (%s) -- %s. "
              "Le jeton maitre n'est jamais un repli." % (CLE_JETON, raison_jeton), flush=True)
        return RC_SANS_JETON
    if not (CONFIG_DIR / "opencode.jsonc").exists():
        print("REFUS : config gouvernee absente (%s) -- sans elle, les outils natifs "
              "d'execution et d'ecriture ne sont pas coupes." % CONFIG_DIR, flush=True)
        return RC_SANS_CONFIG
    exe = trouver_opencode(dossier_appdata())
    if not exe:
        print("REFUS : executable opencode introuvable (dossier npm de l'owner puis PATH).", flush=True)
        return RC_INTROUVABLE
    if port_ecoute():
        print("REFUS : %s:%d ecoute deja -- un autre serveur tient ce port ; "
              "il n'est ni repris ni arrete ici." % (HOTE, PORT), flush=True)
        return RC_PORT_OCCUPE
    try:
        job = armer()
    except Exception as exc:  # noqa: BLE001
        print("REFUS : Job Object non arme (%s) -- l'arret laisserait un serveur orphelin "
              "en ecoute." % type(exc).__name__, flush=True)
        return RC_SANS_JOB
    _JOBS_VIVANTS.append(job)
    cmd = construire_commande(exe)
    enfant = popen(cmd, env=environnement_enfant(mot_de_passe, jeton), stdin=subprocess.DEVNULL,
                   cwd=str(ROOT))
    print("opencode servi sur http://%s:%d/ (authentification Basic, utilisateur %s) pid=%s"
          % (HOTE, PORT, UTILISATEUR, getattr(enfant, "pid", "?")), flush=True)
    return enfant.wait()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--definir-mot-de-passe", action="store_true",
                    help="saisie masquee, rangee dans le gestionnaire d'identification de l'utilisateur courant")
    ap.add_argument("--verifier", action="store_true", help="dit ce qui serait lance, sans rien lancer")
    ap.add_argument("--diagnostiquer", action="store_true",
                    help="interroge le serveur en marche (lecture seule) : projet, sessions, fournisseurs, MCP")
    ap.add_argument("--nouvelle-session", action="store_true",
                    help="cree une session dans le projet du depot, par l'API (prouve la creation)")
    args = ap.parse_args(argv)
    if args.definir_mot_de_passe:
        return definir_mot_de_passe()
    if args.verifier:
        return verifier()
    if args.diagnostiquer:
        return diagnostiquer()
    if args.nouvelle_session:
        return nouvelle_session()
    return servir()


if __name__ == "__main__":
    _rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # os._exit : aucune finalisation qui fermerait le handle du job AVANT que le code
    # de retour soit pose ; le systeme le ferme a la terminaison, et tue alors l'arbre.
    os._exit(code_de_sortie(_rc))
