"""Audit des gardes d'economie de tokens : reglages lus dans le code, refus et suites mesures dans les transcriptions.

Aucun contenu de transcription n'est rendu : seulement des comptes. Une suite de refus est une HEURISTIQUE, dite comme telle.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
TRANSCRIPTIONS = Path("%USERPROFILE%/.claude/projects/C--Users-user-Script-python-IA")
ETAT_BUDGET = Path("%USERPROFILE%/.claude/runtime/tool_budget")
N_SESSIONS = 20

CONSTANTE = re.compile(r"^(_?[A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*(.+)$")
INTERET = re.compile(r"SEUIL|SOFT|HARD|WINDOW|PLAFOND|LIMIT|MAX_|BUDGET|TOLERES|^_?MODE$|TTL|QUEUE|TOUR|BURST")
SITES = ["tools/forge_recon_breaker.py", "tools/hook_search_guard.py", "tools/hook_context_firewall.py",
         "tools/hook_tool_budget_gate.py", "tools/hook_bash_compact.py", "tools/forge_cmd_compactor.py",
         "tools/hook_capability_gate.py", "tools/hook_recon_first.py", "tools/forge_tool_gate.py",
         "tools/forge_job_watch_cli.py", "tools/hook_stop_attente_passive.py", "app/forge_token_watchdog.py",
         "app/forge_token_monitor.py", "tools/forge_token_watchdog.py", "app/forge_prompt_cache.py",
         "app/forge_tool_scope.py"]
REFUS = {
    "bash_guard": "[bash_guard] BLOCKED", "recon_breaker": "recon lourde d", "search_guard": "[search-guard] BLOQUE",
    "recon_first": "[recon_first] STOP", "budget_volume": "BUDGET_VOLUME", "retry_loop": "RETRY_LOOP",
    "repeat_call": "REPEAT_TOOL_CALL", "classifieur": "auto mode classifier gave no verdict",
}
CONSEILS = {
    "tool_gate_deport": "[forge-tool-gate]", "impulsion": "[impulsion]", "compact_pre": "[compact:",
    "context_firewall": "[context-firewall]", "capability_gate": "[capability-gate]",
}
GIT_LECTURE = re.compile(r"(?:^|\s)(?:show|grep|blame|cat-file)(?:\s|$)|(?:^|\s)log\s(?:.*\s)?-p(?:\s|$)")
LIT_UN_FICHIER = re.compile(r"\bopen\(|read_text|Get-Content|\btype\s|\bcat\s|\bsed\s|\bhead\s")


def inventaire():
    for rel in SITES:
        f = RACINE / rel
        if not f.exists():
            print("ABSENT %s" % rel)
            continue
        vus = []
        for ligne in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = CONSTANTE.match(ligne)
            if m and INTERET.search(m.group(1)) and len(m.group(2)) < 90:
                vus.append("%s=%s" % (m.group(1), m.group(2).strip()))
        print("%s : %s" % (rel, " ; ".join(vus[:9]) or "aucune constante de seuil"))
    hooks = sorted(p.name for p in (RACINE / "tools").glob("hook_*.py"))
    print("hooks du depot (%d) : %s" % (len(hooks), " ".join(h[5:-3] for h in hooks)))


def filtres_compacteur():
    sys.path.insert(0, str(RACINE / "tools"))
    try:
        import forge_cmd_compactor as cc
        filtres = cc.load_filters()
        print("filtres compacteur (%d) : %s" % (len(filtres), " ".join(
            "%s(max %s)" % (n, r.get("max_lines", "-")) for n, r in sorted(filtres.items()))))
    except Exception as exc:  # noqa: BLE001 - ILLISIBLE dit, jamais vide
        print("filtres compacteur ILLISIBLES : %s" % type(exc).__name__)


def etat_budget():
    if not ETAT_BUDGET.exists():
        print("etat budget ILLISIBLE ou absent : %s" % ETAT_BUDGET)
        return
    for f in sorted(ETAT_BUDGET.iterdir()):
        try:
            print("etat budget %s : %d o" % (f.name, f.stat().st_size))
        except OSError as exc:
            print("etat budget %s ILLISIBLE : %s" % (f.name, type(exc).__name__))


def _texte(bloc):
    return json.dumps(bloc.get("content"), ensure_ascii=False)


def analyser_session(chemin, cumul):
    outils, attente = {}, None
    for ligne in chemin.open(encoding="utf-8", errors="replace"):
        try:
            e = json.loads(ligne)
        except ValueError:
            cumul["lignes_illisibles"] += 1
            continue
        if e.get("type") == "attachment":
            t = json.dumps(e.get("attachment"), ensure_ascii=False)
            for nom, sig in CONSEILS.items():
                cumul["conseil:" + nom] += t.count(sig) if sig in t else 0
            for nom, sig in REFUS.items():
                cumul["refus:" + nom] += 1 if sig in t else 0
            continue
        contenu = (e.get("message") or {}).get("content")
        for b in contenu if isinstance(contenu, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                nom, entree = str(b.get("name")), b.get("input") or {}
                court = nom.rsplit("__", 1)[-1]
                outils[b.get("id")] = court
                cumul["appels"] += 1
                commande = str(entree.get("command") or "")
                code = str(entree.get("code") or "")
                if court == "Bash" and re.search(r"\bgit\b", commande) and GIT_LECTURE.search(commande):
                    cumul["bash:git_lecture"] += 1
                if court == "Bash" and re.search(r"\bgit\b.*\s>\s", commande):
                    cumul["bash:git_vers_fichier"] += 1
                if court == "run" and entree.get("action") in ("python", "shell"):
                    cumul["run:python_shell"] += 1
                    if LIT_UN_FICHIER.search(code):
                        cumul["run:lit_un_fichier"] += 1
                if court == "run" and entree.get("action") == "run_job":
                    cumul["run:run_job"] += 1
                if court in ("forge_deep_explore", "read_function_body", "get_file_skeleton", "introspect"):
                    cumul["voie_gouvernee:" + court] += 1
                if attente and court in ("Bash", "run", "Agent", "forge_deep_explore"):
                    voie = "deport" if court == "forge_deep_explore" else court
                    cumul["apres_refus_recon:" + voie] += 1
                    attente = None
            elif b.get("type") == "tool_result":
                t = _texte(b)
                for nom, sig in REFUS.items():
                    if sig in t and len(t) < 3000:
                        cumul["refus:" + nom] += 1
                        if nom == "recon_breaker":
                            attente = True


def transcriptions():
    fichiers = sorted(TRANSCRIPTIONS.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)[-N_SESSIONS:]
    cumul = collections.Counter()
    for f in fichiers:
        analyser_session(f, cumul)
    print("transcriptions lues : %d" % len(fichiers))
    for cle, n in sorted(cumul.items()):
        print("  %-40s %d" % (cle, n))


def main():
    inventaire()
    filtres_compacteur()
    etat_budget()
    transcriptions()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
