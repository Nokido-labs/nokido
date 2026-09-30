"""nokido_cutover_owner.py — cutover du nom de dossier, partie OWNER.

CE QUE CE SCRIPT FAIT. Il renomme le dossier du depot et rebranche TOUT ce qui vit
HORS du depot et qui le nomme en dur : les services NSSM (registre), les taches
planifiees, et les fichiers de configuration des clients dans le profil owner. Le
depot lui-meme n'a plus besoin de lui : la phase 0 a rendu le code insensible a son
propre nom de dossier (il derive sa racine de __file__).

CE QU'IL NE REFAIT PAS. L'etat RUNTIME (domaines RAG, fichier d'environnement, chemins
durs residuels DANS le depot) est deja couvert par `tools/nokido_cutover_migrate.py` :
ce script l'APPELLE, il ne le reimplemente pas.

LA VERIFICATION DES CHEMINS EST LE COEUR DE L'OUTIL, pas un extra :

  * TROIS ETATS, jamais deux — OK / ABSENT / ILLISIBLE. Un chemin qu'on n'a pas le
    droit de statuer n'est pas un chemin absent, et un inventaire qui confond les deux
    fabrique des faux negatifs indetectables. Le denominateur est toujours imprime.
  * AVANT : toute reference doit exister DEJA. Une reference morte avant le cutover le
    restera apres, et elle serait mise sur le dos du renommage. Elle est nommee.
  * SIMULATION : la cible est calculee et verifiee AVANT d'ecrire quoi que ce soit. Le
    contenu ne bouge pas, seul le nom de la racine change : la cible existe donc si et
    seulement si la source existe. Toute divergence arrete le cutover.
  * APRES : chaque valeur reecrite est RELUE depuis sa source (registre, disque) et
    reverifiee. Et on verifie qu'AUCUNE reference a l'ancien nom ne subsiste dans les
    surfaces couvertes.
  * Un fichier de journal peut ne pas exister encore : on verifie alors son DOSSIER
    PARENT, et l'etat rendu le dit (OK_PARENT), il ne se deguise pas en OK.

SECRETS. `AppEnvironmentExtra` porte des jetons en clair. Ils sont reecrits si besoin
mais JAMAIS imprimes : seul le NOM de la variable apparait dans les rapports.

REVERSIBILITE. `--apply` ecrit d'abord un instantane complet (valeurs de registre, XML
des taches, copie des fichiers de config, ancien nom de dossier) dans
sandbox/cutover_<horodatage>/snapshot.json. `--rollback <dossier>` le rejoue a l'envers.

ORDRE IMPOSE. arret des services -> renommage du dossier -> reecriture des references
-> migration runtime -> verification -> redemarrage. Le renommage echoue si un
processus tient le dossier : l'erreur est rendue telle quelle, avec le service suspect.

CLI :
    LAFORGE_PYTHON tools/nokido_cutover_owner.py                      # preflight (defaut)
    LAFORGE_PYTHON tools/nokido_cutover_owner.py --plan
    LAFORGE_PYTHON tools/nokido_cutover_owner.py --apply --confirm RENOMMER
    LAFORGE_PYTHON tools/nokido_cutover_owner.py --verify
    LAFORGE_PYTHON tools/nokido_cutover_owner.py --rollback sandbox/cutover_<ts>

CONSOLE ELEVEE REQUISE pour --apply et --rollback (ecriture du registre, arret de
services). Le preflight, lui, tourne sans elevation.
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/rename : cutover du nom de dossier, partie owner"

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parent.parent
SUPER = REPO.parent
OLD_NAME = REPO.name
NEW_NAME = "Nokido"
SVC_BASE = r"SYSTEM\CurrentControlSet\Services"
PATH_FIELDS = ("Application", "AppDirectory", "AppParameters", "AppStdout", "AppStderr")
LOGLIKE = (".log", ".err", ".out", ".txt", ".jsonl")

def _home_owner() -> Path:
    """Profil de l'OWNER, pas celui du compte courant.

    Mesure 2026-08-11 : lance depuis un compte de service, `expanduser("~")` rend
    C:\\Users\\Default. Les configs clientes y sont donc introuvables et l'inventaire
    les comptait ABSENTES — un faux negatif qui fait rater 12 chemins en dur. Le depot
    vit dans <profil_owner>/Script python IA/<depot>, donc deux parents au-dessus.
    """
    candidat = SUPER.parent
    # On tranche sur la FORME du chemin, pas sur sa lisibilite : depuis un compte de
    # service, tester l'existence de <profil>/AppData rend False alors que le dossier
    # existe. Se fier a ce test ramenait au profil Default, c'est-a-dire au faux
    # negatif qu'on cherche a supprimer.
    parties = [p.lower() for p in candidat.parts]
    if "users" in parties and parties[-1] not in ("users", "default", "public"):
        return candidat
    return Path(os.path.expanduser("~"))


# Fichiers de configuration CLIENTS, hors depot. Un client absent n'est pas une erreur.
def _documents() -> Path:
    """Dossier Documents REEL : il peut etre redirige (OneDrive), le registre fait foi."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            return Path(os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0]))
    except (OSError, AttributeError):
        return _home_owner() / "Documents"


def _client_configs() -> list[Path]:
    home = _home_owner()
    docs = _documents()
    return [
        # Le profil PowerShell est une CONFIG CLIENTE a part entiere : c'est lui qui
        # definit les commandes du CLI et qui charge les alias depuis le depot, en
        # chemin ABSOLU. Sans lui, le renommage casse la commande sans rien signaler.
        docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        docs / "PowerShell" / "profile.ps1",
        docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
        home / ".claude" / "settings.json",
        home / ".claude" / "settings.local.json",
        home / ".codex" / "config.toml",
        home / ".gemini" / "settings.json",
        home / ".cursor" / "mcp.json",
        home / "AppData" / "Roaming" / "Code" / "User" / "mcp.json",
        home / "AppData" / "Roaming" / "Code" / "User" / "settings.json",
        home / ".vscode" / "mcp.json",
    ]


# ─────────────────────────── verification des chemins ────────────────────────────

def etat(p: Path | str) -> tuple[str, str]:
    """OK / OK_PARENT / ABSENT / ILLISIBLE, avec le motif. Jamais un simple booleen."""
    p = Path(p)
    try:
        if p.exists():
            return "OK", ""
    except (PermissionError, OSError) as e:
        return "ILLISIBLE", f"{type(e).__name__}: {e}"
    # Un journal pas encore cree n'est pas une reference morte : son DOSSIER doit exister.
    if p.suffix.lower() in LOGLIKE:
        try:
            if p.parent.exists():
                return "OK_PARENT", "fichier absent, dossier parent present"
        except (PermissionError, OSError) as e:
            return "ILLISIBLE", f"parent: {type(e).__name__}: {e}"
    # Distinguer « absent » de « hors de mon perimetre de lecture ».
    for anc in p.parents:
        try:
            if anc.exists():
                os.listdir(anc)
                return "ABSENT", f"premier ancetre lisible: {anc}"
        except PermissionError:
            return "ILLISIBLE", f"ancetre non listable: {anc}"
        except OSError:
            continue
    return "ILLISIBLE", "aucun ancetre lisible"


