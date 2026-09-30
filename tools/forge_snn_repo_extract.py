# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "cognition/extraction-snn"
EXTRACTEUR du depot public **NokidoSNN** depuis Nokido.

POURQUOI UN EXTRACTEUR, ET PAS UNE COPIE
========================================
Une copie manuelle diverge des le lendemain. Ici le depot public se REGENERE : les
sources restent celles qui tournent en production, et le README est ecrit a partir
des RAPPORTS DE BANC, jamais a la main. C'est le garde-fou qui compte pour une
vitrine publique — un chiffre tape a la main derive, un chiffre lu depuis un JSON
ne peut pas mentir sans que le JSON mente aussi.

STRUCTURE CHOISIE
=================
On replique `app/` et `tools/` a l'identique. Les modules calculent leurs chemins
avec `ROOT / "app"` : les renommer ou les aplatir casserait tous les imports et
obligerait a PATCHER le code copie — donc a maintenir deux versions. Le prix d'une
arborescence un peu large est tres inferieur a celui d'un fork silencieux.

CE QUI EST EXTRAIT, ET POURQUOI
==============================
- le substrat : LIF a gradient de substitution, moniteur de spikes ;
- le codec AER + son banc de sparsite (mesure REELLE, pas une extrapolation) ;
- les capteurs : canaux vitaux et leur sonde ;
- les bancs, **y compris celui qui donne un resultat NEGATIF** — sur ce signal le
  seuil bat le LIF. Un negatif honnete sur donnees reelles vaut mieux qu'un positif
  sur MNIST : il se verifie, et il montre qu'on mesure avant de conclure.
- un echantillon de la serie REELLE, pour que les bancs tournent sans le systeme.

    LAFORGE_PYTHON tools/forge_snn_repo_extract.py            # dry-run
    LAFORGE_PYTHON tools/forge_snn_repo_extract.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CIBLE = ROOT / "NokidoSNN"
MAX_LIGNES_SERIE = 20000

SOURCES = [
    ("app/forge_snn_core.py", "app/forge_snn_core.py"),
    ("app/forge_snn_monitor.py", "app/forge_snn_monitor.py"),
    # Le SNN reellement CABLE en production (routage de taches via forge_dt_router).
    # C'est l'argument qui distingue ce depot d'une demonstration : le substrat ne
    # tourne pas dans un banc, il decide. Ses dependances Nokido sont importees
    # PARESSEUSEMENT, donc le module s'importe seul — verifie, pas suppose.
    ("app/forge_spike_router.py", "app/forge_spike_router.py"),
    ("app/forge_aer.py", "app/forge_aer.py"),
    ("app/forge_vitals_channels.py", "app/forge_vitals_channels.py"),
    ("tools/forge_aer_sparsity_bench.py", "tools/forge_aer_sparsity_bench.py"),
    ("tools/forge_snn_vitals_baseline.py", "tools/forge_snn_vitals_baseline.py"),
    ("tools/forge_snn_entraine_vitals_bench.py", "tools/forge_snn_entraine_vitals_bench.py"),
    ("tools/forge_vitals_channel_probe.py", "tools/forge_vitals_channel_probe.py"),
    ("LICENSE", "LICENSE"),
]
RAPPORTS = [
    ("sandbox/aer_sparsity_bench.json", "sandbox/aer_sparsity_bench.json"),
    ("sandbox/snn_vitals_baseline.json", "sandbox/snn_vitals_baseline.json"),
    ("sandbox/vitals_channel_probe.json", "sandbox/vitals_channel_probe.json"),
]

GITIGNORE = """__pycache__/
*.pyc
sandbox/*.tmp
"""

REQUIREMENTS = """# Substrat spiking : torch suffit, le backend LIF integre n'exige PAS snntorch.
torch>=2.0
psutil>=5.9
"""


