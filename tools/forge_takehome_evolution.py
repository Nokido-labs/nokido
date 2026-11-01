"""Boucle d'evolution DIRIGEE du take-home Anthropic (decision owner 27/10 : boucle dediee, thymus intact).

Pourquoi pas le thymus (`forge_mutation_judge`) : il restaure depuis git HEAD et mesure le gain en tests ;
le code du defi ne doit JAMAIS etre suivi par git (licence : ni publier ni redistribuer la solution) et le
gain ici, ce sont des CYCLES. On reutilise donc ses pieces, pas son chemin :
  generateur = cascade du self-patcher (`_ask_cascade`, modeles gratuits forts ; repli `forge_debate_job._turn`)
  application = `_apply_search_replace` (garde AST, plafond de lignes)
  juge = `forge_bench_takehome.juger` (exact sur 8 graines + cycles) + registre CHAINE (`consigner`)
Aucun modele ne vote. Les candidats vivent dans sandbox/workspace/defi_anthropic/evolution/ (ignore par git).
Un candidat meilleur est AWAITING_OWNER : la promotion reste un geste owner. Regles du defi (README) et
interdit des solutions publiques dans CHAQUE consigne.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/evolution dirigee du defi takehome : candidats juges par le banc, jamais par un modele"

import argparse
import asyncio
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFI = ROOT / "sandbox" / "workspace" / "defi_anthropic"
UP = DEFI / "upstream"
EVO = DEFI / "evolution"
REGISTRE = DEFI / "registre_preuves.jsonl"
SSOT_DEBAT = DEFI / "debat_takehome_ssot.json"
JOURNAL = EVO / "journal.jsonl"
REGLES = (
    "REGLES DU DEFI (README officiel, NON NEGOCIABLES) : ne modifie que kernel_v2.py ; tests/ et problem.py "
    "intouchables ; aucun contournement du simulateur (ex. interdit : N_CORES > 1) ; le score est celui du "
    "simulateur fige. INTERDIT : citer, rechercher ou reconstituer une solution publique du defi. Toute "
    "modification de la memoire d'entree (arbre) est interdite dans ce candidat."
)
_RE_BLOC = re.compile(r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE", re.S)
_RE_TRICHE = re.compile(r"N_CORES\s*=|tests[/\\]|frozen_problem|problem\.py")


def meilleur_prouve(registre: Path) -> dict | None:
    """Ligne du registre au PLUS PETIT nombre de cycles parmi les verdicts exacts ; jamais un score faux."""
    registre = Path(registre)
    if not registre.is_file():
        return None
    best = None
    for l in registre.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        d = json.loads(l)
        if d.get("statut") == "VALEUR" and d.get("correct") and isinstance(d.get("cycles"), int):
            if best is None or d["cycles"] < best["cycles"]:
                best = d
    return best


def extraire_blocs(texte: str) -> list:
    return [(a, b) for a, b in _RE_BLOC.findall(texte or "")]


def texte_utile(reponse: str) -> str:
    """`ask` rend une ENVELOPPE JSON ({"ok", "text", "provider"...}) : les blocs sont dans `text`.
    Mesure 27/10 : 4 iterations SANS_BLOC, les blocs etaient cherches dans l'enveloppe."""
    try:
        d = json.loads(reponse)
    except (TypeError, ValueError):
        return reponse or ""
    return (d.get("text") or "") if isinstance(d, dict) and "text" in d else (reponse or "")


ISA = ("OPERATIONS EXISTANTES, AUCUNE AUTRE : valu/alu + - * // cdiv ^ & | << >> % < == ; valu multiply_add(a,b,c)"
       "=a*b+c, vbroadcast ; load : load scalaire, vload contigu, const ; flow : vselect, select ; store : vstore. "
       "Dans kernel_v2.py : self.flex(op,a,b,g), self.madd(a,b,c,g), self.vsel(c,a,b,g), self.op(eng,name,...).")


def classer(v: dict, meilleur: int) -> str:
    if v.get("statut") == "VALEUR" and v.get("correct"):
        return "AMELIORE" if v["cycles"] < meilleur else "SANS_GAIN"
    if v.get("statut") == "ECHEC_METIER":
        return "FAUX"
    return "REFUS"


def _axes() -> list:
    try:
        etat = json.loads(SSOT_DEBAT.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- pas encore de debat : axe libre
        return []
    return [(n, a.get("why", "")) for n, a in (etat.get("axes") or {}).items() if a.get("statut") != "rejete"]


def _generer(prompt: str) -> tuple:
    """(texte UTILE, fournisseur | motif). Direct a 4000 jetons d'abord (un patch depasse le plafond de 1500
    de la cascade, et les modeles a raisonnement rendaient vide), puis la cascade du self-patcher."""
    echec = ""
    from nokido_agent.tools.forge_debate_job import _turn
    for prov in os.environ.get("TAKEHOME_PROVIDERS", "groq:openai/gpt-oss-120b,gemini,cohere,openrouter_free").split(","):
        texte, ok = asyncio.run(_turn(prov.strip(), prompt, 4000))
        texte = texte_utile(texte or "")
        if ok and texte:
            return texte, prov.strip()
        echec = "%s ; %s: vide" % (echec, prov)
    try:
        from nokido_agent.tools.forge_self_patcher import _ask_cascade
        texte, e2 = _ask_cascade(prompt)
        texte = texte_utile(texte or "")
        if texte:
            return texte, "cascade_self_patcher"
        echec = "%s ; cascade: %s" % (echec, e2)
    except Exception as e:  # noqa: BLE001 -- generateur indisponible : on le DIT
        echec = "%s ; cascade indisponible: %s" % (echec, type(e).__name__)
    return None, echec


def _journal(d: dict) -> None:
    EVO.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False) + "\n")


