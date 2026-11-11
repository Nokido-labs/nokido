"""Audit des processus (Security 4688/4689), gouverne par Nokido.

Owner 6/11 : « active l'audit d'evenements, gouverne par nokido ». L'inspecteur avait tue deux fois le superviseur sans trace
nommant le tueur. L'activation passe par l'ordre `audit-processus` : Oui au tray, puis UAC, et l'etat atteint est relu.

Limite assumee : 4688 nomme un `taskkill` et sa ligne de commande, 4689 date la fin d'un processus. Un kill par API
(psutil, TerminateProcess) ne cree aucun processus et ne nomme pas son auteur : `--qui-a-tue` dit alors INCONNU.

Ligne de commande : le journal Security la conserve, secrets eventuels compris. Il n'est lisible que par les
administrateurs et le groupe Lecteurs des journaux ; `--qui-a-tue` masque ce qu'il affiche.

    python tools/forge_audit_processus.py --statut
    python tools/forge_audit_processus.py --activer      (administrateur)
    python tools/forge_audit_processus.py --qui-a-tue 17608 --minutes 120
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import time
from pathlib import Path

__FORGE_COLOR__ = "Observabilite/Trace/audit"

# Fichier d'etat : _fichier_etat(), sous la racine de donnees commune.
# GUID et non noms : les sous-categories sont traduites (« Creation du processus »).
GUID_CREATION = "{0CCE922B-69AE-11D9-BED3-505054503030}"
GUID_FIN = "{0CCE922C-69AE-11D9-BED3-505054503030}"
CLE_LIGNE = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit"
TAILLE_JOURNAL = 209715200  # 200 Mo : 20 Mo par defaut, vite ecrases par une stack qui lance beaucoup de processus
SID_LECTEURS = "S-1-5-32-573"  # Lecteurs des journaux d'evenements
_TUE = re.compile(r"taskkill|stop-process|\.kill\(|pskill", re.I)


def commandes_activation() -> list[list[str]]:
    """Ce que fait l'activation, et rien d'autre. Reversible : auditpol /success:disable."""
    return [
        ["auditpol", "/set", "/subcategory:" + GUID_CREATION, "/success:enable"],
        ["auditpol", "/set", "/subcategory:" + GUID_FIN, "/success:enable"],
        ["reg", "add", CLE_LIGNE, "/v", "ProcessCreationIncludeCmdLine_Enabled", "/t", "REG_DWORD", "/d", "1", "/f"],
        ["wevtutil", "sl", "Security", "/ms:%d" % TAILLE_JOURNAL],
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "try { Add-LocalGroupMember -SID '%s' -Member $env:USERNAME -ErrorAction Stop } "
         "catch [Microsoft.PowerShell.Commands.MemberExistsException] { }" % SID_LECTEURS],
    ]


def audit_actif(sortie_csv: str) -> str:
    """Pur. Sortie de `auditpol /get /r` -> OUI | NON | ILLISIBLE. Liste blanche sur la colonne Inclusion."""
    try:
        lignes = [ligne for ligne in csv.reader(io.StringIO((sortie_csv or "").strip())) if ligne]
        valeur = lignes[1][4].strip().lower()
    except (IndexError, csv.Error):  # muet-ok : forme inattendue rendue ILLISIBLE, jamais NON
        return "ILLISIBLE"
    # Valeurs traduites, et abimees par la console (« R‚ussite » en cp850) : le joker couvre le caractere accentue.
    if re.search(r"succ|r.{1,2}ussite", valeur):
        return "OUI"
    if re.search(r"no auditing|aucun|pas d.{1,2}audit", valeur):
        return "NON"
    return "ILLISIBLE"  # valeur inconnue : surtout pas NON


def etat_global(preuves: dict) -> str:
    """Pur. ACTIF seulement si chaque preuve est OUI ; une preuve illisible n'est pas lue comme un non."""
    valeurs = set(preuves.values())
    if valeurs == {"OUI"}:
        return "ACTIF"
    if "ILLISIBLE" in valeurs:
        return "ILLISIBLE"
    return "PARTIEL" if "OUI" in valeurs else "INACTIF"