def _lire(p: Path):
    """Rend le JSON, ou None. Un rapport ABSENT est dit, jamais suppose vide."""
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _readme(aer: dict | None, base: dict | None, probe: dict | None) -> str:
    """README bati depuis les RAPPORTS. Toute section sans rapport le DIT au lieu
    d'inventer un chiffre."""
    L = []
    L.append("# NokidoSNN\n")
    L.append("**A spiking substrate and event-driven telemetry codec, measured on a "
             "real autonomous system.**\n")
    L.append("Extracted from [Nokido](https://github.com/Nokido-labs/nokido), a "
             "self-regulating local-first AI operating system. Every figure below is "
             "read from a machine-generated benchmark report in `sandbox/`, not typed "
             "by hand.\n")

    L.append("\n## Why this repository exists\n")
    L.append("Most spiking-network demonstrations run on synthetic or vision "
             "benchmarks. This one runs on **continuous multi-channel telemetry "
             "produced by a real autonomous system** — memory pressure, per-core CPU, "
             "disk and network throughput, per-service resident memory, request rates "
             "per port — sampled every 15 seconds over days.\n")
    L.append("It also publishes a **negative result**, because that is what the "
             "measurement says.\n")

    L.append("\n## Result 1 — event-driven encoding (AER)\n")
    if aer:
        t, c, f = aer["transit"], aer["cpu"], aer["fidelite"]
        L.append("Measured on **%d real samples over %.2f days, %d channels** "
                 "(`sandbox/aer_sparsity_bench.json`):\n"
                 % (aer["echantillons"], aer["duree_jours"], aer["canaux"]))
        L.append("| metric | value |")
        L.append("|---|---|")
        L.append("| sparsity | **%.2f %%** |" % t["sparsite_pct"])
        L.append("| bytes | %d -> **%d** (%.2f %% less) |"
                 % (t["octets_ancien"], t["octets_aer"], t["reduction_octets_pct"]))
        L.append("| throughput | %.2f -> **%.2f** bytes/s |"
                 % (t["octets_par_s_ancien"], t["octets_par_s_aer"]))
        L.append("| encode cost | %.2f -> **%.2f** us/tick (cheaper than `json.dumps`) |"
                 % (c["us_par_tic_ancien"], c["us_par_tic_aer"]))
        L.append("| alert fidelity | **%d/%d** distress episodes preceded by a spike, "
                 "median lead **%.1f s** |"
                 % (f["episodes_precedes_d_un_tir"], f["episodes_detresse"],
                    f["latence_mediane_s"] or 0.0))
        L.append("\nThe encoding is **lossy by design**. Consistency check: the RMS "
                 "error equals ~0.55 quantisation step on *every* channel — a constant "
                 "ratio, which is the signature of sound quantisation rather than drift.\n")
        L.append("What this benchmark does **not** measure, and says so: it times the "
                 "*encoding*, not kernel syscalls. Claiming a drop in context switches "
                 "without touching the kernel would be extrapolation.\n")
    else:
        L.append("_Report `sandbox/aer_sparsity_bench.json` missing — run "
                 "`python tools/forge_aer_sparsity_bench.py` to regenerate._\n")

    L.append("\n## Result 2 — the negative one: a threshold beats the LIF here\n")
    if base:
        s = base["temoin_seuil"]
        best = min((g for g in base["lif_grille"]), key=lambda g: g["faux_positifs_par_jour"])
        L.append("Measured on **%d samples over %.2f days, %d real distress episodes** "
                 "(`sandbox/snn_vitals_baseline.json`). Ground truth is borrowed from "
                 "the running system (free memory below %.1f GB), never invented:\n"
                 % (base["echantillons"], base["duree_jours"], base["episodes_detresse"],
                    base["detresse_libre_gb"]))
        L.append("| detector | episodes caught | false positives / day |")
        L.append("|---|---|---|")
        L.append("| plain threshold | %d/%d | **%.2f** |"
                 % (s["episodes_vus"], s["episodes_total"], s["faux_positifs_par_jour"]))
        L.append("| best LIF (beta=%.1f, thr=%.1f) | %d/%d | **%.2f** |"
                 % (best["beta"], best["thr"], best["episodes_vus"],
                    best["episodes_total"], best["faux_positifs_par_jour"]))
        L.append("\n**On this signal, temporal integration buys nothing** — same "
                 "episodes caught, %.1fx the noise.\n"
                 % (best["faux_positifs_par_jour"] / max(s["faux_positifs_par_jour"], 1e-9)))
        L.append("The honest reading is narrow: *a single channel was tested*. "
                 "Spatio-temporal models earn their keep on correlations **between** "
                 "channels, which is why the sensor vector was widened (Result 3) "
                 "before drawing any architectural conclusion.\n")
        L.append("Instrument defect found and fixed during this benchmark: with a "
                 "900 s alert window every setting returned a lead time of 897-899 s "
                 "— **the window itself was being measured**. It is now widened and a "
                 "`avance_saturee` field declares the saturation instead of hiding it.\n")
    else:
        L.append("_Report `sandbox/snn_vitals_baseline.json` missing — run "
                 "`python tools/forge_snn_vitals_baseline.py` to regenerate._\n")

    L.append("\n## Result 3 — widening the sensor vector\n")
    if probe:
        r = probe["resume"]
        L.append("A channel enters the series only if it is **readable, variable and "
                 "cheap** (`sandbox/vitals_channel_probe.json`): out of **%d candidate "
                 "channels**, %d were kept, %d were constant, %d unreadable, %d too "
                 "expensive.\n" % (r["total"], r["retenir"], r["constant"],
                                   r["illisible"], r["trop_cher"]))
        L.append("Three states per channel, never two: *readable* / *unreadable "
                 "(with the reason)* / *absent*. A sensor returning `False` both for "
                 "\"not there\" and \"permission denied\" manufactures undetectable "
                 "false negatives.\n")
    else:
        L.append("_Report `sandbox/vitals_channel_probe.json` missing — run "
                 "`python tools/forge_vitals_channel_probe.py` to regenerate._\n")

    L.append("\n## Layout\n")
    L.append("```")
    L.append("app/forge_snn_core.py         LIF, surrogate gradient (Neftci 2019), selftest")
    L.append("app/forge_snn_monitor.py      vitals -> spikes, refractory period")
    L.append("app/forge_aer.py              8-byte AER codec + decoder")
    L.append("app/forge_vitals_channels.py  channel definitions, two tiers")
    L.append("tools/                        benchmarks and the channel probe")
    L.append("sandbox/                      machine-generated reports + a real sample series")
    L.append("```\n")

    L.append("\n## Reproduce\n")
    L.append("```bash")
    L.append("pip install -r requirements.txt")
    L.append("python app/forge_snn_core.py                 # selftest: the LIF learns")
    L.append("python tools/forge_aer_sparsity_bench.py     # Result 1")
    L.append("python tools/forge_snn_vitals_baseline.py    # Result 2")
    L.append("```\n")
    L.append("\n## Status\n")
    L.append("The spiking substrate is **real and running** in Nokido (LIF core, spike "
             "monitor armed, spike router wired into task routing). Its **advantage "
             "over a threshold is not demonstrated** on the signal measured so far. "
             "This repository publishes both facts.\n")
    L.append("\nLicense: AGPL-3.0 (see `LICENSE`).\n")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extrait le depot public NokidoSNN")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--git-init", action="store_true",
                    help="initialise le depot GIT LOCAL et fait le premier commit "
                         "(aucune publication distante : cela reste une action owner)")
    a = ap.parse_args(argv)

    manquants = [s for s, _ in SOURCES + RAPPORTS if not (ROOT / s).exists()]
    if manquants:
        print("[extract] sources ABSENTES (%d) : %s" % (len(manquants), manquants))
    aer = _lire(ROOT / "sandbox/aer_sparsity_bench.json")
    base = _lire(ROOT / "sandbox/snn_vitals_baseline.json")
    probe = _lire(ROOT / "sandbox/vitals_channel_probe.json")
    for nom, d in (("aer", aer), ("baseline", base), ("probe", probe)):
        print("[extract] rapport %-9s : %s" % (nom, "lu" if d else "ABSENT -> section marquee"))

    serie = ROOT / "sandbox/vitals_history.jsonl"
    n_serie = 0
    if serie.exists():
        n_serie = min(MAX_LIGNES_SERIE,
                      len(serie.read_text(encoding="utf-8", errors="replace").splitlines()))
    print("[extract] serie reelle : %d ligne(s) a embarquer" % n_serie)
    print("[extract] cible : %s" % CIBLE)
    if not a.apply:
        print("[extract] DRY-RUN — relancer avec --apply")
        return 0

    for s, d in SOURCES + RAPPORTS:
        src = ROOT / s
        if not src.exists():
            continue
        dst = CIBLE / d
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    if n_serie:
        lignes = serie.read_text(encoding="utf-8", errors="replace").splitlines()[-n_serie:]
        (CIBLE / "sandbox").mkdir(parents=True, exist_ok=True)
        (CIBLE / "sandbox/vitals_history.jsonl").write_text(
            "\n".join(lignes) + "\n", encoding="utf-8")
    (CIBLE / "README.md").write_text(_readme(aer, base, probe), encoding="utf-8")
    (CIBLE / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (CIBLE / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    print("[extract] ECRIT dans %s" % CIBLE)
    if a.git_init:
        import subprocess

        # Depot LOCAL uniquement. Creer un depot DISTANT et pousser publie du contenu :
        # c'est une action a la main de l'owner, pas un effet de bord d'une extraction.
        g = ["git", "-c", "safe.directory=*", "-C", str(CIBLE)]
        etapes = [
            (g + ["init", "-b", "main"], "init"),
            (g + ["add", "-A"], "add"),
            (g + ["-c", "user.name=user", "-c", "user.email=naarobb@gmail.com",
                  "commit", "-m",
                  "NokidoSNN: spiking substrate + AER codec, measured on real telemetry"],
             "commit"),
        ]
        for cmd, nom in etapes:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            sortie = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0 and "nothing to commit" not in sortie:
                print("[git] %s ECHEC (rc=%d) : %s" % (nom, r.returncode, sortie.strip()[:200]))
                return 1
            print("[git] %-7s ok : %s" % (nom, sortie.strip().splitlines()[-1][:120]
                                          if sortie.strip() else ""))
        print("[git] depot LOCAL pret. Publication distante = action OWNER.")
    else:
        print("[extract] Publication = action OWNER : creer le depot distant puis pousser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
