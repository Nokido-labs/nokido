#!/usr/bin/env python3
"""forge_grounder.py — verbe ground(claim|task) : grounding QUALIFIE multi-source + verification
ADVERSARIALE multi-LLM. Generalise la boucle manuelle (rag -> read -> panel -> refute) en
capability souveraine reutilisable (cowork P3, swarm, self-ground avant action = anti-halluc).

Compose : forge_self_correction.preflight_check (preuves RAG) + panel `ask` free-tier (refutation)
+ agregation -> verdict{verdict, confidence, sources, dissent}. Travail = pur I/O (lecture RAG +
HTTP LLM) -> async/threade ideal, 0 ecriture mono-writer.

P1 (ce fichier) : gather RAG + N refuteurs free-tier + agregation. Modes --selftest / --claim "<x>".
RESTE P2 : routage par KIND vers endpoints qualifies (cascade_oracle/route_task) + rag_truth + read code.
"""
from __future__ import annotations

__FORGE_COLOR__ = "cognition/judge : grounding multi-source et verification adversariale multi-LLM"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import glob
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from nokido_agent.app.forge_secrets import get_secret

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HUB = "http://127.0.0.1:8766"
DEFAULT_REFUTERS = ["groq", "cerebras"]  # free-tier souverains eprouves


def _token() -> str:
    """Jeton de l'identite annoncee (X-Agent-Name: GROUNDER) -- 2b-6, 2026-09-28.

    Avant : le jeton MAITRE lu en direct au coffre machine (hors guichet, hors coffre
    reserve), puis au guichet. `jeton_hub` rend le jeton PROPRE de GROUNDER, sinon le
    maitre en transition dite et comptee."""
    try:
        from nokido_agent.app.forge_agent_credential import jeton_hub

        return jeton_hub("GROUNDER") or ""
    except Exception:  # noqa: BLE001 -- sans jeton, l'appel au hub rendra 401 et le dira
        return ""


def _ask(provider: str, message: str, max_tokens: int = 400) -> str:
    """Appel LLM via le hub /mcp (tool 'ask'). Auth Bearer FORGE_MCP_TOKEN si present.
    FIREWALL pre_flight avant egress cloud (Golden Rule #4 : claim+preuves peuvent contenir du sensible)."""
    try:
        from nokido_agent.app.forge_semantic_firewall import get_firewall

        pf = get_firewall().pre_flight(message, context="", ring=2, provider=provider)
        if not pf.ok:
            return '{"refuted": true, "confidence": 0.3, "reason": "firewall veto egress cloud"}'
        message = getattr(pf, "safe_task", None) or message
    except Exception:
        pass
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "ask", "arguments": {"provider": provider, "message": message, "max_tokens": max_tokens}},
    }).encode()
    headers = {"Content-Type": "application/json", "X-Agent-Name": "GROUNDER"}
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(HUB + "/mcp", data=body, headers=headers, method="POST")
    r = json.loads(urllib.request.urlopen(req, timeout=60).read())
    txt = r.get("result", {}).get("content", [{}])[0].get("text", "{}")
    try:
        return json.loads(txt).get("text", txt)
    except Exception:
        return txt


_STOP = {"utilise", "avec", "pour", "dans", "that", "with", "uses", "normalise", "fusion",
         "and", "the", "une", "des", "les", "est", "plus", "from", "this", "code"}


def _classify_kind(claim: str, kind: str | None = None) -> str:
    """Qualifie le grounding (P2) : 'code' si le claim reference un module/symbole, sinon 'doc'."""
    if kind:
        return kind
    if re.search(r"forge_\w+|\b\w+\.py\b|IndexFlat|\bRRF\b|\bBM25\b|\bFAISS\b|\bdef \w+|\bclass [A-Z]", claim):
        return "code"
    return "doc"