def _extraire_chemins(valeur: str, marqueur: str) -> list[tuple[str, str, str]]:
    """Chemins absolus contenant `marqueur`, rendus avec leur etat : (chemin, etat, motif).

    Trois pieges que la premiere version n'a pas passes, et qui lui faisaient rendre des
    FRAGMENTS (« n.py », « ker.exe ») puis crier a la reference morte :

    1. Le chemin contient des ESPACES (« Script python IA ») : impossible de couper au
       premier blanc. On part donc d'une LETTRE DE LECTEUR et on va jusqu'au bout.
    2. Une valeur est souvent une LIGNE DE COMMANDE : le chemin est suivi d'arguments.
       On retire le dernier mot tant que le chemin n'existe pas — le disque arbitre.
    3. On ARRETE de retirer des que le marqueur disparait, sinon on degringole jusqu'a
       « C:/ », qui existe, et un fragment se ferait passer pour un chemin valide.
    """
    res: list[tuple[str, str, str]] = []
    vus: set[str] = set()
    zones = [m.group(1) for m in re.finditer(r'"([^"]+)"', valeur)]
    zones.append(re.sub(r'"[^"]*"', " ", valeur))     # hors guillemets
    for z in zones:
        for m in re.finditer(r"[A-Za-z]:[\\/]", z):
            cand = z[m.start():].strip().rstrip(",;")
            if marqueur not in cand:
                continue
            retenu = None
            c = cand
            while True:
                st, motif = etat(c)
                if st in ("OK", "OK_PARENT"):
                    retenu = (c, st, motif)
                    break
                if " " not in c:
                    break
                c = c[:c.rfind(" ")].rstrip(" ,;")
                if marqueur not in c:
                    break                              # piege 3
            if retenu is None:
                st, motif = etat(cand)
                retenu = (cand, st, motif)
            if retenu[0] not in vus:
                vus.add(retenu[0])
                res.append(retenu)
    # Une meme valeur peut livrer un candidat mal amorce ET le bon: si le bon est un
    # SUFFIXE du mauvais, le mauvais n'est pas une reference morte, c'est du bruit.
    bons = [p for p, st, _ in res if st in ("OK", "OK_PARENT")]
    return [e for e in res if e[1] in ("OK", "OK_PARENT")
            or not any(e[0].endswith(b) for b in bons)]


def reecrire(valeur: str, ancien: str, nouveau: str) -> str:
    """Remplace le SEGMENT de dossier, jamais une sous-chaine.

    Le nom du dossier est aussi un prefixe de services, de comptes et d'un fichier
    d'environnement : sans la contrainte de segment, le cutover les renommerait aussi.
    """
    motif = re.compile(r"(?<=[\\/])" + re.escape(ancien) + r"(?=[\\/\"'\s]|$)")
    return motif.sub(nouveau, valeur)


# ───────────────────────────────── inventaires ───────────────────────────────────

def inv_services() -> dict:
    if winreg is None:
        return {"erreur": "registre indisponible", "items": [], "enumeres": 0, "illisibles": 0, "sans_params": 0}
    noms, illisibles, sans_params, items = [], 0, 0, []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SVC_BASE) as k:
        i = 0
        while True:
            try:
                noms.append(winreg.EnumKey(k, i)); i += 1
            except OSError:
                break
    for s in noms:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{SVC_BASE}\\{s}\\Parameters") as pk:
                vals, j = {}, 0
                while True:
                    try:
                        n, v, t = winreg.EnumValue(pk, j); vals[n] = (v, t); j += 1
                    except OSError:
                        break
        except FileNotFoundError:
            sans_params += 1; continue
        except (PermissionError, OSError):
            illisibles += 1; continue
        champs, env_noms = {}, []
        for n in PATH_FIELDS:
            v = vals.get(n)
            if v and OLD_NAME in str(v[0]):
                champs[n] = {"valeur": str(v[0]), "type": v[1]}
        env = vals.get("AppEnvironmentExtra")
        if env:
            brut = env[0] if isinstance(env[0], (list, tuple)) else [env[0]]
            env_noms = [str(x).split("=", 1)[0] for x in brut if OLD_NAME in str(x)]
        if champs or env_noms:
            items.append({"service": s, "champs": champs, "env_a_reecrire": env_noms})
    return {"items": items, "enumeres": len(noms), "illisibles": illisibles, "sans_params": sans_params}


def inv_taches() -> dict:
    """Taches dont le NOM ou l'ACTION nomme le dossier. DEUX requetes, et c'est necessaire.

    Mesure 2026-08-11 : la requete VERBEUSE n'a pas rendu une tache desactivee que la
    requete simple rend sans difficulte. Une seule source affichait donc « 0 tache »
    alors qu'il y en avait une. On croise : la liste simple donne les NOMS, la verbeuse
    donne les ACTIONS, et le XML de chaque candidate tranche sur ce qu'elle lance.
    """
    def _q(args: list[str]) -> tuple[str, str]:
        try:
            r = subprocess.run(["schtasks"] + args, capture_output=True, text=True,
                               errors="replace", timeout=120)
        except (OSError, subprocess.SubprocessError) as e:
            return "", f"{type(e).__name__}: {e}"
        return (r.stdout, "") if r.returncode == 0 else ("", f"rc={r.returncode}")

    simple, e1 = _q(["/query", "/fo", "csv"])
    verbeux, e2 = _q(["/query", "/fo", "csv", "/v"])
    if not simple and not verbeux:
        return {"etat": "ILLISIBLE", "items": [], "lignes_vues": 0,
                "motif": f"schtasks muet ({e1} {e2})".strip()}

    noms: set[str] = set()
    for ligne in simple.splitlines():
        champs = [c.strip('"') for c in ligne.split('","')]
        if champs and OLD_NAME in champs[0]:
            noms.add(champs[0].strip('"'))
    for ligne in verbeux.splitlines():
        if OLD_NAME in ligne:
            champs = [c.strip('"') for c in ligne.split('","')]
            nom = next((c for c in champs if c.startswith("\\")), None)
            if nom:
                noms.add(nom)

    items = []
    for nom in sorted(noms):
        xml, err = _q(["/query", "/tn", nom, "/xml"])
        cmd = re.search(r"<Command>(.*?)</Command>", xml, re.S) if xml else None
        arg = re.search(r"<Arguments>(.*?)</Arguments>", xml, re.S) if xml else None
        action = " ".join(x.group(1).strip() for x in (cmd, arg) if x).strip()
        items.append({"tache": nom, "action": action, "action_lisible": bool(xml),
                      "motif": err})
    illisibles = [i["tache"] for i in items if not i["action_lisible"]]
    compte = os.environ.get("USERNAME") or "compte inconnu"
    etat_ = "OK"
    motif = ""
    if illisibles:
        etat_, motif = "PARTIEL", f"action illisible pour {len(illisibles)} tache(s)"
    if not items:
        # Mesure 2026-08-11 : une tache desactivee nommant le depot est visible depuis un
        # compte et INVISIBLE depuis un autre. « Zero tache » n'est donc concluant que si
        # l'on dit QUI a regarde -- sinon c'est un silence qu'on lit comme une absence.
        etat_ = "DOUTEUX"
        motif = (f"aucune tache vue par « {compte} » ; la visibilite depend du compte, "
                 f"relancer en console owner avant de conclure")
    return {"etat": etat_, "items": items, "compte": compte,
            "lignes_vues": len(simple.splitlines()) + len(verbeux.splitlines()),
            "sources": {"simple": bool(simple), "verbeux": bool(verbeux)}, "motif": motif}


