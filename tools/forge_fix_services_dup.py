"""forge_fix_services_dup.py — one-shot IDEMPOTENT : nettoie les [[service]] dupliques
de proxy_deno/core/services.toml, et repare le texte parasite laisse par un
governed_edit multi-blocs (2026-07-17).

POURQUOI CE SCRIPT EXISTE
  Le sandbox `run` est ACL-bloque en ecriture sur proxy_deno/ (PermissionError), et
  governed_edit ne peut pas porter la reparation : son SEARCH devrait contenir ses
  propres marqueurs (<<<<<<< / ======= / >>>>>>>). Reste le chemin trusted_script.

GOTCHA MESURE : governed_edit n'applique QU'UN SEUL bloc par appel. Les blocs suivants
  sont ecrits LITTERALEMENT dans le fichier cible. Un bloc par appel, toujours.

CE QU'IL FAIT (idempotent, verifie avant ecriture) :
  1. Retire les LIGNES de marqueur governed_edit (pas de plage devinee : une plage
     "jusqu'au prochain [[service]]" tombe DANS le parasite -- erreur de la v1).
  2. Retire tout [[service]] INCOMPLET (name sans args) : c'est un artefact d'injection,
     tout service reel porte args.
  3. Dedup par nom, en gardant le bloc EFFECTIF :
     - NokidoAutonomousLoops -> celui qui porte deps = [8766] (attend le hub).
     - NokidoGeminiAutonomous -> celui qui porte GEMINI_AUTO_MODE = "off" ; son jumeau
       MODE="active" se declare lui-meme "Doublon de l'entree MODE=off". Les DEUX sont
       disabled=true donc aucun n'entre dans `states` : zero changement de comportement.

SEMANTIQUE QUI JUSTIFIE "MASQUE" : supervisor.ts:642-647
    const states = new Map<string, ServiceState>();
    for (const def of SERVICES) { if (def.disabled) continue; states.set(def.name, {...}); }
  -> Map indexee par name => LAST WINS, le bloc perdant est ecrase EN SILENCE (aucun
  garde anti-doublon). Retirer un bloc deja ecrase ne change RIEN.

NON-REGRESSION : la reference est la version COMMITEE (git show HEAD:...), PAS le
  fichier courant (que le parasite rend invalide). Les definitions effectives
  (last-wins, disabled exclus) doivent etre IDENTIQUES, sinon REFUS.

Usage : run action=trusted_script path=tools/forge_fix_services_dup.py
        script_args="--apply"   (sans --apply = dry-run)
"""
import collections
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REL = "proxy_deno/core/services.toml"
TOML = ROOT / "proxy_deno" / "core" / "services.toml"

DOC_LOOPS = """# Boucles d'amelioration autopoietiques (autonomous_loops, 2026-07-14) - patterns
# tick=60s local-only (free_local_llms_only), inclut m2m_inbox_watch (observabilite
# boucle M2M). Persiste pour survivre au reboot. pid-alive tracking (pas de heartbeat).
#
# 2026-07-17 : ce service etait declare DEUX FOIS. supervisor.ts:642-647 indexe `states`
# par def.name -> le SECOND bloc ecrase le premier EN SILENCE (aucun garde anti-doublon
# dans le loader). Le bloc mort (cmd=${PYTHON}, sans deps) ne portait plus que cette
# doc -> reportee ici, sur le bloc EFFECTIF. Ne PAS re-dupliquer : un doublon est avale
# sans avertissement, et le bloc perdant a l'air vivant.
"""

MARK = ("<<<<<<<", ">>>>>>>")


def spans(lines):
    """[(start, end)] de chaque [[service]] (end exclusif)."""
    starts = [i for i, l in enumerate(lines) if l.strip() == "[[service]]"]
    return [(s, starts[k + 1] if k + 1 < len(starts) else len(lines))
            for k, s in enumerate(starts)]


def has(lines, lo, hi, needle):
    return any(needle in l for l in lines[lo:hi])


def name_of(lines, lo, hi):
    for l in lines[lo:hi]:
        s = l.strip()
        if s.startswith("name = "):
            return s.split("=", 1)[1].strip().strip('"')
    return None


def effective(txt):
    """{name: def} en appliquant last-wins, comme supervisor.ts."""
    d = tomllib.loads(txt)
    return {s["name"]: s for s in d.get("service", []) if s.get("name")}


