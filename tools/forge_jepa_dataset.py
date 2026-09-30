#!/usr/bin/env python3
"""
forge_jepa_dataset.py — Construit un dataset contrastif SANITIZÉ depuis
execution_traces.db pour fine-tuner BGE-M3 (LoRA) hors-site (Colab/Kaggle).

Décision 2026-06-01 : data maigre (2826 utiles / 15980, 10 clusters dont bcp
synthétique) → fine-tune = EXPÉRIENCE (gain probable marginal). Ce builder
filtre le bruit + construit des paires (anchor, positive) pour
MultipleNegativesRankingLoss + sanitize CHAQUE texte AVANT egress.

Anti-dup : sanitize via `SovereignMembrane` (alias HMAC déterministes — paths,
users Windows, tokens, IPs, UUIDs ; cf CLAUDE.md §5). PAS de re-build DLP.

Pipeline :
1. extract  : traces non-bruit (drop tick/replay/heartbeat), texte par trace.
2. cluster  : group par (task_type, action_type).
3. pairs    : (anchor, positive) intra-cluster (succès) ; + triplets avec
              négatif = échec même task_type (hard negative) si dispo.
4. sanitize : membrane.wrap() sur chaque texte (anonymisation déterministe).
5. write    : sandbox/jepa_dataset/pairs.jsonl + manifest.json + report.

⚠️ EGRESS : le JSONL est destiné à un upload cloud (Colab/Kaggle). NE l'uploader
QUE après vérif du report de sanitization (0 secret/path résiduel).

Usage : python tools/forge_jepa_dataset.py [--max-per-cluster 200] [--min-cluster 2]
                                            [--no-sanitize (debug local only)]

SOURCE `--source oplog` (2026-09-27, chantier LoRA retrieval) : triplets RETRIEVAL
(symptome -> carte du fichier qui l'a corrige -> carte d'un fichier voisin non touche)
depuis sandbox/success_oplog.jsonl, pour un reranker / un encodeur de requete. Mesure
du jour : query_log n'a AUCUN positif (selected_chunk_id vide), les 894 paires du
journal des succes sont le seul signal de pertinence propre a Nokido. Split TEMPOREL
(les plus recentes en held-out). Sorties : oplog_train.jsonl, oplog_heldout.jsonl,
manifest_oplog.json -- pairs.jsonl (traces) n'est pas touche. Destine a un
entrainement LOCAL (env laforge_py314) : aucun egress.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `build_oplog` — Triplets (symptome, fichier du correctif, fichier voisin non touche) depuis success_oplog.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TRACES_DB = ROOT / "RAG" / "execution_traces.db"
OUT_DIR = ROOT / "sandbox" / "jepa_dataset"
OPLOG = ROOT / "sandbox" / "success_oplog.jsonl"
SUFFIXES_CARTE = (".py", ".md", ".ts", ".toml", ".ps1", ".yml", ".yaml")
CARTE_MAX = 1500

NOISE_TOKENS = ("tick", "replay", "heartbeat")


def _is_noise(task: str, action: str) -> bool:
    blob = f"{task} {action}".lower()
    return any(tok in blob for tok in NOISE_TOKENS)


def _trace_text(task: str, action: str, action_json: str) -> str:
    """Représentation textuelle de l'état/transition pour l'encodeur."""
    state = ""
    try:
        d = json.loads(action_json or "{}")
        state = str(d.get("state_text") or d.get("desc") or d.get("prompt") or "")
        if not state:
            params = {k: v for k, v in d.items() if k not in ("type", "state_text", "desc")}
            if params:
                state = json.dumps(params, ensure_ascii=False)[:400]
    except Exception:
        pass
    return f"[task:{task}] [action:{action}] {state}".strip()[:512]


def _get_membrane():
    try:
        from nokido_agent.app.forge_sovereign_membrane import SovereignMembrane
        return SovereignMembrane(mission_id="jepa_dataset_2026")
    except Exception as e:
        print(f"[jepa-ds] WARN membrane indisponible ({e}) — sanitize fallback regex.", flush=True)
        return None


def _fallback_sanitize(text: str) -> str:
    import re
    text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<PATH>", text)
    text = re.sub(r"/(?:home|Users|mnt)/[^\s\"']+", "<PATH>", text)
    text = re.sub(r"\b[\w.-]+@[\w.-]+\.\w+\b", "<EMAIL>", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<IP>", text)
    text = re.sub(r"\b[A-Fa-f0-9]{32,}\b", "<HASH>", text)
    return text


class _Sanitizer:
    """Passe chaque texte par SovereignMembrane (repli regex) et compte les redactions."""

    def __init__(self, sanitize: bool):
        self.sanitize = sanitize
        self.membrane = _get_membrane() if sanitize else None
        self.redactions = 0

    def __call__(self, t: str) -> str:
        if not self.sanitize:
            return t
        if self.membrane is not None:
            try:
                w = self.membrane.wrap(t)
                out = w.content if hasattr(w, "content") else str(w)
            except Exception:
                out = _fallback_sanitize(t)
        else:
            out = _fallback_sanitize(t)
        if out != t:
            self.redactions += 1
        return out


def build(max_per_cluster: int, min_cluster: int, sanitize: bool) -> dict:
    if not TRACES_DB.exists():
        print(f"[jepa-ds] ERREUR: {TRACES_DB} introuvable (V: monté ?).", flush=True)
        return {}
    conn = sqlite3.connect(f"file:{TRACES_DB}?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT task_type, action_json, success FROM traces WHERE action_json IS NOT NULL"
    ).fetchall()
    conn.close()

    clusters: dict[tuple, list] = defaultdict(list)   # (task,action) -> [text] (succès)
    fails: dict[str, list] = defaultdict(list)        # task -> [text] (échecs, hard-neg)
    kept = 0
    for r in rows:
        task = str(r["task_type"] or "unknown")
        try:
            action = str(json.loads(r["action_json"] or "{}").get("type", "?"))
        except Exception:
            action = "?"
        if _is_noise(task, action):
            continue
        text = _trace_text(task, action, r["action_json"])
        if len(text) < 12:
            continue
        kept += 1
        if r["success"]:
            clusters[(task, action)].append(text)
        else:
            fails[task].append(text)

    san = _Sanitizer(sanitize)

    pairs = []
    triplets = 0
    for (task, action), texts in clusters.items():
        uniq = list(dict.fromkeys(texts))  # dedup
        if len(uniq) < min_cluster:
            continue
        uniq = uniq[:max_per_cluster]
        neg_pool = fails.get(task, [])
        for i in range(len(uniq) - 1):
            rec = {"anchor": san(uniq[i]), "positive": san(uniq[i + 1])}
            if neg_pool:
                rec["negative"] = san(neg_pool[i % len(neg_pool)])
                triplets += 1
            pairs.append(rec)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jsonl = OUT_DIR / "pairs.jsonl"
    with open(jsonl, "w", encoding="utf-8") as f:
        for rec in pairs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    manifest = {
        "total_traces": len(rows),
        "kept_non_noise": kept,
        "clusters_used": sum(1 for v in clusters.values() if len(set(v)) >= min_cluster),
        "pairs": len(pairs),
        "with_hard_negative": triplets,
        "sanitized": sanitize,
        "redactions_applied": san.redactions,
        "max_per_cluster": max_per_cluster,
        "min_cluster": min_cluster,
        "output": str(jsonl),
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def _carte_fichier(root: Path, rel: str) -> str | None:
    """Passage qui represente un fichier : chemin + docstring de module + noms definis (.py),
    debut du texte sinon.

    Borne a CARTE_MAX caracteres : c'est un PASSAGE de reranker (~512 tokens), pas le fichier.
    None si le fichier n'existe plus ou n'est pas d'un type retenu (le manifest compte les deux).
    """
    p = root / rel
    if p.suffix.lower() not in SUFFIXES_CARTE or not p.is_file():
        return None
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    corps = src
    if p.suffix.lower() == ".py":
        try:
            arbre = ast.parse(src)
            noms = [n.name for n in arbre.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
            corps = (ast.get_docstring(arbre) or "") + ("\nDEFINIT : " + ", ".join(noms[:40]) if noms else "")
        except SyntaxError:  # muet-ok : repli VOULU, la carte garde le debut du texte brut
            pass
    return (rel.replace("\\", "/") + "\n" + corps)[:CARTE_MAX]


def _jetons(entree: dict) -> set:
    j = entree.get("jetons")
    if isinstance(j, list) and j:
        return {str(x).lower() for x in j}
    return set(re.findall(r"\w{4,}", str(entree.get("symptome", "")).lower()))


def build_oplog(oplog: Path = OPLOG, root: Path = ROOT, out_dir: Path = OUT_DIR,
                sanitize: bool = True, holdout_frac: float = 0.15, max_fichiers: int = 3,
                carrefour_frac: float = 0.05, carrefour_min: int = 10) -> dict:
    """Triplets (symptome, fichier du correctif, fichier voisin non touche) depuis success_oplog.

    Requete = le symptome tel que l'agent l'a nomme ; positif = carte d'un fichier du correctif ;
    negatif DUR = carte d'un fichier d'une AUTRE entree au vocabulaire le plus proche, disjointe
    des fichiers du correctif. Une entree INFIRME n'est jamais un positif : un correctif refute
    ne prouve pas la pertinence (elle est comptee, pas utilisee).
    Split TEMPOREL : les `holdout_frac` entrees les plus recentes forment le held-out ; les
    negatifs du train ne sont tires QUE du train (aucun document du held-out n'y entre).
    FICHIER CARREFOUR : touche par plus de `carrefour_frac` des entrees (et au moins
    `carrefour_min` fois) -- il accompagne le correctif sans en etre la cause. Mesure du
    2026-09-27 : tools/ci_local.py, ou chaque NR s'inscrit, faisait 12,3 % des positifs du
    train ; garde, il devient un positif universel. Retire des positifs et NOMME au manifest.
    Tout ce qui est ecarte est COMPTE dans le manifest, jamais tu.
    """
    if not oplog.exists():
        print(f"[jepa-ds] ERREUR: {oplog} introuvable.", flush=True)
        return {}
    ecarts: dict[str, int] = defaultdict(int)
    entrees = []
    lues = 0
    with open(oplog, encoding="utf-8", errors="replace") as f:
        for ligne in f:
            if not ligne.strip():
                continue
            lues += 1
            try:
                e = json.loads(ligne)
            except ValueError:
                ecarts["ligne_illisible"] += 1
                continue
            proc = e.get("procedure") if isinstance(e.get("procedure"), dict) else {}
            fichiers = [x for x in (proc.get("fichiers") or []) if isinstance(x, str)]
            if not str(e.get("symptome") or "").strip():
                ecarts["sans_symptome"] += 1
            elif not fichiers:
                ecarts["sans_fichiers"] += 1
            elif e.get("etat") == "INFIRME":
                ecarts["infirme_jamais_positif"] += 1
            else:
                entrees.append((e, fichiers))

    cartes: dict[str, str | None] = {}

    def carte(rel: str) -> str | None:
        if rel not in cartes:
            cartes[rel] = _carte_fichier(root, rel)
        return cartes[rel]

    avec_vivants = []
    for e, fichiers in entrees:
        vivants = [x for x in fichiers if carte(x)]
        ecarts["fichiers_sans_carte"] += len(fichiers) - len(vivants)
        if not vivants:
            ecarts["entree_sans_fichier_vivant"] += 1
            continue
        avec_vivants.append((e, vivants))
    freq = Counter(x for _e, v in avec_vivants for x in set(v))
    seuil = carrefour_frac * len(avec_vivants)
    carrefours = {x: n for x, n in freq.items() if n > seuil and n >= carrefour_min}
    utiles = []
    for e, vivants in avec_vivants:
        propres = [x for x in vivants if x not in carrefours]
        if len(propres) < len(vivants):
            ecarts["fichiers_carrefour_retires"] += len(vivants) - len(propres)
        if not propres:
            ecarts["entree_seulement_carrefour"] += 1
            continue
        if len(propres) > max_fichiers:
            ecarts["fichiers_au_dela_de_max"] += len(propres) - max_fichiers
        utiles.append((e, propres[:max_fichiers], _jetons(e)))
    utiles.sort(key=lambda t: str(t[0].get("date") or ""))
    coupe = len(utiles) - int(round(len(utiles) * holdout_frac))

    san = _Sanitizer(sanitize)
    recs: dict[str, list] = {"train": [], "heldout": []}
    vus = set()
    sans_negatif = 0
    for i, (e, vivants, jet) in enumerate(utiles):
        split = "train" if i < coupe else "heldout"
        pool = range(coupe) if split == "train" else range(len(utiles))
        meilleur, score = None, -1.0
        for j in pool:
            if j == i or set(vivants).intersection(utiles[j][1]):
                continue
            jet2 = utiles[j][2]
            s = len(jet & jet2) / (len(jet | jet2) or 1)
            if s > score:
                meilleur, score = utiles[j][1][0], s
        for rel in vivants:
            cle = (str(e["symptome"]).strip().lower(), rel)
            if cle in vus:
                ecarts["doublon_symptome_fichier"] += 1
                continue
            vus.add(cle)
            rec = {"anchor": san(str(e["symptome"])), "positive": san(carte(rel)),
                   "commit": e.get("commit"), "date": e.get("date"), "etat": e.get("etat")}
            if meilleur:
                rec["negative"] = san(carte(meilleur))
            else:
                sans_negatif += 1
            recs[split].append(rec)

    out_dir.mkdir(parents=True, exist_ok=True)
    for split, lignes in recs.items():
        with open(out_dir / f"oplog_{split}.jsonl", "w", encoding="utf-8") as f:
            for rec in lignes:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    manifest = {
        "source": str(oplog),
        "entrees_lues": lues,
        "entrees_retenues": len(utiles),
        "ecartees": dict(ecarts),
        "fichiers_carrefour": dict(sorted(carrefours.items(), key=lambda kv: -kv[1])),
        "train": len(recs["train"]),
        "heldout": len(recs["heldout"]),
        "heldout_depuis": str(utiles[coupe][0].get("date")) if coupe < len(utiles) else None,
        "sans_negatif": sans_negatif,
        "fichiers_distincts_avec_carte": sum(1 for v in cartes.values() if v),
        "carte_max_caracteres": CARTE_MAX,
        "sanitized": sanitize,
        "redactions_applied": san.redactions,
        "sorties": [str(out_dir / "oplog_train.jsonl"), str(out_dir / "oplog_heldout.jsonl")],
    }
    (out_dir / "manifest_oplog.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                                 encoding="utf-8")
    return manifest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Dataset contrastif sanitizé pour fine-tune BGE-M3.")
    p.add_argument("--max-per-cluster", type=int, default=200)
    p.add_argument("--min-cluster", type=int, default=2)
    p.add_argument("--no-sanitize", action="store_true", help="DEBUG local — ne PAS uploader la sortie")
    p.add_argument("--source", choices=("traces", "oplog"), default="traces",
                   help="traces = paires JEPA (defaut, inchange) ; oplog = triplets retrieval du journal des succes")
    p.add_argument("--oplog", default=str(OPLOG))
    p.add_argument("--root", default=str(ROOT), help="racine ou lire les fichiers cites par l'oplog")
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--holdout-frac", type=float, default=0.15)
    args = p.parse_args(argv)

    if args.source == "oplog":
        m = build_oplog(Path(args.oplog), Path(args.root), Path(args.out_dir),
                        sanitize=not args.no_sanitize, holdout_frac=args.holdout_frac)
        if not m:
            return 1
        print("=== OPLOG RETRIEVAL DATASET ===")
        for k, v in m.items():
            print(f"  {k:<30} {v}")
        return 0

    m = build(args.max_per_cluster, args.min_cluster, sanitize=not args.no_sanitize)
    if not m:
        return 1
    print("=== JEPA DATASET ===")
    for k, v in m.items():
        print(f"  {k:<20} {v}")
    if not args.no_sanitize and m.get("redactions_applied", 0) == 0:
        print("  NOTE: 0 redaction — vérifier manuellement pairs.jsonl avant upload (peut être propre, ou sanitize off).")
    print("\nVérifier le report ci-dessus PUIS uploader sandbox/jepa_dataset/pairs.jsonl sur Colab/Kaggle.")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