def inv_configs() -> dict:
    items, absents, illisibles = [], [], []
    for f in _client_configs():
        try:
            if not f.is_file():
                # « pas de fichier » ne vaut que si on peut LISTER le dossier parent.
                st, motif = etat(f.parent)
                (absents if st == "OK" else illisibles).append(f"{f} ({motif or st})")
                continue
            txt = f.read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError) as e:
            illisibles.append(f"{f} ({type(e).__name__})"); continue
        hits = [(i, l.strip()) for i, l in enumerate(txt.splitlines(), 1) if OLD_NAME in l]
        if hits:
            items.append({"fichier": str(f), "occurrences": len(hits),
                          "lignes": [h[0] for h in hits]})
    return {"items": items, "absents": absents, "illisibles": illisibles,
            "profil_scanne": str(_home_owner())}


# Lignes que des OUTILS reecrivent seuls. Le bloquant « depot non propre » existe pour
# ne pas perdre du travail HUMAIN pendant le renommage ; un artefact regenere n'est pas
# a ce risque, et le laisser bloquer rend la condition insatisfiable — le hook
# POST_COMMIT resalit ces fichiers a chaque livraison. On les ecarte donc, mais LIGNE A
# LIGNE : si une seule ligne modifiee ne correspond a aucun motif connu, le fichier
# redevient humain. Et le rapport NOMME toujours ce qui a ete ecarte.
_MOTIFS_GENERES = {
    "README.md": [re.compile(r"<!--\s*STATS:")],
    # Motifs ancres sur le DEBUT seulement : le generateur du skill coupe ses lignes a
    # un plafond de taille, on trouve donc dans le diff des « - `tools/forge_sweben »
    # sans backtick fermant. Exiger une fin de ligne rendait ces artefacts « humains »
    # et bloquait le cutover sur du bruit machine (mesure 2026-08-11 : 2 lignes sur 140).
    "SKILL.md": [re.compile(r"^## Commit [0-9a-f]{6,}"), re.compile(r"^\*\*"),
                 re.compile(r"^### "), re.compile(r"^- `"), re.compile(r"^\s*$"),
                 re.compile(r"^_Genere ")],
}


def _lignes_modifiees(fichier: str) -> tuple[list[str], str]:
    try:
        r = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(REPO), "diff", "-U0", "--", fichier],
                           capture_output=True, text=True, errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return [], f"{type(e).__name__}: {e}"
    if r.returncode != 0:
        return [], f"git diff rc={r.returncode}"
    out = []
    for l in r.stdout.splitlines():
        if l.startswith(("+++", "---", "@@", "diff ", "index ", "new file", "deleted file")):
            continue
        if l[:1] in "+-":
            # Retirer le retour chariot : le depot est en CRLF, et une ligne finissant
            # par \r ne matche aucun motif ancre sur $ -- mesure 2026-08-11, deux
            # fichiers pourtant regeneres etaient classes « humains » pour cette
            # seule raison.
            out.append(l[1:].rstrip("\r\n\t "))
    return out, ""


def _est_regenere(fichier: str) -> tuple[bool, str]:
    motifs = _MOTIFS_GENERES.get(Path(fichier).name)
    if not motifs:
        return False, "aucun motif declare pour ce fichier"
    lignes, err = _lignes_modifiees(fichier)
    if err:
        return False, f"diff illisible ({err})"      # dans le doute, on le compte humain
    if not lignes:
        return False, "diff vide"
    for l in lignes:
        if not any(m.search(l) for m in motifs):
            return False, f"ligne hors motif: {l.strip()[:60]}"
    return True, f"{len(lignes)} ligne(s), toutes au motif genere"


def inv_processus() -> dict:
    """Processus dont l'executable ou le repertoire courant est DANS le depot.

    Le renommage d'un dossier echoue tant qu'un processus le tient (WinError 32). Or
    arreter les services NSSM ne suffit pas : le superviseur lance des enfants qui ne
    sont pas des services, et un job detache peut avoir son repertoire courant ici.

    `psutil` rend souvent des champs VIDES pour les process d'un autre compte (mesure
    connue : 331 sur 339). Ce n'est pas « rien trouve », c'est « pas pu voir » : le
    compte des illisibles est rendu, et il vaut avertissement.
    """
    try:
        import psutil
    except ImportError:
        return {"etat": "ILLISIBLE", "motif": "psutil absent", "items": [], "vus": 0, "illisibles": 0}
    racine = str(REPO).lower()
    items, vus, illisibles = [], 0, 0
    for p in psutil.process_iter(["pid", "name", "exe", "cwd", "cmdline"]):
        vus += 1
        try:
            info = p.info
            exe, cwd = (info.get("exe") or ""), (info.get("cwd") or "")
            if not exe and not cwd:
                illisibles += 1
                continue
            if racine in exe.lower() or racine in cwd.lower():
                # La ligne de commande est ce qui permet de DECIDER : un pid nu ne dit
                # pas si le processus est un daemon a couper ou une console a fermer.
                cl = " ".join(info.get("cmdline") or [])
                items.append({"pid": info.get("pid"), "nom": info.get("name"),
                              "par": "executable" if racine in exe.lower() else "repertoire courant",
                              "cmdline": cl[:160] if cl else ""})
        except Exception:
            illisibles += 1
    return {"etat": "OK", "items": items, "vus": vus, "illisibles": illisibles,
            "motif": "" if not illisibles else f"{illisibles} process illisibles depuis ce compte"}


# ───────────────────────────────── preflight ─────────────────────────────────────

