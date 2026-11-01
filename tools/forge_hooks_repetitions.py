"""forge_hooks_repetitions.py -- P1a MESURE SEULE : repetitions des injections de hooks dans une transcription.

Decision owner 20/10 : MESURER avant d'alleger. La mesure du 22/10 attribue ~8 % du contexte aux hooks et
~61 % de leurs injections sont des repetitions identiques. Cet instrument dit, POUR CHAQUE HOOK :
  - `injections`                 nombre de blocs injectes (un attachment = une invocation de hook) ;
  - `caracteres`                 volume injecte ;
  - `injections_identiques`      blocs identiques mot pour mot a l'injection PRECEDENTE du meme hook ;
  - `part_injections_identiques` identiques / injections ayant un precedent (la 1re n'en a pas) ;
  - `part_caracteres_identiques` caracteres des blocs identiques / caracteres injectes (gain potentiel).

Le hook est identifie par son `hookName` (`PreToolUse:capability-gate`, `SessionStart:startup`...), a defaut
par son `hookEvent`. La comparaison est STRICTE avec l'injection precedente du meme hook : une repetition qui
revient apres une autre valeur n'est PAS comptee (contrairement a une vue "deja vu dans le segment").

Le decoupage de la transcription est REUTILISE depuis `tools/forge_contexte_par_source.py`
(`injections_hooks`) : aucun parseur duplique. MESURE SEULEMENT, lecture seule : aucun fichier de hook n'est
lu ni modifie.

Usage : LAFORGE_PYTHON tools/forge_hooks_repetitions.py <transcription.jsonl> [...] [--sortie r.json] [--top 25]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

__FORGE_COLOR__ = "metabolisme-llm/instrument"

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge_contexte_par_source as C  # noqa: E402


def analyser_hooks(entrees) -> dict:
    """Agrege les injections par hook. Comparaison stricte avec l'injection precedente du meme hook."""
    stats, ordre, precedents = {}, [], {}
    for inj in C.injections_hooks(entrees):
        hook = inj["hook"]
        s = stats.get(hook)
        if s is None:
            s = stats[hook] = {"hook": hook, "evenements": set(), "types": set(), "injections": 0,
                               "caracteres": 0, "avec_precedent": 0, "injections_identiques": 0,
                               "caracteres_identiques": 0}
            ordre.append(hook)
        texte = inj["texte"]
        s["evenements"].add(inj["evenement"])
        s["types"].add(inj["type"])
        s["injections"] += 1
        s["caracteres"] += len(texte)
        precedent = precedents.get(hook)
        if precedent is not None:
            s["avec_precedent"] += 1
            if texte == precedent:
                s["injections_identiques"] += 1
                s["caracteres_identiques"] += len(texte)
        precedents[hook] = texte

    hooks = []
    for hook in ordre:
        s = stats[hook]
        s["evenements"] = sorted(s["evenements"])
        s["types"] = sorted(s["types"])
        s["part_injections_identiques"] = (s["injections_identiques"] / s["avec_precedent"]
                                           if s["avec_precedent"] else 0.0)
        s["part_caracteres_identiques"] = (s["caracteres_identiques"] / s["caracteres"]
                                           if s["caracteres"] else 0.0)
        hooks.append(s)
    hooks.sort(key=lambda s: (-s["caracteres"], s["hook"]))

    injections = sum(s["injections"] for s in hooks)
    caracteres = sum(s["caracteres"] for s in hooks)
    avec_precedent = sum(s["avec_precedent"] for s in hooks)
    identiques = sum(s["injections_identiques"] for s in hooks)
    car_identiques = sum(s["caracteres_identiques"] for s in hooks)
    return {
        "hooks": hooks,
        "totaux": {
            "hooks": len(hooks),
            "injections": injections,
            "caracteres": caracteres,
            "avec_precedent": avec_precedent,
            "injections_identiques": identiques,
            "caracteres_identiques": car_identiques,
            "part_injections_identiques": identiques / avec_precedent if avec_precedent else 0.0,
            "part_caracteres_identiques": car_identiques / caracteres if caracteres else 0.0,
        },
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("transcriptions", nargs="+")
    p.add_argument("--sortie", help="fichier JSON du rapport (un rapport par transcription)")
    p.add_argument("--top", type=int, default=25)
    a = p.parse_args(argv)
    rapports = []
    for chemin in a.transcriptions:
        entrees, illisibles = C._lire(Path(chemin))
        r = analyser_hooks(entrees)
        r.update(transcription=str(chemin), lignes=len(entrees), lignes_illisibles=illisibles)
        rapports.append(r)
        t = r["totaux"]
        print("== %s : %d hook(s), %d injection(s), %d caracteres, %d ligne(s) illisible(s)"
              % (Path(chemin).name, t["hooks"], t["injections"], t["caracteres"], illisibles))
        if not t["injections"]:
            print("   aucune injection de hook dans cette transcription")
            continue
        print("   identique a l'injection precedente du meme hook : %d/%d injection(s) (%.1f%%), "
              "%.1f%% des caracteres"
              % (t["injections_identiques"], t["avec_precedent"], 100.0 * t["part_injections_identiques"],
                 100.0 * t["part_caracteres_identiques"]))
        print("   %-46s %4s %9s %8s %9s %9s" % ("hook", "inj", "car", "=prec", "inj.id.%", "car.id.%"))
        for s in r["hooks"][: a.top]:
            print("   %-46s %4d %9d %8d %8.0f%% %8.0f%%" % (
                s["hook"][:46], s["injections"], s["caracteres"], s["injections_identiques"],
                100.0 * s["part_injections_identiques"], 100.0 * s["part_caracteres_identiques"]))
        if len(r["hooks"]) > a.top:
            print("   ... %d hook(s) de plus dans le rapport JSON" % (len(r["hooks"]) - a.top))
    if a.sortie:
        donnees = rapports[0] if len(rapports) == 1 else rapports
        Path(a.sortie).write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
        print("rapport : %s" % a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