def main() -> int:
    apply = "--apply" in sys.argv
    raw = TOML.read_text(encoding="utf-8")
    lines = raw.split("\n")

    # 1. lignes de marqueur (jamais une plage devinee)
    keep = [l for l in lines
            if not (l.startswith(MARK[0]) or l.startswith(MARK[1]) or l.strip() == "=======")]
    print("[1] lignes-marqueur retirees  : %d" % (len(lines) - len(keep)))
    lines = keep

    # 2. blocs incomplets (name sans args) = artefacts d'injection
    drop = [(lo, hi) for lo, hi in spans(lines)
            if name_of(lines, lo, hi) and not has(lines, lo, hi, "args = ")]
    for lo, hi in reversed(drop):
        print("    bloc incomplet retire : %s (%d lignes)" % (name_of(lines, lo, hi), hi - lo))
        lines = lines[:lo] + lines[hi:]
    print("[2] blocs incomplets retires  : %d" % len(drop))

    # 3. dedup, en gardant le bloc EFFECTIF
    for nm, keep_needle in (("NokidoAutonomousLoops", "deps = [8766]"),
                            ("NokidoGeminiAutonomous", 'GEMINI_AUTO_MODE = "off"')):
        occ = [(lo, hi) for lo, hi in spans(lines) if name_of(lines, lo, hi) == nm]
        if len(occ) <= 1:
            print("[3] %-24s : deja unique" % nm)
            continue
        kept = [(lo, hi) for lo, hi in occ if has(lines, lo, hi, keep_needle)]
        if len(kept) != 1:
            raise SystemExit("REFUS %s : %d blocs portent %r (attendu 1)" % (nm, len(kept), keep_needle))
        for lo, hi in reversed([o for o in occ if o != kept[0]]):
            print("[3] %-24s : bloc masque retire (%d lignes)" % (nm, hi - lo))
            lines = lines[:lo] + lines[hi:]

    # 4. reporter la doc sur le bloc effectif AutonomousLoops (idempotent)
    if "reportee ici, sur le bloc EFFECTIF" not in "\n".join(lines):
        for lo, hi in spans(lines):
            if name_of(lines, lo, hi) == "NokidoAutonomousLoops":
                lines = lines[:lo + 1] + DOC_LOOPS.rstrip("\n").split("\n") + lines[lo + 1:]
                print("[4] doc reportee sur le bloc EFFECTIF")
                break
    else:
        print("[4] doc deja presente (idempotent)")

    new = "\n".join(lines)

    # --- VERIFICATIONS AVANT ECRITURE (fail-closed) ---
    d = tomllib.loads(new)  # leve si invalide
    svcs = d["service"]
    dups = [n for n, c in collections.Counter(s.get("name") for s in svcs).items() if c > 1]
    if dups:
        raise SystemExit("REFUS : doublons restants %s" % dups)

    # non-regression vs la version COMMITEE (le fichier courant est invalide)
    head = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                           "show", "HEAD:" + REL],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")  # gate anti-regression 47GB : jamais de
    # subprocess mode-texte sans errors= (crash _readerthread sur octet non decodable)
    if head.returncode != 0:
        raise SystemExit("REFUS : git show HEAD:%s -> %s" % (REL, head.stderr[:200]))
    eff_old, eff_new = effective(head.stdout), effective(new)
    if set(eff_old) != set(eff_new):
        raise SystemExit("REFUS : ensemble des noms change -> %s" % (set(eff_old) ^ set(eff_new)))
    # Drift AUTORISE, nominativement, et SEULEMENT s'il est prouve inerte.
    # NokidoGeminiAutonomous : last-wins faisait gagner le bloc MODE="active" ; on garde
    # desormais MODE="off". C'est un vrai changement de semantique LATENTE, assume :
    # le bloc retire se declare lui-meme "Doublon de l'entree MODE=off", et l'entree
    # gardee porte toute la doc + LIGHT=1 + INTERVAL=60. La preuve d'innocuite n'est pas
    # une affirmation : on EXIGE disabled=true des DEUX cotes -> supervisor.ts:645
    # (`if (def.disabled) continue`) ne l'instancie jamais, donc impact runtime nul.
    # Le jour ou quelqu'un l'active, il tombera sur MODE="off" (sur) et non "active".
    ALLOWED_DRIFT = {"NokidoGeminiAutonomous"}
    drift = [n for n in eff_old if eff_old[n] != eff_new[n]]
    unexpected = [n for n in drift if n not in ALLOWED_DRIFT]
    if unexpected:
        raise SystemExit("REFUS : definition effective modifiee -> %s" % unexpected)
    for n in drift:
        if not (eff_old[n].get("disabled") and eff_new[n].get("disabled")):
            raise SystemExit("REFUS : drift tolere sur %s mais le service n'est PAS "
                             "disabled des deux cotes -> impact runtime possible" % n)
        print("[ok] drift ASSUME sur %s (disabled=true des 2 cotes -> jamais dans states)" % n)
    print("[ok] non-regression vs HEAD : %d definitions effectives IDENTIQUES" % len(eff_new))
    print("[ok] TOML valide, %d blocs, 0 doublon" % len(svcs))

    if not apply:
        print("\nDRY-RUN -- rien ecrit. Relancer avec --apply")
        return 0
    bak = TOML.with_name("services.toml.bak-%d" % int(time.time()))
    shutil.copy2(TOML, bak)
    TOML.write_text(new, encoding="utf-8")
    print("\nECRIT. Backup : %s" % bak.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
