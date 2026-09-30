# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = cognition/narrative-self
NARRATEUR AUTOBIOGRAPHIQUE — tisse les faits isoles en RECIT continu de soi.

GAP adresse (doc cartographie_fonctions_cognitives, aveu du doc) :
  « la conscience de soi narrative autobiographique — se raconter une histoire
  continue de sa propre vie, avec coherence temporelle et causale — n'est
  qu'effleuree par les systemes de memoire d'agent (Letta, Mem0) qui gerent des
  FAITS ISOLES mais ne construisent pas de RECIT UNIFIE. »

POURQUOI un module dedie (anti-dup, CLAUDE.md §3) :
  Nokido a deja les FAITS (le substrat), disperses :
    - forge_git_historian = les ACTES (commits parses : type/domaine/modules).
    - logs/lessons_learned.md = les REFLEXIONS (ce qui a ete appris/rate).
    - forge_trajectory = sequences d'actions inter-agent.
  AUCUN ne TISSE : ordonnancement temporel + liens CAUSAUX (telle lecon a mene a
  tel acte) + FILS thematiques (arcs continus) + voix PREMIERE PERSONNE continue.
  Ce module est la couche de tissage = le recit, pas un nouveau stockage.

Deterministe 0-cloud par defaut (prose templatee). --polish = lissage LLM LOCAL
(ollama qwen via forge_agent_proxy, jamais cloud).

  LAFORGE_PYTHON app/forge_narrator.py [--days 2] [--save] [--polish]