def qui_a_tue(evenements: list[dict], pid: str) -> dict:
    """Pur. Les 4688 d'un outil de kill dont la ligne de commande nomme CE pid, et le 4689 de sa fin."""
    motif = re.compile(r"(?<!\d)%s(?!\d)" % re.escape(str(pid)))
    tueurs = [e for e in evenements if e.get("id") == 4688 and _TUE.search(str(e.get("cmd") or e.get("image") or ""))
              and motif.search(str(e.get("cmd") or ""))]
    fin = next((e for e in evenements if e.get("id") == 4689 and str(e.get("pid")) == str(pid)), None)
    if tueurs:
        verdict = "NOMME : %s, lance par %s (pid %s)" % (tueurs[0].get("image"), tueurs[0].get("parent"), tueurs[0].get("pid_parent"))
    else:
        verdict = "INCONNU : aucun outil de kill ne nomme ce pid ; un kill par API ne laisse pas de 4688"
    return {"pid": str(pid), "tueurs": tueurs, "fin": fin, "verdict": verdict}


def _lancer(cmd: list[str], t: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=t)


def relire() -> dict:
    """L'etat ATTEINT, relu sur la machine. auditpol exige l'administrateur : hors eleve, ces preuves sont ILLISIBLE."""
    preuves = {}
    brut = {}
    for nom, guid in (("creation", GUID_CREATION), ("fin", GUID_FIN)):
        try:
            sortie = _lancer(["auditpol", "/get", "/subcategory:" + guid, "/r"])
            preuves[nom] = audit_actif(sortie.stdout)
            brut[nom] = ((sortie.stdout or "") + (sortie.stderr or ""))[:400]
        except (OSError, subprocess.SubprocessError) as e:  # rendu ILLISIBLE, et dit dans le brut
            preuves[nom] = "ILLISIBLE"
            brut[nom] = "%s : %s" % (type(e).__name__, e)
    try:
        r = _lancer(["reg", "query", CLE_LIGNE, "/v", "ProcessCreationIncludeCmdLine_Enabled"])
        preuves["ligne_de_commande"] = "OUI" if "0x1" in r.stdout else ("NON" if r.returncode else "ILLISIBLE")
    except (OSError, subprocess.SubprocessError):  # muet-ok : rendu ILLISIBLE
        preuves["ligne_de_commande"] = "ILLISIBLE"
    # L'effet reel : un evenement ecrit. La politique seule ne le prouve pas ; illisible sans droit, et c'est dit.
    try:
        ev = _lancer(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                      "(Get-WinEvent -FilterHashtable @{LogName='Security';Id=4688} -MaxEvents 1 -ErrorAction Stop)"
                      ".TimeCreated.ToString('s')"])
        dernier = ev.stdout.strip() or "ILLISIBLE : %s" % (ev.stderr or "").strip()[:160]
    except (OSError, subprocess.SubprocessError) as e:
        dernier = "ILLISIBLE : %s" % type(e).__name__
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "etat": etat_global(preuves), "preuves": preuves,
            "dernier_4688": dernier, "brut": brut}


def _fichier_etat() -> Path | None:
    """La racine de donnees vient de forge_db_path, jamais de __file__. Illisible -> None, et c'est dit."""
    try:
        try:
            from nokido_agent.app.forge_db_path import racine_donnees
        except ImportError:
            # 9/11 : sous trusted_script le paquet nokido_agent n'est pas importable ; le depot l'est.
            racine_depot = str(Path(__file__).resolve().parents[1])
            if racine_depot not in sys.path:
                sys.path.insert(0, racine_depot)
            from app.forge_db_path import racine_donnees

        return Path(racine_donnees()) / "logs" / "audit_processus_etat.json"
    except Exception as e:  # noqa: BLE001 - dit : l'etat reste affiche en console
        print("etat non conserve, racine de donnees illisible : %s" % type(e).__name__, file=sys.stderr)
        return None


