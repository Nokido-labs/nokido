"""Juge du banc anthropics/original_performance_takehome (pilote du cycle conseil, GO owner 24/10).

Score = cycles du simulateur. Un LLM ne juge jamais ici : le classement par les pairs ne sert qu'a TRIER
les propositions avant mesure, et le pilote mesure justement s'il predit les cycles.

Garde anti reward-hacking (la triche documentee du banc : modifier tests/ ou le simulateur) :
  1. seul `perf_takehome.py` est repris du candidat ; problem.py et tests/ viennent du clone de reference,
     dont le sha256 est verifie contre l'empreinte figee a la baseline, AVANT et APRES l'execution du candidat ;
  2. le candidat tourne dans un processus JETABLE qui ne fait qu'une chose : construire le noyau et
     SERIALISER ses instructions en JSON (de la donnee, validee a la lecture) ;
  3. simulation et verification tournent dans un AUTRE processus qui n'importe jamais le candidat :
     patcher frozen_problem a l'import ne sert a rien.

Usage : forge_bench_takehome.py <perf_takehome.py candidat> [--graines 8] [--json sortie.json]
rc : 0 correct, 1 sortie fausse (ECHEC_METIER), 2 refus ou candidat illisible.
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/meta-evaluation"

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

N = Path(__file__).resolve().parents[1]
REF = N / "sandbox/workspace/bench/original_performance_takehome"
# Empreinte figee a la baseline du 24/10 (sha 5452f74bd du depot, 147 734 cycles mesures).
EMPREINTE = {
    "problem.py": "14041d538e4af84bb30ca68b728a883418e153266ebfba67fdef5501103f0e29",
    "tests/frozen_problem.py": "14041d538e4af84bb30ca68b728a883418e153266ebfba67fdef5501103f0e29",
    "tests/submission_tests.py": "8dc5f293dea0cd498a4c9f2ac7a6c5b1e6e24d9f65f795dd04eb3b527635547c",
}
BASELINE = 147734
MOTEURS = {"alu", "valu", "load", "store", "flow", "debug"}

_CONSTRUIRE = """import json, sys
sys.path.insert(0, ".")
from perf_takehome import KernelBuilder
kb = KernelBuilder()
kb.build_kernel(10, 2047, 256, 16)
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump([{k: [list(s) for s in v] for k, v in b.items()} for b in kb.instrs], f)
"""

_SIMULER = """import json, random, sys
sys.path.insert(0, sys.argv[1])
from frozen_problem import Machine, build_mem_image, reference_kernel2, Tree, Input, N_CORES, DebugInfo
with open(sys.argv[2], encoding="utf-8") as f:
    instrs = [{k: [tuple(s) for s in v] for k, v in b.items()} for b in json.load(f)]
res = []
for g in range(int(sys.argv[3])):
    random.seed(g)
    forest = Tree.generate(10)
    inp = Input.generate(forest, 256, 16)
    mem = build_mem_image(forest, inp)
    m = Machine(list(mem), instrs, DebugInfo(scratch_map={}), n_cores=N_CORES)
    m.enable_pause = False
    m.enable_debug = False
    m.run()
    # reference_kernel2 modifie `mem` SUR PLACE : l'entree se capture AVANT (NR du 24/10 : inchanges=0 sinon)
    ent = list(mem[mem[6]:mem[6] + 256])
    for ref in reference_kernel2(mem):
        pass
    p = ref[6]
    obt, att = m.mem[p:p + 256], ref[p:p + 256]
    faux = [i for i in range(256) if obt[i] != att[i]]
    ecart = None
    if faux:
        i = faux[0]
        ecart = {"faux": len(faux), "inchanges": sum(1 for j in faux if obt[j] == ent[j]),
                 "premier": {"indice": i, "attendu": att[i], "obtenu": obt[i], "entree": ent[i]}}
    q, fp, nn = ref[5], ref[4], ref[1]
    res.append({"graine": g, "ok": not faux, "cycles": m.cycle, "ecart": ecart,
                "indices_ok": m.mem[q:q + 256] == ref[q:q + 256], "arbre_ok": m.mem[fp:fp + nn] == ref[fp:fp + nn]})