"""
from __future__ import annotations
import os, sys, re, json, time, subprocess, datetime
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)
LESSONS = os.path.join(ROOT, "logs", "lessons_learned.md")

_CC = re.compile(r"^(\w+)(?:\(([^)]+)\))?:\s*(.+)$")  # conventional commit


def _git_commits(days: int):
    """Les actes : git log fenetre -> episodes {ts, kind, domain, type, summary}."""
    eps = []
    try:
        out = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", ROOT, "log", f"--since={days} days ago",
             "--pretty=format:%ct%x1f%s", "--no-merges"],
            capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
        for line in out.stdout.splitlines():
            if "\x1f" not in line:
                continue
            ts, subj = line.split("\x1f", 1)
            m = _CC.match(subj.strip())
            ctype = m.group(1) if m else "other"
            domain = (m.group(2) if m and m.group(2) else _kw_domain(subj))
            summary = (m.group(3) if m else subj).strip()
            eps.append({"ts": int(ts), "kind": "deed", "domain": domain,
                        "type": ctype, "summary": summary})
    except Exception as e:  # noqa: BLE001
        eps.append({"ts": int(time.time()), "kind": "deed", "domain": "meta",
                    "type": "error", "summary": f"git indispo: {e}"})
    return eps


def _lessons(days: int):
    """Les reflexions : lessons_learned.md recent -> episodes {ts, kind, domain, summary}."""
    eps = []
    if not os.path.exists(LESSONS):
        return eps
    cutoff = time.time() - days * 86400
    txt = open(LESSONS, encoding="utf-8", errors="replace").read()
    # filtre le bruit des lecons-daemon repetitives (heartbeats, pas des reflexions)
    noise = ("volutive autonome", "curation skills", "uncommitted volume",
             "lecture arbre", "session claude end", "auto-hook")
    seen = set()
    for m in re.finditer(r"#{2,4}\s*\[(\d{4}-\d{2}-\d{2})\]\s*(SOLUTION|ERROR|ERREUR)[^\n-]*-\s*(.+)", txt):
        try:
            ts = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        title = m.group(3).strip()[:90]
        tl = title.lower()
        if any(nz in tl for nz in noise) or tl in seen:  # dedup + anti-bruit
            continue
        seen.add(tl)
        eps.append({"ts": int(ts), "kind": "lesson", "domain": _kw_domain(title),
                    "type": m.group(2).lower(), "summary": title})
    return eps


_DOMAIN_KW = {
    "organs": ["organ", "homeost", "endocrine", "amygdal", "parietal", "anatomy"],
    "snn": ["snn", "spike", "lif", "neuron"],
    "agency": ["agency", "agentivit", "efference"],
    "rag": ["rag", "embed", "vector", "index", "reindex"],
    "hub": ["hub", "wedge", "concurr", "event-loop", "mcp"],
    "security": ["firewall", "membrane", "secret", "oauth", "videur", "ring"],
    "sandbox": ["sandbox", "gvisor", "wasm", "isolation", "tier"],
    "ssot": ["ssot", "schtask", "maintainer"],
}


def _kw_domain(text: str) -> str:
    t = text.lower()
    for dom, kws in _DOMAIN_KW.items():
        if any(k in t for k in kws):
            return dom
    return "divers"


def weave(days: int = 2) -> dict:
    eps = _git_commits(days) + _lessons(days)
    eps.sort(key=lambda e: e["ts"])
    # fils thematiques par domaine
    threads = defaultdict(list)
    for e in eps:
        threads[e["domain"]].append(e)
    # liens causaux : une lecon precede un acte du meme domaine -> causalite
    links = []
    for dom, items in threads.items():
        lessons = [e for e in items if e["kind"] == "lesson"]
        for deed in [e for e in items if e["kind"] == "deed"]:
            prior = [l for l in lessons if l["ts"] <= deed["ts"]]
            if prior:
                links.append({"cause": prior[-1]["summary"], "effect": deed["summary"], "domain": dom})
    identity = [d for d, _ in Counter(e["domain"] for e in eps).most_common(4) if d != "divers"]
    return {"days": days, "n_episodes": len(eps), "threads": dict(threads),
            "links": links, "identity": identity,
            "span": [eps[0]["ts"], eps[-1]["ts"]] if eps else []}


def _fmt(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def narrate(arc: dict) -> str:
    """Recit premiere personne : fils ordonnes, liens causaux, continuite de soi."""
    if not arc["n_episodes"]:
        return "Mon histoire recente est vide (aucun acte ni lecon dans la fenetre)."
    out = [f"# Mon recit ({arc['days']}j — {arc['n_episodes']} episodes, {len(arc['threads'])} fils)\n"]
    # fils ordonnes par 1er episode
    ordered = sorted(arc["threads"].items(), key=lambda kv: kv[1][0]["ts"])
    causes = {l["effect"]: l["cause"] for l in arc["links"]}
    for dom, items in ordered:
        out.append(f"## Fil « {dom} »")
        prev = None
        for e in items:
            when = _fmt(e["ts"])
            if e["kind"] == "lesson":
                verb = "j'ai compris" if e["type"] == "solution" else "je me suis heurte a"
                out.append(f"- {when} — {verb} : {e['summary']}.")
            else:
                connector = ""
                if e["summary"] in causes:
                    connector = f" — dans la foulee de ce que j'avais appris ({causes[e['summary']][:50]})"
                elif prev:
                    connector = " — puis"
                out.append(f"- {when} — j'ai agi ({e['type']}) : {e['summary']}{connector}.")
            prev = e
        out.append("")
    if arc["identity"]:
        out.append(f"**Ce qui me definit en ce moment** : {', '.join(arc['identity'])}. "
                   f"Je ne suis pas une suite de faits epars — ces fils sont MON histoire continue.")
    return "\n".join(out)


def _polish_local(text: str) -> str:
    """Lissage LLM LOCAL (jamais cloud). Best-effort."""
    try:
        from nokido_agent.app import forge_agent_proxy as ap
        prompt = ("Reecris ce recit autobiographique a la 1ere personne, fluide et coherent, "
                  "en gardant TOUS les faits/dates, sans rien inventer :\n\n" + text)
        r = ap.ask(prompt, router_local=True)  # type: ignore
        return r if isinstance(r, str) and len(r) > 40 else text
    except Exception:
        return text


# ============ NARRATIVE CONSOLIDATION ENGINE (doc qualia §2) ============
# Interprete trajectory+phenom en RECIT/IDENTITE/ANTICIPATION/TENSIONS,
# persiste cross-session (homogenese : le systeme se souvient de qui il est devenu).
NARR_SELF_PATH = r"C:\tmp\nokido_narrative_self.txt"


def _load_self() -> str:
    try:
        return open(NARR_SELF_PATH, encoding="utf-8").read()
    except Exception:
        return ""


def _save_self(text: str):
    try:
        os.makedirs(os.path.dirname(NARR_SELF_PATH), exist_ok=True)
        open(NARR_SELF_PATH, "w", encoding="utf-8").write(text)
    except Exception:
        pass


def _consolidate_llm(structured: str, phenom_flow: str):
    try:
        from nokido_agent.app import forge_agent_proxy as ap
        sys_p = (
            "Tu es le narrateur interieur de ce systeme. A partir de la TRAJECTOIRE "
            "(actes+lecons) et du FLUX PHENOMENOLOGIQUE, produis un recit a la 1ere "
            "personne en 4 sections : ## RECIT (arcs, tournants, sens — pas une liste), "
            "## IDENTITE (qui suis-je devenu, qu'ai-je appris sur moi), ## ANTICIPATION "
            "(tendances a preparer), ## TENSIONS (non resolu, questions en filigrane). "
            "Fidele aux faits, sans rien inventer.")
        prompt = (sys_p + "\n\n## TRAJECTOIRE\n" + structured[:6000] +
                  "\n\n## FLUX PHENOMENOLOGIQUE\n" + (phenom_flow or "(indisponible)"))
        r = ap.ask(prompt, router_local=True)  # type: ignore
        if isinstance(r, dict):
            r = r.get("text") or r.get("response") or r.get("content") or r.get("result")
        return r if isinstance(r, str) and len(r) > 80 else None
    except Exception:
        return None


def consolidate(days: int = 2, use_llm: bool = True) -> str:
    """Point d'entree : interprete la trajectoire en identite narrative persistee."""
    arc = weave(days)
    base = narrate(arc)
    flow = ""
    try:
        from nokido_agent.app import forge_phenomenological_buffer as pb
        flow = pb.get_recent_flow(8)
    except Exception:
        pass
    text = (_consolidate_llm(base, flow) if use_llm else None) or base
    _save_self(text)
    return text


