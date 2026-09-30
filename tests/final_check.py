"""
tests/final_check.py — Gate de validation forge_context + dispatch_at @rag info
Ecrit le verdict dans sandbox/verdict.txt
Usage: python tests/final_check.py
"""
import sys, os, asyncio, traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
APP  = ROOT / 'app'
sys.path.insert(0, str(APP))

VERDICT = ROOT / 'sandbox' / 'verdict.txt'
log = []

def ok(msg):  log.append(f"✅ {msg}")
def fail(msg): log.append(f"❌ {msg}")

# ── 1. forge_context importable et contient les 5 singletons ─────────────────
try:
    import forge_context as ctx
    for s in ['rag_engine','version_manager','settings','ssh_manager','orchestrator']:
        if hasattr(ctx, s):
            ok(f"forge_context.{s} present")
        else:
            fail(f"forge_context.{s} ABSENT")
except Exception as e:
    fail(f"import forge_context: {e}")
    VERDICT.write_text("FAIL\n\n" + '\n'.join(log))
    sys.exit(1)

# ── 2. Simuler le boot : injecter des stubs dans forge_context ────────────────
class FakeRAG:
    chunks = [{"source": "Nokido.py", "text": "RAG test chunk"}]
    emb_file = ROOT / 'RAG' / 'embeddings.db'
    faiss_index = True
    bm25_index  = True
    indexed     = {}
    async def search(self, q, k=5): return self.chunks

class FakeChat:
    msgs = []
    def write(self, m): self.msgs.append(m)

class FakeApp:
    rag_engine = FakeRAG()
    def _chat_log(self): return FakeChat()

ctx.rag_engine      = FakeRAG()
ctx.settings        = type('S', (), {'use_rag': True})()
ctx.version_manager = type('V', (), {'current_version': '0.13.3'})()
ctx.ssh_manager     = object()
ctx.orchestrator    = object()
ok("boot simulé — 5 singletons injectés dans forge_context")

# ── 3. forge_commands importable ──────────────────────────────────────────────
try:
    import forge_commands as fc_mod
    ok("forge_commands importé")
except Exception as e:
    fail(f"import forge_commands: {e}\n{traceback.format_exc()[:300]}")
    VERDICT.write_text("FAIL\n\n" + '\n'.join(log))
    sys.exit(1)

# ── 4. dispatch_at '@rag info' sur FakeApp ────────────────────────────────────
async def run():
    app = FakeApp()
    try:
        result = await fc_mod.dispatch_at(app, "@rag info")
        if result:
            ok("dispatch_at('@rag info') retourne True")
        else:
            fail("dispatch_at retourne False — commande non reconnue")
        msgs = app._chat_log().msgs
        # Chercher un mot-cle RAG dans les messages
        all_text = ' '.join(str(m) for m in msgs)
        if any(kw in all_text for kw in ['chunk','Chunk','RAG','FAISS','source']):
            ok(f"chat contient mots-cles RAG: {all_text[:120]}")
        else:
            fail(f"chat vide ou sans mots-cles RAG: {all_text[:120]}")
    except Exception as e:
        fail(f"dispatch_at exception: {e}\n{traceback.format_exc()[:400]}")

asyncio.run(run())

# ── 5. mcp_bridge a query_rag ─────────────────────────────────────────────────
try:
    mb_txt = (APP / 'mcp_bridge.py').read_text(encoding='utf-8', errors='ignore')
    if 'query_rag' in mb_txt and 'forge_context' in mb_txt:
        ok("mcp_bridge.py expose query_rag via forge_context")
    else:
        fail("mcp_bridge.py : query_rag ou forge_context absent")
except Exception as e:
    fail(f"mcp_bridge check: {e}")

# ── 6. 0 _g() critiques dans forge_commands ───────────────────────────────────
import re
cmd_txt = (APP / 'forge_commands.py').read_text(encoding='utf-8', errors='ignore')
g_count = len(re.findall(r"_g\('\w+'\)", cmd_txt))
if g_count == 0:
    ok("forge_commands.py : 0 _g() restants")
else:
    fail(f"forge_commands.py : {g_count} _g() restants")

# ── Verdict final ─────────────────────────────────────────────────────────────
failures = [l for l in log if l.startswith('❌')]
verdict  = "SUCCESS" if not failures else "FAIL"

report = f"{verdict}\n\n" + '\n'.join(log)
VERDICT.write_text(report, encoding='utf-8')
print(report)
sys.exit(0 if verdict == "SUCCESS" else 1)