def _gather_code(claim: str, limit: int = 5) -> list[dict]:
    """Preuves = LIGNES du MODULE REEL reference (P2). Un code-fact se verifie dans le code,
    pas dans des solutions de session. Grep les lignes du module matchant les mots-cles du claim."""
    mods = set(re.findall(r"forge_\w+", claim))
    files: list[str] = []
    for m in mods:
        files += glob.glob(str(ROOT / "app" / f"{m}.py")) + glob.glob(str(ROOT / "tools" / f"{m}.py"))
    kws = [w for w in re.findall(r"[A-Za-z_]{4,}", claim) if w.lower() not in _STOP and not w.startswith("forge_")]
    kl = [k.lower() for k in kws]
    scored: list = []
    for f in files[:3]:
        try:
            src = open(f, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        base = os.path.basename(f)
        try:  # P3 : AST -> def/class dont le nom matche un mot-cle = preuve DEFINITIONNELLE (boost 10)
            for node in ast.walk(ast.parse(src)):
                nm = getattr(node, "name", None)
                if nm and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                        and any(k in nm.lower() for k in kl):
                    doc = (ast.get_docstring(node) or "").splitlines()
                    kind = "class" if isinstance(node, ast.ClassDef) else "def"
                    scored.append((10, {"source": f"{base}:{node.lineno}", "score": "code:" + kind,
                                        "preview": f"{kind} {nm}: {doc[0] if doc else ''}"[:200]}))
        except Exception:
            pass
        for i, line in enumerate(src.splitlines(), 1):  # grep ranked (nb mots-cles)
            hits = sum(1 for kw in kws if kw in line)
            if hits:
                scored.append((hits, {"source": f"{base}:{i}", "score": "code", "preview": line.strip()[:200]}))
    scored.sort(key=lambda t: -t[0])  # def/class (10) puis lignes specifiques > generiques
    seen, out = set(), []
    for _, s in scored:
        if s["source"] in seen:
            continue
        seen.add(s["source"])
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _gather_rag(claim: str, limit: int = 5) -> list[dict]:
    """Preuves RAG via preflight_check (best-effort)."""
    srcs: list[dict] = []
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        v = preflight_check_verbose(claim, "")
        for x in (v.get("results") or [])[:limit]:
            srcs.append({"source": x.get("source"), "score": x.get("score"),
                         "preview": (x.get("preview") or "")[:200]})
    except Exception:
        pass
    return srcs


def _gather(claim: str, kind: str | None = None, limit: int = 5) -> list[dict]:
    """Route les preuves par KIND (P2) : code -> read le module reel (fallback RAG si introuvable) ; sinon RAG."""
    if _classify_kind(claim, kind) == "code":
        ev = _gather_code(claim, limit)
        if ev:
            return ev
    return _gather_rag(claim, limit)


def _refute(claim: str, evidence: list[dict], provider: str, ask=None) -> dict:
    """1 LLM tente de REFUTER le claim au vu des preuves -> {refuted, confidence, reason}."""
    ev = "\n".join(f"- [{s.get('score')}] {s.get('source')}: {s.get('preview')}" for s in evidence) or "(no RAG evidence)"
    prompt = (f"CLAIM: {claim}\n\nEVIDENCE (Nokido RAG):\n{ev}\n\n"
              "You are an ADVERSARIAL verifier. TRY TO REFUTE the claim. Default refuted=true if "
              "uncertain or unsupported by evidence. Respond ONLY JSON: "
              '{"refuted": bool, "confidence": 0.0-1.0, "reason": "short"}.')
    fn = ask or _ask
    raw = fn(provider, prompt)
    # P3 : regex-extract refuted+confidence — robuste a TOUT format (JSON/prose/nested/fences/reasoning cerebras)
    mr = re.search(r'"?refuted"?\s*[:=]\s*\*{0,2}\s*(true|false|yes|no|oui|non)', raw, re.I)
    if mr:
        refuted = mr.group(1).lower() in ("true", "yes", "oui")
        mc = re.search(r'"?confidence"?\s*[:=]\s*([01](?:\.\d+)?)', raw, re.I)
        mreason = re.search(r'"?reason"?\s*[:=]\s*"?([^"\n}]{3,})', raw, re.I)
        return {"provider": provider, "refuted": refuted,
                "confidence": float(mc.group(1)) if mc else 0.5,
                "reason": (mreason.group(1).strip()[:160] if mreason else "regex-extract")}
    low = raw.lower()
    if "not refuted" in low or "is supported" in low or "claim is true" in low or "is verifiable" in low:
        return {"provider": provider, "refuted": False, "confidence": 0.5, "reason": "heuristic(prose): supported"}
    return {"provider": provider, "refuted": True, "confidence": 0.3, "reason": "unparseable -> refuted (safe default)"}


def ground(claim: str, *, kind: str | None = None, refuters: list[str] | None = None, ask=None) -> dict:
    """Grounding adversarial : preuves RAG -> N refuteurs free-tier -> verdict consolide.

    verdict : GROUNDED (0 refute) | REFUTED (tous refutent) | UNCERTAIN (split).
    confidence = accord * confiance_moyenne. dissent = avis par refuteur."""
    provs = refuters or DEFAULT_REFUTERS
    evidence = _gather(claim, kind)
    verdicts = [_refute(claim, evidence, p, ask=ask) for p in provs]
    n = len(verdicts) or 1
    n_ref = sum(1 for v in verdicts if v["refuted"])
    verdict = "GROUNDED" if n_ref == 0 else ("REFUTED" if n_ref == n else "UNCERTAIN")
    mean_conf = round(sum(v["confidence"] for v in verdicts) / n, 3)
    agree = round(max(n_ref, n - n_ref) / n, 3)
    return {"claim": claim, "kind": _classify_kind(claim, kind), "verdict": verdict,
            "confidence": round(agree * mean_conf, 3), "agreement": agree,
            "sources": evidence, "dissent": verdicts}


def _selftest() -> int:
    def stub(provider, msg):  # 'R_false' refute, sinon valide
        return json.dumps({"refuted": provider == "R_false", "confidence": 0.9, "reason": "stub"})

    g1 = ground("claim", refuters=["R_true", "R_true"], ask=stub)
    assert g1["verdict"] == "GROUNDED", g1
    g2 = ground("claim", refuters=["R_false", "R_false"], ask=stub)
    assert g2["verdict"] == "REFUTED", g2
    g3 = ground("claim", refuters=["R_true", "R_false"], ask=stub)
    assert g3["verdict"] == "UNCERTAIN", g3
    # unparseable -> refute safe-default
    g4 = ground("claim", refuters=["X"], ask=lambda p, m: "not json at all")
    assert g4["verdict"] == "REFUTED", g4
    # P2 : routage par KIND (code-fact -> read le module reel) + parse robuste
    assert _classify_kind("forge_rag_engine utilise FAISS IndexFlatIP BM25") == "code"
    assert _classify_kind("la doc explique la philosophie souveraine") == "doc"
    cev = _gather_code("forge_rag_engine utilise FAISS IndexFlatIP RRF BM25", limit=3)
    pv = _refute("x", [], "P", ask=lambda p, m: 'reasoning...\n```json\n{"refuted": false, "confidence": 0.7}\n```')
    assert pv["refuted"] is False, pv  # parse robuste : JSON noye dans prose + fences
    # P3 : parse verdict robuste (reasoning cerebras-like) + gather AST-aware (def/class)
    pv2 = _refute("x", [], "C", ask=lambda p, m: 'analysis... claim unsupported.\nVerdict: "refuted": true, "confidence": 0.6')
    assert pv2["refuted"] is True and pv2["confidence"] == 0.6, pv2
    acev = _gather_code("forge_grounder definit la fonction ground et _gather_code", limit=4)
    ndef = sum(1 for s in acev if s["score"].startswith("code:"))
    assert ndef >= 1, acev  # AST a surface au moins une def/class
    print(f"GROUNDER OK | P1 verdicts | P2 classify+code-gather({len(cev)}) | "
          f"P3 parse-robuste(reasoning cerebras) + AST-gather({ndef} def/class)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    if "--claim" in sys.argv:
        i = sys.argv.index("--claim")
        c = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        print(json.dumps(ground(c), ensure_ascii=True, indent=2))
        raise SystemExit(0)
    print('usage: --selftest | --claim "<claim>"')