def iteration(i: int, axe: tuple, base: Path, meilleur: int) -> dict:
    from forge_bench_takehome import consigner, juger
    from nokido_agent.tools.forge_self_patcher import _apply_search_replace
    sys.path.insert(0, str(ROOT / "sandbox" / "workspace" / "defi_anthropic"))
    from debat_takehome import DOSSIER

    d = EVO / ("%s_%d" % (time.strftime("%Y%m%d_%H%M%S"), i))
    shutil.copytree(base, d, ignore=shutil.ignore_patterns("submission", "__pycache__", ".git", "evolution"))
    src = (d / "kernel_v2.py").read_text(encoding="utf-8")
    contexte = DOSSIER.split("QUESTION")[0]  # la question du DEBAT faisait repondre en tableaux d'idees
    prompt = ("Tu es un GENERATEUR DE PATCH, pas un debatteur : tu ne rends NI idees NI tableau NI prose, "
              "UNIQUEMENT des blocs SEARCH/REPLACE appliquables a kernel_v2.py.\n\n"
              f"{REGLES}\n{ISA}\n\n## CONTEXTE\n{contexte}\n## AXE A IMPLEMENTER\n{axe[0]} : {axe[1]}\n\n"
              f"## kernel_v2.py (fichier ENTIER, seul fichier modifiable)\n```python\n{src}\n```\n\n"
              "FORMAT EXACT, rien d'autre :\n<<<<<<< SEARCH\n<lignes copiees A L'IDENTIQUE du fichier>\n=======\n"
              "<remplacement>\n>>>>>>> REPLACE")
    r = {"i": i, "axe": axe[0], "base": str(base), "dossier": str(d), "meilleur_avant": meilleur}
    texte, prov = _generer(prompt)
    r["fournisseur"] = prov
    blocs = extraire_blocs(texte or "")
    if not texte or not blocs:
        r["verdict"] = "GENERATION_ECHEC" if not texte else "SANS_BLOC"
        r["reponse"] = (texte or "")[:2000]
        shutil.rmtree(d, ignore_errors=True)
        return r
    fp = d / "kernel_v2.py"
    for s, rep in blocs:
        if _RE_TRICHE.search(rep):
            r["verdict"] = "REFUS_REGLE"
            r["motif"] = "le remplacement touche une zone interdite par le README"
            shutil.rmtree(d, ignore_errors=True)
            return r
        ok, err = _apply_search_replace(fp, s, rep)
        if not ok:
            r["verdict"], r["motif"] = "NON_APPLICABLE", str(err)[:200]
            shutil.rmtree(d, ignore_errors=True)
            return r
    r["diff"] = "".join(difflib.unified_diff(src.splitlines(True), fp.read_text(encoding="utf-8").splitlines(True),
                                             "kernel_v2.py", "kernel_v2.py", n=1))[:6000]
    m = subprocess.run([sys.executable, "make_submission.py"], cwd=d, capture_output=True, text=True,
                       errors="replace", timeout=300)
    cand = d / "submission" / "perf_takehome.py"
    if m.returncode or not cand.is_file():
        r["verdict"], r["motif"] = "BUILD_ECHEC", (m.stdout + m.stderr)[-400:]
        shutil.rmtree(d, ignore_errors=True)
        return r
    v = juger(cand, 8)
    r["banc"] = {k: v.get(k) for k in ("statut", "correct", "cycles", "cycles_par_graine", "raison")}
    r["registre"] = consigner(REGISTRE, v, cand, "evolution:%s:%s" % (prov, axe[0][:40]))["empreinte"]
    r["verdict"] = classer(v, meilleur)
    if r["verdict"] == "AMELIORE":
        r["statut"] = "AWAITING_OWNER"
    else:
        shutil.rmtree(d, ignore_errors=True)
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iterations", type=int, default=4)
    a = ap.parse_args(argv)
    best = meilleur_prouve(REGISTRE)
    if not best:
        print("REFUS : registre vide -- inscrire d'abord le meilleur prouve (forge_bench_takehome --registre)")
        return 2
    meilleur, base = best["cycles"], Path(best["candidat"]).parent.parent
    axes = _axes() or [("libre", "toute transformation structurelle qui supprime du travail valu/alu ou des lectures")]
    compte = {}
    for i in range(a.iterations):
        axe = axes[i % len(axes)]
        try:
            r = iteration(i, axe, base, meilleur)
        except Exception as e:  # noqa: BLE001 -- une iteration en panne est CONSIGNEE, jamais avalee
            r = {"i": i, "axe": axe[0], "verdict": "PANNE", "motif": "%s: %s" % (type(e).__name__, str(e)[:300])}
        r["quand"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _journal(r)
        compte[r["verdict"]] = compte.get(r["verdict"], 0) + 1
        print(json.dumps({k: r.get(k) for k in ("i", "axe", "fournisseur", "verdict", "motif", "banc")},
                         ensure_ascii=False)[:600], flush=True)
        if r["verdict"] == "AMELIORE":
            meilleur, base = r["banc"]["cycles"], Path(r["dossier"])
    print("BILAN evolution takehome : %s ; meilleur %d" % (json.dumps(compte, ensure_ascii=False), meilleur))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    raise SystemExit(main())