def preflight() -> dict:
    svc, tasks, cfg, proc = inv_services(), inv_taches(), inv_configs(), inv_processus()
    refs, morts, illisibles = 0, [], 0
    for it in svc["items"]:
        for champ, d in it["champs"].items():
            for p, st, motif in _extraire_chemins(d["valeur"], OLD_NAME):
                refs += 1
                if st == "ABSENT":
                    morts.append(f"{it['service']}/{champ}: {p} ({motif})")
                elif st == "ILLISIBLE":
                    illisibles += 1
    cible = SUPER / NEW_NAME
    bloquants = []
    if cible.exists():
        bloquants.append(f"la cible existe deja: {cible}")
    if not (REPO / ".git").exists():
        bloquants.append(f"pas de depot git en {REPO}")
    try:
        g = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(REPO), "status", "--porcelain"],
                           capture_output=True, text=True, errors="replace", timeout=60)
        sale = [l for l in g.stdout.splitlines() if l[:2] not in ("??",)] if g.returncode == 0 else None
        humains, regeneres = [], []
        for ligne in (sale or []):
            f = ligne[3:].strip().strip('"')
            ok, motif = _est_regenere(f)
            (regeneres if ok else humains).append(f"{f} ({motif})")
        if sale is None:
            git_etat = "ILLISIBLE"
        else:
            git_etat = (f"{len(humains)} fichier(s) humains modifies, "
                        f"{len(regeneres)} regenere(s) ecarte(s)")
        if humains:
            bloquants.append(f"depot non propre: {len(humains)} fichier(s) suivis modifies")
        if sale is None:
            # Ne PAS lire un git muet comme un depot propre : c'est la faute qu'on
            # traque partout ailleurs dans cet outil.
            bloquants.append("etat git ILLISIBLE -- relancer depuis un compte qui peut lancer git")
    except (OSError, subprocess.SubprocessError) as e:
        git_etat, humains, regeneres = f"ILLISIBLE ({type(e).__name__})", [], []
        bloquants.append(f"etat git ILLISIBLE ({type(e).__name__}) -- relancer depuis un compte qui peut lancer git")
    gm = SUPER / ".gitmodules"
    gm_txt = gm.read_text(encoding="utf-8", errors="replace") if gm.is_file() else ""
    return {
        "repo": str(REPO), "cible": str(cible), "ancien": OLD_NAME, "nouveau": NEW_NAME,
        "services": svc, "taches": tasks, "configs": cfg, "processus": proc,
        "refs_verifiees": refs, "refs_mortes_AVANT": morts, "refs_illisibles": illisibles,
        "git": git_etat, "git_humains": humains, "git_regeneres": regeneres,
        "gitmodules_declare_ancien": OLD_NAME in gm_txt,
        "eleve": bool(getattr(ctypes.windll.shell32, "IsUserAnAdmin", lambda: 0)()) if os.name == "nt" else False,
        "bloquants": bloquants,
    }


def imprimer_preflight(r: dict) -> None:
    svc, t, c = r["services"], r["taches"], r["configs"]
    print(f"[cutover] {r['ancien']} -> {r['nouveau']}")
    print(f"  depot   : {r['repo']}")
    print(f"  cible   : {r['cible']}")
    print(f"  console elevee : {'oui' if r['eleve'] else 'NON (preflight seulement)'}")
    print(f"  git     : {r['git']} | .gitmodules nomme l'ancien : {r['gitmodules_declare_ancien']}")
    for f in r.get("git_regeneres", []):
        print(f"    ~ ecarte (regenere) : {f}")
    for f in r.get("git_humains", []):
        print(f"    ! humain non commite : {f}")
    print(f"  services: {len(svc['items'])} a reecrire "
          f"(sur {svc['enumeres']} enumeres, {svc['sans_params']} non-NSSM, {svc['illisibles']} ILLISIBLES)")
    for it in svc["items"]:
        env = f" | env: {', '.join(it['env_a_reecrire'])}" if it["env_a_reecrire"] else ""
        print(f"    - {it['service']}: {', '.join(sorted(it['champs']))}{env}")
    if t.get("etat") == "OK":
        print(f"  taches  : {len(t['items'])} concernee(s) sur {t['lignes_vues']} lignes")
        for it in t["items"]:
            print(f"    - {it['tache']}")
    else:
        print(f"  taches  : ILLISIBLE ({t.get('motif')}) — a relancer en console owner")
    print(f"  configs : {len(c['items'])} fichier(s) client concerne(s), "
          f"{len(c['absents'])} absent(s), {len(c['illisibles'])} illisible(s)")
    for it in c["items"]:
        print(f"    - {it['fichier']}: {it['occurrences']} occurrence(s) lignes {it['lignes']}")
    p = r.get("processus", {})
    print(f"  processus tenant le dossier : {len(p.get('items', []))} "
          f"(sur {p.get('vus', '?')} vus, {p.get('illisibles', '?')} illisibles)")
    for it in p.get("items", [])[:14]:
        detail = it.get("cmdline") or "cmdline illisible"
        print(f"    - pid {it['pid']} {it['nom']} ({it['par']}) :: {detail}")
    print(f"  chemins verifies AVANT : {r['refs_verifiees']} | illisibles : {r['refs_illisibles']}")
    if r["refs_mortes_AVANT"]:
        print(f"  ! {len(r['refs_mortes_AVANT'])} reference(s) DEJA morte(s) avant le cutover "
              f"(le renommage ne les repare pas, elles seraient mises sur son dos) :")
        for m in r["refs_mortes_AVANT"]:
            print(f"      {m}")
    print("  " + ("BLOQUANTS: " + " | ".join(r["bloquants"]) if r["bloquants"] else "aucun bloquant"))


# ─────────────────────────────── plan / simulation ───────────────────────────────

def plan(r: dict) -> list[dict]:
    """Chaque reecriture prevue, avec l'etat de la cible SIMULEE (contenu inchange)."""
    etapes = []
    for it in r["services"]["items"]:
        for champ, d in it["champs"].items():
            avant = d["valeur"]
            apres = reecrire(avant, OLD_NAME, NEW_NAME)
            sim = []
            for p, st, motif in _extraire_chemins(avant, OLD_NAME):
                # la cible existera si et seulement si la source existe : le contenu ne
                # bouge pas, seul le nom de la racine change.
                sim.append({"source": p, "etat_source": st, "motif": motif,
                            "cible": reecrire(p, OLD_NAME, NEW_NAME)})
            etapes.append({"type": "nssm", "cible_nom": it["service"], "champ": champ,
                           "avant": avant, "apres": apres, "chemins": sim})
        for nom in it["env_a_reecrire"]:
            etapes.append({"type": "nssm_env", "cible_nom": it["service"], "champ": nom,
                           "avant": "<valeur masquee>", "apres": "<valeur masquee>", "chemins": []})
    for it in r["taches"].get("items", []):
        etapes.append({"type": "schtask", "cible_nom": it["tache"], "champ": "action",
                       "avant": it["action"], "apres": reecrire(it["action"], OLD_NAME, NEW_NAME),
                       "chemins": []})
    for it in r["configs"]["items"]:
        etapes.append({"type": "config", "cible_nom": it["fichier"], "champ": "texte",
                       "avant": f"{it['occurrences']} occurrence(s)",
                       "apres": f"{it['occurrences']} reecrite(s)", "chemins": []})
    etapes.append({"type": "git", "cible_nom": str(SUPER), "champ": "git mv + .gitmodules",
                   "avant": OLD_NAME, "apres": NEW_NAME, "chemins": []})
    etapes.append({"type": "runtime", "cible_nom": "tools/nokido_cutover_migrate.py",
                   "champ": "--apply", "avant": "etat runtime", "apres": "migre", "chemins": []})
    return etapes


# ───────────────────────────────── application ───────────────────────────────────

