"""forge_card_summarize.py — DEFINITIONS grounded des modules sans docstring.

Pour chaque module forge a docstring faible : lit le CODE REEL et demande au LLM
free-tier (groq via forge_agent_proxy.ask, raw=True) une description 1-2 phrases
DEDUITE DU CODE (pas une glose de signatures). Persiste dans
tools/forge_card_summaries.json (tracke, keye par sha source -> anti-derive :
un module recode = resume invalide -> regenere).

Idempotent + --limit par run (tient sous le cap 120s du trusted_script).
Boucle externe : appeler --limit K jusqu'a remaining=0.
"""
from __future__ import annotations
import sys, json, asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WS = ROOT / "sandbox" / "workspace"
SUMMARIES = ROOT / "tools" / "forge_card_summaries.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_agent_proxy import ask  # provider registry + vault (contexte trusted)
try:
    from nokido_agent.app.forge_llamacpp import llamacpp_call, is_available as _llama_up, strip_think  # local :8080, illimite
except Exception:
    llamacpp_call = None
    def _llama_up():
        return False
    def strip_think(t):
        return t

PROVIDERS = ["ollama"]  # local seulement, cloud INTERDIT
PROMPT = (
    "Voici le CODE REEL (debut) d'un module Python du systeme Nokido, SANS docstring.\n"
    "En 1 a 2 phrases FR concretes, dis ce que FAIT ce module (son role, ce qu'il\n"
    "manipule/produit), DEDUIT DU CODE. Reponds UNIQUEMENT la description, sans\n"
    "preambule, sans markdown, sans repeter le nom du fichier.\n\nMODULE {name}:\n```python\n{code}\n```"
)
BATCH_PROMPT = (
    "Voici plusieurs modules Python Nokido SANS docstring, avec leur CODE REEL.\n"
    "Pour CHAQUE module, ecris UNE definition concrete DEDUITE DU CODE (role, ce qu'il\n"
    "manipule/produit). Format STRICT, une ligne par module, EXACTEMENT :\n"
    "nomfichier.py === description en une phrase\n"
    "Aucune autre ligne, pas de markdown, pas de numero, pas de bloc de code.\n\n"
)


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _is_bad(s: str) -> bool:
    """Rejette les reponses polluees (firewall/erreur/quota) au lieu de les stocker."""
    if not s or len(s) < 15:
        return True
    low = s.lower()
    return any(m in low for m in (
        "[firewall]", "envoi cloud", "modele local", "mod`le local", "modèle local",
        "rate_limit", "error code", "indisponible", "timeout apres", "provider ", "dlp:",
    ))


def targets() -> list:
    cards = _load(WS / "module_cards.json", {})
    summ = _load(SUMMARIES, {})
    out = []
    for mod, c in cards.items():
        name = mod.split("/")[-1]
        if not name.startswith("forge_"):
            continue
        if len(c.get("doc", "")) >= 25:
            continue
        sha = c.get("sha", "")
        prev = summ.get(mod)
        if prev and prev.get("sha") == sha and prev.get("summary"):
            continue
        out.append((mod, name, sha))
    return out


async def run(limit: int, batch: int = 2):
    summ = _load(SUMMARIES, {})
    _before = len(summ)
    summ = {k: v for k, v in summ.items() if not _is_bad(v.get("summary", ""))}
    if len(summ) != _before:
        SUMMARIES.write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    tg = targets()[:limit]
    done = 0
    # BATCH : N modules en UN appel LLM -> amortit la latence (bat le cap 120s).
    for i in range(0, len(tg), batch):
        chunk = tg[i:i + batch]
        blocks, names = [], {}
        for mod, name, sha in chunk:
            try:
                code = (ROOT / mod).read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            names[name] = (mod, sha)
            blocks.append(f"### {name}\n```python\n{code[:1400]}\n```")
        if not blocks:
            continue
        prompt = BATCH_PROMPT + "\n\n".join(blocks)
        text = ""
        for prov in PROVIDERS:
            try:
                kwargs = {"raw": True, "rag_context": False, "max_tokens": 900, "timeout": 115}
                if prov == "ollama":
                    kwargs["model"] = "huihui_ai/deepseek-r1-abliterated:8b"
                r = await ask(prov, prompt, **kwargs)
            except Exception:
                r = {"ok": False}
            if r.get("ok") and r.get("text") and not _is_bad(r["text"]):
                text = strip_think(r["text"])
                break
        for line in text.splitlines():
            if " === " not in line:
                continue
            nm, _, desc = line.partition(" === ")
            nm = nm.strip().strip("`*-# ")
            desc = " ".join(desc.strip().split())[:320]
            if nm in names and desc and not _is_bad(desc):
                mod, sha = names[nm]
                summ[mod] = {"sha": sha, "summary": desc}
                done += 1
        SUMMARIES.write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    rem = [m for m, c in _load(WS / "module_cards.json", {}).items()
           if m.split("/")[-1].startswith("forge_") and len(c.get("doc") or "") < 25 and not summ.get(m, {}).get("summary")]
    print(json.dumps({"processed": done, "remaining": len(rem)}, ensure_ascii=False))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--probe", action="store_true", help="diagnostic llama.cpp local")
    a = ap.parse_args()
    if a.probe:
        up = False
        try:
            up = bool(_llama_up())
        except Exception as e:
            print("is_available err:", e)
        out = {"llama_available": up, "llamacpp_call": bool(llamacpp_call)}
        try:
            import urllib.request
            tags = json.loads(urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5).read())
            out["ollama_models"] = [m.get("name") for m in tags.get("models", [])]
        except Exception as e:
            out["ollama_err"] = str(e)[:120]
        print(json.dumps(out, ensure_ascii=False))
        return
    asyncio.run(run(a.limit))


if __name__ == "__main__":
    main()
