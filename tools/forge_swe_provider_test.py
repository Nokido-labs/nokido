"""Teste call_llm (du runner SWE) pour chaque provider DANS le contexte trusted
(= contexte du runner détaché) -> voir le retour réel (ERR/firewall/token/code)."""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from nokido_agent.tools.forge_swebench_runner import call_llm  # noqa: E402

msgs = [{"role": "user", "content": "Ecris une fonction python qui inverse une string. Donne uniquement le code."}]
for prov in ("claude_cli", "gemini_cli", "groq"):
    try:
        r = call_llm(msgs, prov, max_tokens=120)
        print(f"{prov}: ({len(r)}c) {repr(r[:240])}")
    except Exception as e:
        print(f"{prov}: EXC {type(e).__name__}: {e}")