print(json.dumps(res))
"""


def empreinte_ok() -> list[str]:
    """Fichiers de reference dont le sha256 a bouge (vide = intact)."""
    return [r for r, h in EMPREINTE.items()
            if not (REF / r).is_file() or hashlib.sha256((REF / r).read_bytes()).hexdigest() != h]


def _instrs_valides(brut) -> str | None:
    if not isinstance(brut, list) or not brut:
        return "programme vide ou non-liste"
    for i, b in enumerate(brut):
        if not isinstance(b, dict) or not set(b) <= MOTEURS:
            return f"bundle {i} : moteur inconnu {sorted(set(b) - MOTEURS) if isinstance(b, dict) else type(b)}"
        for moteur, slots in b.items():
            if moteur == "debug":
                # vcompare porte des cles imbriquees ; la simulation saute ces slots (enable_debug=False).
                # Les GARDER (pas les retirer) : un bundle ne doit pas changer de forme, le compte de cycles en depend.
                continue
            mauvais = next((s for s in (slots if isinstance(slots, list) else [slots])
                            if not isinstance(s, list) or not all(isinstance(x, (int, str)) for x in s)), None)
            if not isinstance(slots, list) or mauvais is not None:
                # nommer le slot fautif : sans lui un executant a stagne 7 tours sur ce refus (boucle du 24/10)
                return f"bundle {i} : slot non atomique (moteur {moteur}) : {repr(mauvais if mauvais is not None else slots)[:200]}"
    return None


def juger(candidat: Path, graines: int = 8) -> dict:
    r: dict = {"candidat": str(candidat), "graines": graines}
    bouge = empreinte_ok()
    if bouge:
        return {**r, "statut": "REFUS", "raison": f"reference alteree avant execution : {bouge}"}
    with tempfile.TemporaryDirectory(prefix="takehome_") as t:
        t = Path(t)
        shutil.copy2(candidat, t / "perf_takehome.py")
        shutil.copy2(REF / "problem.py", t / "problem.py")
        (t / "construire.py").write_text(_CONSTRUIRE, encoding="utf-8")
        sortie = t / "instrs.json"
        try:
            p = subprocess.run([sys.executable, "-E", "-s", "construire.py", str(sortie)], cwd=t,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", timeout=180)
        except subprocess.TimeoutExpired:
            return {**r, "statut": "ILLISIBLE", "raison": "construction > 180 s"}
        if p.returncode != 0 or not sortie.is_file():
            return {**r, "statut": "ILLISIBLE", "raison": "construction en echec", "sortie": p.stdout[-1500:]}
        bouge = empreinte_ok()
        if bouge:
            return {**r, "statut": "REFUS", "raison": f"reference alteree PAR le candidat : {bouge}"}
        try:
            brut = json.loads(sortie.read_text(encoding="utf-8"))
        except ValueError as e:
            return {**r, "statut": "ILLISIBLE", "raison": f"instructions illisibles : {e}"}
        err = _instrs_valides(brut)
        if err:
            return {**r, "statut": "REFUS", "raison": err}
        (t / "simuler.py").write_text(_SIMULER, encoding="utf-8")
        propre = t / "instrs_valides.json"
        propre.write_text(json.dumps(brut), encoding="utf-8")
        try:
            s = subprocess.run([sys.executable, "-E", "-s", str(t / "simuler.py"), str(REF / "tests"),
                                str(propre), str(graines)], cwd=REF / "tests", stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", timeout=900)
        except subprocess.TimeoutExpired:
            return {**r, "statut": "ILLISIBLE", "raison": "simulation > 900 s"}
        try:
            res = json.loads(s.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {**r, "statut": "ILLISIBLE", "raison": "simulation en echec", "sortie": s.stdout[-1500:]}
    cycles = max(x["cycles"] for x in res)
    ok = all(x["ok"] for x in res)
    # diagnostic de l'ecart (mesure, pas interpretation) : sans lui, un executant stagne (boucle du 24/10)
    ecart = next((x["ecart"] for x in res if x.get("ecart")), None)
    # contrat officiel = valeurs (tests/submission_tests.py) ; indices et arbre = contrat strict, MESURES a part
    return {**r, "statut": "VALEUR" if ok else "ECHEC_METIER", "correct": ok, "ecart": ecart,
            "graines_fausses": [x["graine"] for x in res if not x["ok"]],
            "cycles_par_graine": [x["cycles"] for x in res],
            "bornes": bornes(brut),
            "indices_exacts": all(x.get("indices_ok") for x in res),
            "arbre_intact": all(x.get("arbre_ok") for x in res),
            "cycles": cycles, "speedup": round(BASELINE / cycles, 2), "bundles": len(brut)}


def bornes(prog: list) -> dict:
    """Bornes de DEBIT d'un programme (porte 1, proposition owner 27/10) : un candidat dont la borne ne descend
    pas sous le meilleur score ne merite pas un reaccord de 3 700 essais. valu + alu/8 a 7,5/cycle, load a
    2/cycle, flow a 1/cycle ; les `pause` du flow ne comptent pas."""
    import math
    c = {}
    for b in prog:
        for e, slots in (b or {}).items():
            n = sum(1 for s in slots if not (e == "flow" and s and s[0] == "pause"))
            c[e] = c.get(e, 0) + n
    v, a, ld, fl = c.get("valu", 0), c.get("alu", 0), c.get("load", 0), c.get("flow", 0)
    r = {"valu": v, "alu": a, "load": ld, "flow": fl, "borne_calcul": math.ceil((v + a / 8) / 7.5),
         "borne_load": math.ceil(ld / 2), "borne_flow": fl}
    r["borne"] = max(r["borne_calcul"], r["borne_load"], r["borne_flow"])
    return r


def _canon(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def consigner(registre: Path, verdict: dict, candidat: Path, provenance: str) -> dict:
    """Ajoute un verdict au registre de preuves CHAINE (append-only, owner 27/10 : « l'observabilite
    pour prouver notre resolution »). Chaque ligne porte l'empreinte de la precedente : retoucher un
    score apres coup casse la chaine, ce que `verifier_registre` detecte."""
    import time
    registre = Path(registre)
    precedent = None
    if registre.is_file():
        lignes = [l for l in registre.read_text(encoding="utf-8").splitlines() if l.strip()]
        if lignes:
            precedent = json.loads(lignes[-1])["empreinte"]
    ligne = {"quand": time.strftime("%Y-%m-%dT%H:%M:%S"), "provenance": provenance, "candidat": str(candidat),
             "sha256_candidat": hashlib.sha256(Path(candidat).read_bytes()).hexdigest(),
             "reference": dict(EMPREINTE),
             **{k: verdict.get(k) for k in ("statut", "correct", "cycles", "cycles_par_graine",
                                             "indices_exacts", "arbre_intact", "graines", "raison")},
             "precedent": precedent}
    ligne["empreinte"] = hashlib.sha256(_canon(ligne).encode("utf-8")).hexdigest()
    registre.parent.mkdir(parents=True, exist_ok=True)
    with registre.open("a", encoding="utf-8") as f:
        f.write(_canon(ligne) + "\n")
    return ligne


def verifier_registre(registre: Path) -> dict:
    """Rejoue la chaine. `rupture` = index (base 0) de la premiere ligne dont l'empreinte ou le lien ment."""
    precedent = None
    lignes = [l for l in Path(registre).read_text(encoding="utf-8").splitlines() if l.strip()]
    for i, l in enumerate(lignes):
        d = json.loads(l)
        e = d.pop("empreinte", None)
        if d.get("precedent") != precedent or hashlib.sha256(_canon(d).encode("utf-8")).hexdigest() != e:
            return {"ok": False, "lignes": len(lignes), "rupture": i}
        precedent = e
    return {"ok": True, "lignes": len(lignes), "rupture": None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("candidat", type=Path, nargs="?")
    ap.add_argument("--graines", type=int, default=8)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--registre", type=Path, help="registre de preuves chaine (JSONL append-only)")
    ap.add_argument("--provenance", default="manuel", help="qui a produit le candidat (agent, tour, commit)")
    ap.add_argument("--verifier-registre", type=Path, help="rejoue la chaine d'un registre et sort")
    a = ap.parse_args(argv)
    if a.verifier_registre:
        r = verifier_registre(a.verifier_registre)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r["ok"] else 1
    if a.candidat is None:
        ap.error("candidat requis (sauf --verifier-registre)")
    v = juger(a.candidat, a.graines)
    if a.registre:
        v["registre"] = consigner(a.registre, v, a.candidat, a.provenance)["empreinte"]
    txt = json.dumps(v, ensure_ascii=False, indent=1)
    if a.json:
        a.json.write_text(txt, encoding="utf-8")
    print(txt)
    return {"VALEUR": 0, "ECHEC_METIER": 1}.get(v["statut"], 2)


if __name__ == "__main__":
    sys.exit(main())
