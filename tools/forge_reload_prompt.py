"""forge_reload_prompt.py — Popup branded Nokido expliquant l'UAC (cas par cas) avant reload.

__FORGE_COLOR__ = "infra-ops"

POURQUOI : l'UAC n'est requis QUE pour restart LaForge-Master LUI-MÊME (service SCM).
Les SERVICES enfants (hub :8766, ChainExecutor, daemons) se relancent SANS UAC via l'API
du superviseur :8765 (Master tourne déjà élevé = LocalSystem). Ce popup s'affiche AVANT
la boîte UAC native (non-thémable), aux couleurs Nokido, pour expliquer — selon le CAS —
pourquoi l'élévation est demandée. Fin de l'UAC opaque.

CONSENTEMENT : le popup n'élève RIEN seul. L'utilisateur clique "Redémarrer" → lance
nokido_stop.ps1 puis nokido_start.ps1 dans UN shell élevé (1 seul UAC). On NE fait PAS
`Restart-Service LaForge-Master` (se coince SERVICE_PAUSED, hub pas relancé — cf mémoire
feedback_boot_via_launcher).

CONTEXTE : GUI → session user (desktop). Lancer :
  - direct : `LAFORGE_PYTHON tools/forge_reload_prompt.py --case <cas>`
  - ou spawné par le superviseur en runAs=interactive (WTSQueryUserToken) sur flag.

USAGE : forge_reload_prompt.py [--case master_down|supervisor_code|services_def|cold_boot|generic]
                               [--reason "texte custom"] [--mode reload|start]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS_STOP = ROOT / "tools" / "nokido_stop.ps1"
PS_START = ROOT / "tools" / "nokido_start.ps1"

# Palette Nokido (cohérente ANSI launcher / design tokens)
BG = "#0B0E14"        # fond sombre
PANEL = "#11161F"     # panneau
GREEN = "#5FE08A"     # vert Nokido (accent)
ORANGE = "#E3B341"    # warn UAC
TEXT = "#E6EDF3"      # texte
DIM = "#7D8590"       # texte secondaire
RED = "#F0625D"

LOGO = "⚙  Nokido"

# Explication CAS PAR CAS du POURQUOI de l'UAC (sélection via --case).
# Chaque cas dit pourquoi CETTE situation exige l'élévation Master (SCM).
CASES = {
    "generic": (
        "Redémarrage de la flotte Nokido (superviseur LaForge-Master).\n\n"
        "Windows demande l'autorisation administrateur (UAC) car le contrôle des "
        "services Windows (SCM start/stop) exige l'élévation."
    ),
    "master_down": (
        "CAS : LaForge-Master (le superviseur) ne répond plus.\n\n"
        "Un redémarrage à froid via le gestionnaire de services Windows (SCM) est requis : "
        "seul SCM (admin / UAC) peut relever Master quand il est tombé.\n\n"
        "En temps normal les services se relancent sans UAC via l'API de Master — mais là, "
        "Master étant mort, cette API n'existe plus."
    ),
    "supervisor_code": (
        "CAS : le code du superviseur (proxy_deno/core/supervisor.ts) a changé.\n\n"
        "Master doit redémarrer pour recharger son propre code. Comme c'est un service "
        "Windows, l'opération passe par SCM → élévation (UAC).\n\n"
        "Les enfants (hub, daemons), eux, se rechargent SANS UAC via l'API superviseur."
    ),
    "services_def": (
        "CAS : une définition services.toml (env / heartbeat / wave) a été modifiée "
        "pour un service DÉJÀ en cours.\n\n"
        "Le hot-reload du superviseur est ADDITIF (il ne prend que les NOUVEAUX services) ; "
        "relire une def modifiée impose un restart de Master → SCM → UAC.\n\n"
        "Note : le CODE d'un service, lui, s'active sans UAC par un simple restart enfant."
    ),
    "cold_boot": (
        "CAS : démarrage à froid de la flotte Nokido après un arrêt complet.\n\n"
        "Le lancement des services Windows (SCM) exige l'élévation administrateur (UAC)."
    ),
}

# Réassurance commune (footer) — affichée pour TOUS les cas.
FOOTER = (
    "Rien d'autre n'est élevé. Aucune connexion sortante. Tout reste local.\n"
    "L'UAC ne concerne QUE le superviseur Master (service SCM) : les services enfants "
    "(hub, ChainExecutor, daemons) se relancent SANS UAC via l'API :8765."
)


def _elevated_reload(mode: str) -> None:
    """Lance le reload dans UN shell PowerShell élevé (1 seul UAC).

    mode=reload : stop puis start (réactive les defs services.toml modifiées).
    mode=start  : start seul (idempotent).
    Les .ps1 s'auto-élèvent ; lancés depuis un shell déjà admin -> pas de double UAC.
    """
    if mode == "reload" and PS_STOP.exists():
        inner = f"& '{PS_STOP}'; Start-Sleep -Seconds 3; & '{PS_START}'"
    else:
        inner = f"& '{PS_START}'"
    # -Verb RunAs => UAC unique ; le shell élevé enchaîne stop puis start.
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"Start-Process powershell -Verb RunAs -ArgumentList "
            f"'-NoProfile','-ExecutionPolicy','Bypass','-Command',\"{inner}\"",
        ]
    )


def _show_gui(reason: str, mode: str, case: str = "generic") -> int:
    import tkinter as tk

    root = tk.Tk()
    root.title("Nokido — Redémarrage")
    root.configure(bg=BG)
    root.attributes("-topmost", True)
    w, h = 580, 520
    root.update_idletasks()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(root, text=LOGO, bg=BG, fg=GREEN, font=("Consolas", 26, "bold")).pack(pady=(20, 2))
    tk.Label(root, text="Autorisation administrateur requise (UAC)", bg=BG, fg=TEXT,
             font=("Segoe UI", 13, "bold")).pack(pady=(0, 2))
    tk.Label(root, text=f"— pourquoi · cas : {case} —", bg=BG, fg=ORANGE,
             font=("Segoe UI", 9)).pack()

    panel = tk.Frame(root, bg=PANEL)
    panel.pack(fill="both", expand=True, padx=22, pady=(12, 6))
    tk.Label(panel, text=reason, bg=PANEL, fg=TEXT, font=("Segoe UI", 10),
             justify="left", wraplength=w - 70, anchor="nw").pack(padx=16, pady=14, fill="both", expand=True)

    tk.Label(root, text=FOOTER, bg=BG, fg=DIM, font=("Segoe UI", 8),
             justify="left", wraplength=w - 50).pack(padx=22, pady=(0, 8), fill="x")

    btns = tk.Frame(root, bg=BG)
    btns.pack(pady=(0, 18))

    def _go():
        _elevated_reload(mode)
        root.destroy()

    tk.Button(btns, text="  Redémarrer Nokido (admin)  ", command=_go, bg=GREEN, fg=BG,
              activebackground=TEXT, font=("Segoe UI", 11, "bold"), relief="flat", cursor="hand2").pack(side="left", padx=8)
    tk.Button(btns, text="  Annuler  ", command=root.destroy, bg=PANEL, fg=DIM,
              activebackground=RED, font=("Segoe UI", 11), relief="flat", cursor="hand2").pack(side="left", padx=8)

    root.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Popup branded Nokido — explainer UAC (cas par cas) avant reload")
    ap.add_argument("--case", choices=list(CASES), default="generic",
                    help="cas expliquant POURQUOI l'UAC est demandé")
    ap.add_argument("--reason", default=None, help="texte custom (override --case)")
    ap.add_argument("--mode", choices=["reload", "start"], default="reload")
    args = ap.parse_args()
    reason = args.reason or CASES.get(args.case, CASES["generic"])
    try:
        return _show_gui(reason, args.mode, args.case)
    except Exception as e:
        # Pas d'affichage (session 0 / headless) -> fallback console.
        print(f"[reload_prompt] GUI indisponible ({e}). Cas={args.case}.\n{reason}\n\n{FOOTER}", flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