def _snapshot(dest: Path, r: dict) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    brut = {"horodatage": time.strftime("%Y-%m-%d_%H%M%S"), "ancien": OLD_NAME, "nouveau": NEW_NAME,
            "repo": str(REPO), "services": {}, "configs": [], "taches": r["taches"].get("items", [])}
    for it in r["services"]["items"]:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{SVC_BASE}\\{it['service']}\\Parameters") as pk:
            vals, j = {}, 0
            while True:
                try:
                    n, v, t = winreg.EnumValue(pk, j)
                    vals[n] = {"valeur": v if not isinstance(v, (list, tuple)) else list(v), "type": t}
                    j += 1
                except OSError:
                    break
        brut["services"][it["service"]] = vals        # valeurs COMPLETES : c'est le rollback
    for it in r["configs"]["items"]:
        src = Path(it["fichier"])
        cp = dest / ("config_" + re.sub(r"[^A-Za-z0-9._-]", "_", src.name))
        shutil.copy2(src, cp)
        brut["configs"].append({"origine": str(src), "copie": str(cp)})
    (dest / "snapshot.json").write_text(json.dumps(brut, indent=2, ensure_ascii=False), encoding="utf-8")
    return dest / "snapshot.json"


def _svc_etat(nom: str) -> str:
    """RUNNING / STOPPED / INCONNU. Sert a ne relancer QUE ce qui tournait."""
    try:
        r = subprocess.run(["sc", "query", nom], capture_output=True, text=True,
                           errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "INCONNU"
    if r.returncode != 0:
        return "INCONNU"
    m = re.search(r"STATE\s+:\s+\d+\s+(\w+)", r.stdout)
    return m.group(1) if m else "INCONNU"


def _tache_active(nom: str) -> bool | None:
    """True/False/None(illisible). Lu dans le XML : insensible a la langue de Windows.

    PIEGE MESURE 2026-08-11 : Windows n'ecrit `<Enabled>` QUE lorsque la tache est
    desactivee. Une tache ACTIVE omet la balise. Lire cette absence comme « illisible »
    laissait tourner les 21 taches actives — exactement celles qu'il fallait neutraliser,
    et le planificateur relançait des processus pendant la fenetre de cutover.
    XML obtenu + pas de balise = ACTIVE.
    """
    try:
        r = subprocess.run(["schtasks", "/query", "/tn", nom, "/xml"], capture_output=True,
                           text=True, errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or "<Task" not in (r.stdout or ""):
        return None                      # la, c'est VRAIMENT illisible
    m = re.search(r"<Enabled>\s*(true|false)\s*</Enabled>", r.stdout)
    return (m.group(1) == "true") if m else True


def _tache_bascule(nom: str, activer: bool) -> bool:
    try:
        r = subprocess.run(["schtasks", "/change", "/tn", nom,
                            "/enable" if activer else "/disable"],
                           capture_output=True, text=True, errors="replace", timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_PREP = REPO / "sandbox" / "cutover_boot_prep.json"


def _svc_demarrage(nom: str) -> str:
    """AUTO_START / DEMAND_START / DISABLED / INCONNU."""
    try:
        r = subprocess.run(["sc", "qc", nom], capture_output=True, text=True,
                           errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "INCONNU"
    m = re.search(r"START_TYPE\s+:\s+\d+\s+(\w+)", r.stdout or "")
    return m.group(1) if m else "INCONNU"


def _svc_set_demarrage(nom: str, mode: str) -> bool:
    """mode: auto | demand | disabled. `sc config` exige l'espace apres `start=`."""
    try:
        r = subprocess.run(["sc", "config", nom, "start=", mode], capture_output=True,
                           text=True, errors="replace", timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def preparer_boot(r: dict) -> int:
    """Empecher tout demarrage automatique, pour renommer AVANT que rien ne tourne.

    POURQUOI CE DETOUR. Mesure du 2026-08-11 : 82 processus tiennent un handle dans le
    depot, et l'immense majorite sur UN SEUL fichier, le journal du superviseur. Celui-ci
    redirige la sortie de tous ses enfants vers ce journal, et chaque enfant HERITE du
    handle — y compris des processus etrangers a nos services (le moteur de modeles, le
    runner d'integration continue). Tant qu'un seul descendant survit, le renommage est
    refuse. Cette course ne se gagne pas a chaud : on renomme quand RIEN n'a demarre.
    """
    services = [it["service"] for it in r["services"]["items"]]
    taches = [it["tache"] for it in r["taches"].get("items", [])]
    etat = {"services": {}, "taches": {}}
    print(f"[prep-boot] {len(services)} service(s) passes en demarrage MANUEL")
    for s in services:
        avant = _svc_demarrage(s)
        etat["services"][s] = avant
        if avant in ("AUTO_START", "DELAYED"):
            ok = _svc_set_demarrage(s, "demand")
            print(("  [ok] " if ok else "  [KO] ") + f"{s} : {avant} -> DEMAND")
        else:
            print(f"  [--] {s} : deja {avant}")
    print(f"[prep-boot] {len(taches)} tache(s) planifiee(s)")
    for t in taches:
        actif = _tache_active(t)
        etat["taches"][t] = actif
        if actif:
            ok = _tache_bascule(t, False) and _tache_active(t) is False
            print(("  [ok] " if ok else "  [KO] ") + f"desactive {t}")
    _PREP.parent.mkdir(parents=True, exist_ok=True)
    _PREP.write_text(json.dumps(etat, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[prep-boot] etat d'origine consigne : {_PREP}")
    print("[prep-boot] REDEMARRER la machine, puis lancer --apply en console elevee.")
    print("[prep-boot] Le cutover restaurera lui-meme les types de demarrage et les taches.")
    return 0


def _svc(action: str, nom: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["sc", action, nom], capture_output=True, text=True,
                           errors="replace", timeout=120)
        return r.returncode, (r.stdout or r.stderr).strip()[:200]
    except (OSError, subprocess.SubprocessError) as e:
        return -1, f"{type(e).__name__}: {e}"


def _tuer(items: list[dict], note) -> None:
    """Couper les processus qui tiennent le dossier. Opt-in explicite seulement."""
    try:
        import psutil
    except ImportError:
        note("kill impossible", False, "psutil absent")
        return
    for it in items:
        try:
            p = psutil.Process(it["pid"])
            p.terminate()
            try:
                p.wait(timeout=5)
            except psutil.TimeoutExpired:
                p.kill()
            note(f"kill pid {it['pid']} {it['nom']}", True, it.get("cmdline", "")[:100])
        except psutil.NoSuchProcess:
            note(f"kill pid {it['pid']} {it['nom']}", True, "deja parti")
        except (psutil.Error, OSError) as e:
            note(f"kill pid {it['pid']} {it['nom']}", False, f"{type(e).__name__}: {e}")


def appliquer(r: dict, snap_dir: Path, tuer: bool = False) -> dict:
    journal = {"snapshot": str(_snapshot(snap_dir, r)), "etapes": []}

    def note(quoi, ok, detail=""):
        journal["etapes"].append({"etape": quoi, "ok": bool(ok), "detail": detail})
        print(("  [ok] " if ok else "  [KO] ") + quoi + ((" -- " + detail) if detail else ""))

    services = [it["service"] for it in r["services"]["items"]]
    taches = [it["tache"] for it in r["taches"].get("items", [])]
    journal["renomme"] = False

    # 0/6 — NEUTRALISER LE PLANIFICATEUR. Sans cela il RELANCE des processus dans le
    # dossier pendant qu'on attend qu'il se libere : mesure du 2026-08-11, on descend de
    # 14 a 4 tenants et on n'atteint jamais zero, caddy revenant par sa tache.
    print(f"[cutover] 0/6 desactivation temporaire de {len(taches)} tache(s) planifiee(s)")
    taches_actives = {}
    for t in taches:
        etat = _tache_active(t)
        taches_actives[t] = etat
        if etat:
            ok_ = _tache_bascule(t, False)
            # Verifier APRES coup : un changement qui rend 0 ne prouve pas l'etat obtenu.
            note(f"desactive {t}", ok_ and _tache_active(t) is False)
        else:
            note(f"laisse {t}", True, "deja desactivee" if etat is False else "etat ILLISIBLE")

    def _restaurer(motif: str) -> None:
        """Remettre le corps comme on l'a trouve : ni plus, ni moins."""
        print(f"[cutover] restauration ({motif})")
        for s_, avant in etats_services.items():
            if avant == "RUNNING":
                rc_, msg_ = _svc("start", s_)
                note(f"start {s_}", rc_ in (0, 1056), msg_)
            else:
                note(f"laisse {s_} a l'arret", True, f"etat avant: {avant}")
        for t_, actif in taches_actives.items():
            if actif:
                note(f"reactive {t_}", _tache_bascule(t_, True))
        # Si un --preparer-boot a precede, c'est LUI qui detient l'etat d'origine des
        # types de demarrage et des taches : le restaurer, puis retirer le fichier pour
        # qu'une execution ulterieure ne rejoue pas un etat perime.
        prep = _PREP if _PREP.is_file() else (SUPER / NEW_NAME / "sandbox" / _PREP.name)
        if prep.is_file():
            try:
                d = json.loads(prep.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                note("restauration prep-boot", False, f"{type(e).__name__}: {e}")
                return
            for s_, avant in d.get("services", {}).items():
                if avant in ("AUTO_START", "DELAYED"):
                    note(f"demarrage {s_} -> auto", _svc_set_demarrage(s_, "auto"))
            for t_, actif in d.get("taches", {}).items():
                if actif:
                    _tache_bascule(t_, True)
            try:
                prep.unlink()
                note("etat prep-boot consomme", True, str(prep))
            except OSError as e:
                note("etat prep-boot non retire", False, f"{type(e).__name__}: {e}")

    print("[cutover] 1/6 arret des services")
    # Releve AVANT : relancer aveuglement les 32 services demarrerait des services
    # volontairement a l'arret. On ne restaure que ce qui tournait.
    etats_services = {s: _svc_etat(s) for s in services}
    print("  etats avant : " + ", ".join(f"{k}={v}" for k, v in etats_services.items()
                                         if v == "RUNNING") or "  aucun service en marche")
    for s in services:
        rc, msg = _svc("stop", s)
        note(f"stop {s}", rc in (0, 1062, 1060), msg)

    print("[cutover] 2/6 renommage du dossier")
    cible = SUPER / NEW_NAME
    # ON TENTE, ON NE PREDIT PAS. La liste des processus est un INDICE ; l'autorite, c'est
    # os.rename. Mesure du 2026-08-11 : apres avoir coupe les cinq tenants, un SIXIEME est
    # apparu — une sonde de sante du hub qui vit une seconde et renait. Une garde qui
    # exige une liste vide ne peut pas gagner cette course, alors que la tentative, elle,
    # reussit des que le verrou tombe. Chaque echec est nomme avec les tenants du moment.
    derniere_erreur, tenants = None, []
    for essai in range(1, 13):
        try:
            os.rename(REPO, cible)
            journal["renomme"] = True
            note(f"rename {OLD_NAME} -> {NEW_NAME}", True, f"reussi a l'essai {essai}")
            break
        except OSError as e:
            derniere_erreur = f"{type(e).__name__}: {e}"
            tenants = inv_processus().get("items", [])
            if tuer and tenants:
                _tuer(tenants, note)
            if essai == 1 or essai % 4 == 0:
                print(f"  ... verrou tenu (essai {essai}/12) : {len(tenants)} processus, "
                      f"{derniere_erreur[:60]}")
            time.sleep(3)
    if not journal["renomme"]:
        for it in tenants:
            note(f"tient le dossier: pid {it['pid']} {it['nom']} ({it['par']})", False,
                 it.get("cmdline") or "cmdline illisible")
        note("renommage ECHOUE", False,
             f"{derniere_erreur} -- AUCUNE reference n'a ete modifiee")
        _restaurer("renommage echoue")
        return journal

    print("[cutover] 3/6 reecriture des references")
    for it in r["services"]["items"]:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{SVC_BASE}\\{it['service']}\\Parameters",
                            0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as pk:
            for champ, d in it["champs"].items():
                winreg.SetValueEx(pk, champ, 0, d["type"], reecrire(d["valeur"], OLD_NAME, NEW_NAME))
            if it["env_a_reecrire"]:
                v, t = winreg.QueryValueEx(pk, "AppEnvironmentExtra")
                items = list(v) if isinstance(v, (list, tuple)) else [v]
                winreg.SetValueEx(pk, "AppEnvironmentExtra", 0, t,
                                  [reecrire(str(x), OLD_NAME, NEW_NAME) for x in items])
        note(f"registre {it['service']} ({len(it['champs'])} champ(s)"
             + (f" + env {', '.join(it['env_a_reecrire'])}" if it["env_a_reecrire"] else "") + ")", True)

    for it in r["configs"]["items"]:
        p = Path(it["fichier"])
        p.write_text(reecrire(p.read_text(encoding="utf-8", errors="replace"), OLD_NAME, NEW_NAME),
                     encoding="utf-8")
        note(f"config {p.name} ({it['occurrences']} occurrence(s))", True)

    for it in r["taches"].get("items", []):
        # schtasks ne modifie pas une action en place : export XML -> reecriture -> reimport.
        base = re.sub(r"[^A-Za-z0-9._-]", "_", it["tache"])
        xml, neuf = snap_dir / (base + ".xml"), snap_dir / (base + "_neuf.xml")
        try:
            e = subprocess.run(["schtasks", "/query", "/tn", it["tache"], "/xml"],
                               capture_output=True, text=True, errors="replace", timeout=60)
            xml.write_text(e.stdout, encoding="utf-16")
            neuf.write_text(reecrire(e.stdout, OLD_NAME, NEW_NAME), encoding="utf-16")
            d = subprocess.run(["schtasks", "/delete", "/tn", it["tache"], "/f"],
                               capture_output=True, text=True, errors="replace", timeout=60)
            c = subprocess.run(["schtasks", "/create", "/tn", it["tache"], "/xml", str(neuf)],
                               capture_output=True, text=True, errors="replace", timeout=60)
            note(f"tache {it['tache']}", c.returncode == 0,
                 (c.stdout or c.stderr).strip()[:160] + f" | delete rc={d.returncode}")
        except (OSError, subprocess.SubprocessError) as ex:
            note(f"tache {it['tache']}", False, f"{type(ex).__name__}: {ex}")

    print("[cutover] 4/6 superrepo : aligner l'index et le pointeur de sous-module")
    for cmd in (["git", "-c", "safe.directory=*", "-C", str(SUPER), "rm", "--cached", "-q", OLD_NAME],
                ["git", "-c", "safe.directory=*", "-C", str(SUPER), "add", NEW_NAME]):
        try:
            g = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120)
            note("git " + " ".join(cmd[-3:]), g.returncode == 0, (g.stdout or g.stderr).strip()[:160])
        except (OSError, subprocess.SubprocessError) as e:
            note("git " + " ".join(cmd[-3:]), False, f"{type(e).__name__}: {e}")
    gm = SUPER / ".gitmodules"
    if gm.is_file():
        txt = gm.read_text(encoding="utf-8", errors="replace")
        txt = (reecrire(txt, OLD_NAME, NEW_NAME)
               .replace(f'[submodule "{OLD_NAME}"]', f'[submodule "{NEW_NAME}"]')
               .replace(f"path = {OLD_NAME}", f"path = {NEW_NAME}"))
        gm.write_text(txt, encoding="utf-8")
        note(".gitmodules reecrit", True)
        try:
            g = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(SUPER), "submodule", "sync"],
                               capture_output=True, text=True, errors="replace", timeout=120)
            note("submodule sync", g.returncode == 0, (g.stdout or g.stderr).strip()[:160])
        except (OSError, subprocess.SubprocessError) as e:
            note("submodule sync", False, f"{type(e).__name__}: {e}")

    print("[cutover] 5/6 etat runtime (outil dedie, non reimplemente ici)")
    try:
        m = subprocess.run([sys.executable, str(cible / "tools" / "nokido_cutover_migrate.py"),
                            "--root", str(cible), "--apply"],
                           capture_output=True, text=True, errors="replace", timeout=900)
        note("nokido_cutover_migrate --apply", m.returncode == 0, (m.stdout or m.stderr).strip()[-300:])
    except (OSError, subprocess.SubprocessError) as e:
        note("nokido_cutover_migrate", False, f"{type(e).__name__}: {e}")

    print("[cutover] 6/6 redemarrage")
    _restaurer("cutover applique")
    return journal


# ─────────────────────── reparation des references mortes ────────────────────────

def _candidat_repare(chemin: str) -> tuple[str | None, str]:
    """Chemin repare et son motif, ou (None, motif) si rien de SUR.

    Deux reparations seulement, toutes deux verifiees sur le disque avant d'etre
    proposees : un guillemet parasite en fin de valeur (il y en a dans le registre), et
    un lanceur dont seul le PREFIXE DE MARQUE a change. Tout le reste est rendu « a
    instruire » : deviner la cible d'un service est exactement ce qu'il ne faut pas
    faire.
    """
    brut = chemin.rstrip(" \"'")
    if brut != chemin and etat(brut)[0] in ("OK", "OK_PARENT"):
        return brut, "guillemet parasite retire"
    p = Path(brut)
    m = re.match(r"(?i)^(laforge|nokido)([_-].+)$", p.name)
    if m:
        for marque in ("nokido", "laforge"):
            cand = p.with_name(marque + m.group(2))
            if str(cand).lower() != str(p).lower() and etat(cand)[0] == "OK":
                return str(cand), f"lanceur renomme: {p.name} -> {cand.name}"
    return None, "aucun equivalent sur le disque -- a instruire (construire, ou retirer le service)"


def reparer(ecrire: bool) -> int:
    svc = inv_services()
    plan_rep, a_instruire = [], []
    for it in svc["items"]:
        for champ, d in it["champs"].items():
            valeur = d["valeur"]
            nouvelle = valeur
            motifs = []
            for chemin, st, _ in _extraire_chemins(valeur, OLD_NAME):
                if st != "ABSENT":
                    continue
                cand, motif = _candidat_repare(chemin)
                if cand:
                    nouvelle = nouvelle.replace(chemin, cand)
                    motifs.append(motif)
                else:
                    a_instruire.append(f"{it['service']}/{champ}: {Path(chemin).name} — {motif}")
            if nouvelle != valeur:
                plan_rep.append({"service": it["service"], "champ": champ, "type": d["type"],
                                 "avant": valeur, "apres": nouvelle, "motifs": motifs})

    print(f"[reparation] {len(plan_rep)} valeur(s) reparable(s), {len(a_instruire)} a instruire")
    for e in plan_rep:
        print(f"  ~ {e['service']}/{e['champ']} : {'; '.join(e['motifs'])}")
        print(f"      {e['avant']}\n   -> {e['apres']}")
    for x in a_instruire:
        print(f"  ! {x}")
    if not ecrire:
        print("[reparation] DRY-RUN — relancer avec --confirm REPARER pour ecrire")
        return 0
    if not plan_rep:
        return 0
    inst = REPO / "sandbox" / ("reparation_" + time.strftime("%Y%m%d_%H%M%S") + ".json")
    inst.parent.mkdir(parents=True, exist_ok=True)
    inst.write_text(json.dumps(plan_rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[reparation] instantane : {inst}")
    for e in plan_rep:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{SVC_BASE}\\{e['service']}\\Parameters",
                            0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as pk:
            winreg.SetValueEx(pk, e["champ"], 0, e["type"], e["apres"])
        relu = None
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{SVC_BASE}\\{e['service']}\\Parameters") as pk:
            relu = str(winreg.QueryValueEx(pk, e["champ"])[0])
        ok = relu == e["apres"]
        # On relit depuis le registre : un SetValueEx qui rend sans erreur ne prouve pas
        # que la valeur ecrite est celle qu'on voulait.
        print(("  [ok] " if ok else "  [KO] ") + f"{e['service']}/{e['champ']}")
    reste = [m for m in preflight()["refs_mortes_AVANT"]]
    print(f"[reparation] references mortes restantes : {len(reste)}")
    for m in reste:
        print("   ! " + m)
    return 0


# ──────────────────────────── verification post-cutover ──────────────────────────

def verifier(nouveau: str | None = None) -> dict:
    """Relit les references DEPUIS leur source et confronte chaque chemin au disque."""
    nouveau = nouveau or NEW_NAME
    if winreg is None:
        return {"erreur": "registre indisponible"}
    res = {"ok": 0, "ok_parent": 0, "absents": [], "illisibles": 0, "restes_ancien_nom": []}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, SVC_BASE) as k:
        noms, i = [], 0
        while True:
            try:
                noms.append(winreg.EnumKey(k, i)); i += 1
            except OSError:
                break
    for s in noms:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{SVC_BASE}\\{s}\\Parameters") as pk:
                vals, j = {}, 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(pk, j); vals[n] = v; j += 1
                    except OSError:
                        break
        except FileNotFoundError:
            continue
        except (PermissionError, OSError):
            res["illisibles"] += 1
            continue
        for champ in PATH_FIELDS:
            v = str(vals.get(champ, ""))
            if OLD_NAME != nouveau and re.search(r"(?<=[\\/])" + re.escape(OLD_NAME) + r"(?=[\\/\"'\s]|$)", v):
                res["restes_ancien_nom"].append(f"{s}/{champ}")
            for p, st, motif in _extraire_chemins(v, nouveau):
                if st == "OK":
                    res["ok"] += 1
                elif st == "OK_PARENT":
                    res["ok_parent"] += 1
                elif st == "ABSENT":
                    res["absents"].append(f"{s}/{champ}: {p} ({motif})")
                else:
                    res["illisibles"] += 1
    for f in _client_configs():
        try:
            if f.is_file() and OLD_NAME != nouveau and OLD_NAME in f.read_text(encoding="utf-8", errors="replace"):
                res["restes_ancien_nom"].append(str(f))
        except (PermissionError, OSError):
            res["illisibles"] += 1
    return res


def rollback(dossier: Path) -> int:
    snap = json.loads((dossier / "snapshot.json").read_text(encoding="utf-8"))
    ancien, nouveau = snap["ancien"], snap["nouveau"]
    print(f"[rollback] {nouveau} -> {ancien} depuis {dossier}")
    for s in snap["services"]:
        _svc("stop", s)
    cible = SUPER / nouveau
    if cible.exists():
        try:
            os.rename(cible, SUPER / ancien)
            print(f"  [ok] dossier restaure : {ancien}")
        except OSError as e:
            print(f"  [KO] rename : {e}")
            return 1
    for s, vals in snap["services"].items():
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{SVC_BASE}\\{s}\\Parameters",
                            0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as pk:
            for n, d in vals.items():
                winreg.SetValueEx(pk, n, 0, d["type"], d["valeur"])
        print(f"  [ok] registre restaure : {s}")
    for c in snap["configs"]:
        shutil.copy2(c["copie"], c["origine"])
        print(f"  [ok] config restauree : {c['origine']}")
    for s in snap["services"]:
        _svc("start", s)
    print("  ! taches planifiees et superrepo : l'XML d'origine est dans le dossier d'instantane ; "
          "le reimport et le git mv inverse se font a la main, verifies et non devines")
    return 0


def _main() -> int:
    ap = argparse.ArgumentParser(description="Cutover du nom de dossier -- partie owner")
    ap.add_argument("--plan", action="store_true", help="montre chaque reecriture et sa cible")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true", help="revalide les chemins apres coup")
    ap.add_argument("--rollback", metavar="DOSSIER")
    ap.add_argument("--reparer", action="store_true",
                    help="repointe les references mortes reparables SANS renommer")
    ap.add_argument("--preparer-boot", action="store_true",
                    help="passe les services en demarrage MANUEL et desactive les taches, "
                         "pour renommer apres un REDEMARRAGE, quand rien ne tient le dossier")
    ap.add_argument("--tuer-tenants", action="store_true",
                    help="avec --apply : coupe les processus qui tiennent encore le dossier "
                         "apres l'arret des services (services et taches sont restaures ensuite)")
    ap.add_argument("--confirm", default="",
                    help="RENOMMER pour --apply, REPARER pour --reparer")
    ap.add_argument("--new-name", default=NEW_NAME)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    globals()["NEW_NAME"] = a.new_name

    if a.rollback:
        return rollback(Path(a.rollback))
    if a.reparer:
        if a.confirm == "REPARER" and not (
                bool(getattr(ctypes.windll.shell32, "IsUserAnAdmin", lambda: 0)()) if os.name == "nt" else False):
            print("[reparation] REFUSE -- console NON elevee (ecriture du registre).")
            return 2
        return reparer(a.confirm == "REPARER")
    if a.verify:
        v = verifier()
        if a.json:
            print(json.dumps(v, indent=2, ensure_ascii=False))
        else:
            print(f"[verify] {v['ok']} chemin(s) OK, {v['ok_parent']} dossier parent seul, "
                  f"{len(v['absents'])} ABSENT(S), {v['illisibles']} illisible(s), "
                  f"{len(v['restes_ancien_nom'])} reference(s) portant encore l'ancien nom")
            for x in v["absents"]:
                print("  ! " + x)
            for x in v["restes_ancien_nom"]:
                print("  ~ reste : " + x)
        return 1 if (v["absents"] or v["restes_ancien_nom"]) else 0

    if a.preparer_boot:
        pre = preflight()
        if not pre["eleve"]:
            print("[prep-boot] REFUSE -- console NON elevee.")
            return 2
        return preparer_boot(pre)

    r = preflight()
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        imprimer_preflight(r)

    if a.plan or a.apply:
        etapes = plan(r)
        print(f"\n[plan] {len(etapes)} etape(s)")
        for e in etapes:
            print(f"  {e['type']:<10} {e['cible_nom']} :: {e['champ']}")
            for c in e["chemins"]:
                marque = "OK " if c["etat_source"] in ("OK", "OK_PARENT") else "!! "
                suffixe = "" if c["etat_source"] == "OK" else f"   [{c['etat_source']} {c['motif']}]"
                print(f"      {marque}{c['source']}\n         -> {c['cible']}{suffixe}")

    if a.apply:
        if r["bloquants"]:
            print("\n[apply] REFUSE -- bloquants non leves :")
            for b in r["bloquants"]:
                print("   ! " + b)
            return 2
        if r["refs_mortes_AVANT"]:
            print("\n[apply] REFUSE -- des references sont DEJA mortes avant le cutover. "
                  "Les corriger ou les retirer d'abord : sinon le renommage portera leur chapeau.")
            return 2
        if not r["eleve"]:
            print("\n[apply] REFUSE -- console NON elevee (ecriture du registre, arret de services).")
            return 2
        if a.confirm != "RENOMMER":
            print("\n[apply] REFUSE -- relancer avec --confirm RENOMMER.")
            return 2
        snap_dir = REPO / "sandbox" / ("cutover_" + time.strftime("%Y%m%d_%H%M%S"))
        j = appliquer(r, snap_dir, tuer=a.tuer_tenants)
        # Le chemin de l'instantane ne suit le renommage QUE s'il a eu lieu. Le substituer
        # sans condition envoyait vers un dossier inexistant en cas de refus.
        inst = str(j["snapshot"])
        if j.get("renomme"):
            inst = inst.replace(f"{SUPER}{os.sep}{OLD_NAME}{os.sep}",
                                f"{SUPER}{os.sep}{NEW_NAME}{os.sep}")
        print(f"\n[apply] instantane : {inst}")
        if not j.get("renomme"):
            print("[apply] le dossier n'a PAS ete renomme : aucune reference n'a ete modifiee.")
            return 2
        v = verifier()
        print(f"[apply] verification : {v['ok']} OK, {v['ok_parent']} parent seul, "
              f"{len(v['absents'])} ABSENT(S), {len(v['restes_ancien_nom'])} reste(s) de l'ancien nom")
        for x in v["absents"] + v["restes_ancien_nom"]:
            print("   ! " + str(x))
        return 1 if (v["absents"] or v["restes_ancien_nom"]) else 0
    return 0


if __name__ == "__main__":
    sys.exit(_main())