def _ecrire_etat(etat: dict) -> None:
    f = _fichier_etat()
    if f:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(etat, ensure_ascii=False, indent=1), encoding="utf-8")


def activer() -> int:
    """Applique puis relit : une commande acceptee n'est pas un etat atteint."""
    echecs = []
    for cmd in commandes_activation():
        r = _lancer(cmd, 60)
        print("rc=%s  %s" % (r.returncode, " ".join(cmd)[:90]))
        if r.returncode:
            echecs.append({"cmd": cmd[0], "rc": r.returncode, "sortie": (r.stderr or r.stdout).strip()[:200]})
    etat = relire()
    etat["echecs"] = echecs
    _ecrire_etat(etat)
    print(json.dumps(etat, ensure_ascii=False, indent=1))
    return 0 if etat["etat"] == "ACTIF" and not echecs else 1


def _lire_securite(minutes: int) -> list[dict]:
    """4688 et 4689 recents. Illisible sans droit : l'exception remonte, ce n'est pas « rien ne s'est passe »."""
    script = ("Get-WinEvent -FilterHashtable @{LogName='Security';Id=4688,4689;StartTime=(Get-Date).AddMinutes(-%d)} "
              "-ErrorAction Stop | ForEach-Object { $x=[xml]$_.ToXml(); $d=@{}; "
              "foreach($n in $x.Event.EventData.Data){$d[$n.Name]=$n.'#text'}; "
              "[PSCustomObject]@{id=$_.Id;ts=$_.TimeCreated.ToString('o');image=$d.NewProcessName;cmd=$d.CommandLine;"
              "parent=$d.ParentProcessName;pid_parent=$d.ProcessId;fin_image=$d.ProcessName;pid_fin=$d.ProcessId;code=$d.Status} "
              "| ConvertTo-Json -Compress }" % minutes)
    r = _lancer(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], 180)
    if r.returncode:
        raise PermissionError((r.stderr or "").strip()[:240])
    out = []
    for ligne in r.stdout.splitlines():
        try:
            e = json.loads(ligne)
        except ValueError:
            print("ligne d'evenement illisible, ignoree : %s" % ligne[:60], file=sys.stderr)
            continue
        if e.get("id") == 4689:
            e.update(image=e.get("fin_image"), pid=str(int(str(e.get("pid_fin")), 16)) if e.get("pid_fin") else None)
        elif e.get("pid_parent"):
            e["pid_parent"] = str(int(str(e["pid_parent"]), 16))
        out.append(e)
    return out


def _masquer(texte: str) -> str:
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_text

        return redact_text(texte)[0]
    except Exception:  # noqa: BLE001 - masque indisponible : ne rien afficher plutot qu'un secret
        return "[ligne de commande non affichee : masque indisponible]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--statut", action="store_true")
    ap.add_argument("--activer", action="store_true")
    ap.add_argument("--qui-a-tue", metavar="PID")
    ap.add_argument("--minutes", type=int, default=120)
    a = ap.parse_args()
    if a.activer:
        return activer()
    if a.qui_a_tue:
        try:
            r = qui_a_tue(_lire_securite(a.minutes), a.qui_a_tue)
        except (PermissionError, OSError, subprocess.SubprocessError) as e:
            print("ILLISIBLE : journal Security non lu (%s)" % str(e)[:240])
            return 2
        for t in r["tueurs"]:
            t["cmd"] = _masquer(str(t.get("cmd") or ""))
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    etat = relire()
    f = _fichier_etat()
    if f and f.exists():
        try:
            etat["derniere_activation"] = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            etat["derniere_activation"] = "ILLISIBLE : %s" % e
    print(json.dumps(etat, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