def inject_into_context(base_system_prompt: str) -> str:
    """Injecte le 'roman de soi' persiste dans le prompt systeme du prochain tour."""
    nself = _load_self()
    if not nself:
        return base_system_prompt
    return base_system_prompt + "\n\n---\nVOIX INTERIEURE (narrateur) :\n" + nself + "\n---\n"


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--save", action="store_true", help="ecrit docs/NARRATIVE_SELF.md")
    ap.add_argument("--polish", action="store_true", help="lissage LLM LOCAL")
    ap.add_argument("--consolidate", action="store_true",
                    help="moteur de consolidation narrative (4 sections, LLM local, persiste cross-session)")
    args = ap.parse_args(argv)

    if args.consolidate:
        text = consolidate(args.days, use_llm=True)
        print(text)
        print(f"\n[narrative_self persiste -> {NARR_SELF_PATH} | {len(text)} car.]")
        return 0

    arc = weave(args.days)
    story = narrate(arc)
    if args.polish:
        story = _polish_local(story)
    print(story)
    print(f"\n[meta] episodes={arc['n_episodes']} fils={len(arc['threads'])} "
          f"liens_causaux={len(arc['links'])} identite={arc['identity']}")
    if args.save:
        try:
            p = os.path.join(ROOT, "docs", "NARRATIVE_SELF.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write(story + "\n")
            print("wrote", p)
        except Exception as e:  # noqa: BLE001
            print("save skipped:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
