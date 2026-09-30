"""tools/gen_demo_gifs.py — Generate launch demo GIFs via Playwright.

Two GIFs :
  1. Terminal demo (xterm.js-styled HTML with typed commands + outputs).
  2. Admin UI demo (rendered from the same HTML template as the live page,
     with fake providers data for stability + reproducibility).

Output : docs/launch/media/demo_terminal.gif, demo_admin_ui.gif.

Cross-OS, headless, no GUI required. Uses Playwright + Pillow.
"""

from __future__ import annotations

__FORGE_COLOR__ = "infra/deploy : genere les GIF de demo via Playwright"  # organe declare le 2026-09-06 (audit de raccordement)

import io
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "launch" / "media"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ════════════════════════════════════════════════════════════════════════
# Terminal HTML — self-contained, auto-types commands with realistic output
# ════════════════════════════════════════════════════════════════════════
TERMINAL_HTML = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Nokido demo</title>
<style>
  body { margin:0; padding:0; background:#0d1117; font-family:'JetBrains Mono','Cascadia Code',Consolas,monospace; font-size:14px; color:#c9d1d9; line-height:1.5; }
  .term { padding:20px 28px; min-height:100vh; box-sizing:border-box; }
  .prompt { color:#58a6ff; font-weight:bold; }
  .cmd { color:#e6edf3; }
  .ok { color:#3fb950; }
  .warn { color:#d29922; }
  .err { color:#f85149; }
  .dim { color:#7d8590; }
  .blue { color:#79c0ff; }
  .purple { color:#d2a8ff; }
  .caption { background:#1f6feb22; padding:14px 18px; border-left:3px solid #58a6ff; margin:18px 0; border-radius:4px; }
  .h1 { color:#fff; font-size:18px; font-weight:bold; padding:6px 0; }
  .h2 { color:#79c0ff; font-size:15px; padding:4px 0; }
  pre { margin:0; padding:0; font-family:inherit; }
  #out span { display:inline; }
  .blink { display:inline-block; width:8px; height:14px; background:#58a6ff; vertical-align:middle; animation:blink 0.8s infinite; }
  @keyframes blink { 50% { opacity:0; } }
</style>
</head><body>
<div class="term" id="out"></div>
<script>
const out = document.getElementById('out');
const frames = [
  '<div class="h1">Nokido — Autonomous Local-First AI OS</div><div class="dim"># Local hub, neuro-symbolic governance, 25 MCP tools</div><br>',
  '<span class="prompt">$ </span><span class="cmd">curl -s http://localhost:8766/health | jq</span>',
  '<br><span class="ok">{ "status": "ok", "version": "18.3", "ts": "2026-05-26T21:00:00Z" }</span><br><br>',

  '<span class="prompt">$ </span><span class="cmd">curl -s -X POST http://localhost:8766/mcp -d \'{"method":"tools/list"}\'</span>',
  '<br><span class="h2"># 25 MCP tools exposed by the hub:</span>',
  '<br><span class="blue">  • run</span> <span class="dim">— github / python / shell / trusted_script / atlas</span>',
  '<br><span class="blue">  • read</span> <span class="dim">— file or tail_logs</span>',
  '<br><span class="blue">  • rag</span> <span class="dim">— hybrid retrieval FTS5+BM25+FAISS+reranker</span>',
  '<br><span class="blue">  • ask</span> <span class="dim">— 29 LLM providers cascade</span>',
  '<br><span class="blue">  • orchestrate</span> <span class="dim">— autonomous loop via local Qwen2.5-Coder</span>',
  '<br><span class="blue">  • plan</span> <span class="dim">— GOAP planner</span>',
  '<br><span class="blue">  • biblio</span> <span class="dim">— bibliography worker</span>',
  '<br><span class="blue">  • netcfg</span> <span class="dim">— multi-vendor network (Cisco/Huawei/Aruba/HPE)</span>',
  '<br><span class="dim">  … (17 more)</span><br><br>',

  '<span class="prompt">$ </span><span class="cmd">curl -s -X POST http://localhost:8766/mcp -d \'{"name":"ask","provider":"ollama_local","msg":"What is RAG?"}\'</span>',
  '<br><span class="h2"># Routing to local Ollama — zero cloud egress</span>',
  '<br><span class="purple">RAG (Retrieval-Augmented Generation) combines large language models</span>',
  '<br><span class="purple">with external knowledge retrieval: a query first searches a vector</span>',
  '<br><span class="purple">database for relevant documents, which are then injected as context</span>',
  '<br><span class="purple">into the LLM prompt for more grounded, factual responses.</span><br><br>',

  '<span class="prompt">$ </span><span class="cmd">python -c "from forge_semantic_firewall import get_firewall; ..."</span>',
  '<br><span class="h2"># Semantic firewall pre-flight on a prompt with sensitive data:</span>',
  '<br><span class="warn">  Input:  "My API key is sk-proj-abc123def456; what is RAG?"</span>',
  '<br><span class="ok">  Safe task:  "My API key is &lt;api_key:HMAC_abc&gt;; what is RAG?"</span>',
  '<br><span class="ok">  Mapping aliases: 1 sensitive token replaced</span>',
  '<br><span class="ok">  Pre-flight: OK</span><br><br>',

  '<span class="prompt">$ </span><span class="cmd">curl -s -X POST http://localhost:8766/mcp -d \'{"name":"rag","action":"search","topic":"neuromorphic"}\'</span>',
  '<br><span class="h2"># RAG search in 380k+ chunks (BGE-M3 1024D + FTS5 + reranker):</span>',
  '<br><span class="blue">  [0.94] MANIFESTO.md §6.3  — Neuromorphic (12-24 months): Loihi 2, NorthPole, Akida</span>',
  '<br><span class="blue">  [0.91] docs/wiki/13       — Phase B target: forge_spike_router on Lava-Loihi</span>',
  '<br><span class="blue">  [0.88] app/forge_lnn_monitor — CfC continuous-time, ~100× lighter than LLM</span>',
  '<br><br>',

  '<div class="caption"><span class="h2">Nokido — Local-first · Neuro-symbolic · AGPLv3</span><br>'
  + '<span class="dim">github.com/Nokido-labs/nokido — Manifesto + Wiki in repo</span><br>'
  + '<span class="dim">Tested on AMD Ryzen 7 8700G + Radeon 780M iGPU</span><br>'
  + '<span class="dim">HumanEval 87.8% · BFCL v4 90-96% · 29 LLM providers cascade</span></div>',
];

let i = 0;
function step() {
  if (i >= frames.length) { window.demoDone = true; return; }
  out.insertAdjacentHTML('beforeend', frames[i]);
  i++;
  setTimeout(step, 500);
}
setTimeout(step, 300);
</script>
</body></html>"""


# ════════════════════════════════════════════════════════════════════════
# Admin UI HTML — extract of the real /admin/providers template
# ════════════════════════════════════════════════════════════════════════
ADMIN_HTML = r"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><title>Nokido — LLM Providers</title>
<script defer src="https://unpkg.com/alpinejs@3.14.3/dist/cdn.min.js"></script>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; background:#0d1117; color:#c9d1d9; }
  .tier-local { color:#3fb950; }
  .tier-free  { color:#58a6ff; }
  .tier-paid_api { color:#d29922; }
  .pill { padding:2px 8px; border-radius:6px; font-size:0.75rem; }
  .pill-on  { background:#238636; color:#fff; }
  .pill-off { background:#6e7681; color:#fff; }
  .cap { background:#1f6feb22; color:#79c0ff; padding:1px 6px; border-radius:4px; font-size:0.7rem; margin-right:4px; }
  table { width:100%; border-collapse:collapse; }
  th, td { padding:8px 12px; text-align:left; border-bottom:1px solid #21262d; }
  th { background:#161b22; font-weight:600; font-size:0.85rem; text-transform:uppercase; }
  input, select { background:#0d1117; border:1px solid #30363d; color:#c9d1d9; padding:4px 8px; border-radius:4px; }
  button { background:#1f6feb; color:#fff; padding:4px 12px; border-radius:6px; border:none; cursor:pointer; font-size:0.85rem; }
  button.ghost { background:transparent; border:1px solid #30363d; color:#c9d1d9; }
  button.danger { background:#da3633; }
  [x-cloak] { display: none !important; }
</style>
</head><body class="p-6">

<header class="mb-6 flex justify-between items-center">
  <div>
    <h1 class="text-2xl font-bold">🔌 LLM Providers Admin</h1>
    <p class="text-sm text-gray-400">Vault-backed key management — DPAPI / Keychain / libsecret. Never .env.</p>
  </div>
  <div class="text-sm text-gray-500">29 providers · 14 cloud free-tier · 3 local</div>
</header>

<div x-data="providers" x-init="load()" class="space-y-4">
  <div class="flex gap-3 items-center text-sm">
    <input x-model="search" placeholder="Filter by name…" class="w-64" id="filter-input">
    <select x-model="tierFilter" id="tier-filter">
      <option value="">All tiers</option>
      <option value="local">Local</option>
      <option value="free">Free cloud</option>
      <option value="paid_api">Paid API</option>
    </select>
    <label class="text-gray-400"><input type="checkbox" x-model="onlyMissingKey"> Only missing keys</label>
    <span class="text-gray-500 ml-auto" x-text="`${visible().length} / ${rows.length} providers`"></span>
  </div>

  <table>
    <thead><tr>
      <th>Provider</th><th>Tier</th><th>Capabilities</th><th>Context</th>
      <th>Vault key</th><th>Status</th><th>Actions</th>
    </tr></thead>
    <tbody>
      <template x-for="p in visible()" :key="p.name">
        <tr>
          <td>
            <div class="font-mono font-semibold" x-text="p.name"></div>
            <div class="text-xs text-gray-500" x-text="p.notes"></div>
          </td>
          <td><span :class="'tier-' + p.tier" x-text="p.tier"></span></td>
          <td>
            <template x-for="c in p.capabilities" :key="c">
              <span class="cap" x-text="c"></span>
            </template>
          </td>
          <td x-text="p.context.toLocaleString()"></td>
          <td><code class="text-xs text-purple-300" x-text="p.vault_key || '-'"></code></td>
          <td>
            <span :class="p.has_key ? 'pill pill-on' : 'pill pill-off'"
                  x-text="p.has_key ? '✓ key present' : (p.vault_key ? '✗ no key' : 'n/a')"></span>
          </td>
          <td class="space-x-1">
            <template x-if="p.vault_key">
              <button class="ghost" @click="openModal(p)" :id="'set-' + p.name">🔑 Set key</button>
            </template>
            <button class="ghost">▶ Test</button>
            <template x-if="p.has_key && p.vault_key">
              <button class="danger">✗ Remove</button>
            </template>
          </td>
        </tr>
      </template>
    </tbody>
  </table>

  <div x-show="modalOpen" x-cloak id="modal" class="fixed inset-0 bg-black/70 flex items-center justify-center">
    <div class="bg-gray-900 p-6 rounded-lg w-96 space-y-3">
      <h3 class="text-lg font-semibold">Set API key — <span class="font-mono text-blue-400" x-text="modalProvider"></span></h3>
      <p class="text-xs text-gray-400">
        Stored in: <code class="text-purple-300" x-text="modalVaultKey"></code> (vault DPAPI/Keychain/libsecret).
        Never written to <code>.env</code>.
      </p>
      <input type="password" x-model="modalKey" placeholder="Paste API key here" class="w-full" id="key-input">
      <div class="flex justify-end gap-2 pt-2">
        <button class="ghost" @click="modalOpen=false">Cancel</button>
        <button @click="saveKey()" id="save-btn">Save to vault</button>
      </div>
    </div>
  </div>

  <div x-show="toast" x-cloak x-transition.duration.300ms
       class="fixed bottom-4 right-4 bg-gray-800 px-4 py-2 rounded shadow-lg"
       x-text="toast"></div>
</div>

<script>
document.addEventListener('alpine:init', () => {
  Alpine.data('providers', () => ({
    rows: [
      { name: "ollama_local",          tier: "local",    context: 32000,  capabilities: ["chat","code","reasoning","tool_call"],   vault_key: null,                  has_key: true,  notes: "qwen2.5-coder, deepseek-r1, ..." },
      { name: "llamacpp_local",        tier: "local",    context: 32000,  capabilities: ["chat","code","tool_call"],               vault_key: null,                  has_key: true,  notes: "qwen2.5-coder:7b on :8080" },
      { name: "lmstudio_native",       tier: "local",    context: 8192,   capabilities: ["chat","code"],                           vault_key: null,                  has_key: true,  notes: "OpenAI-compat :1234" },
      { name: "groq",                  tier: "free",     context: 32768,  capabilities: ["chat","code","reasoning","tool_call"],   vault_key: "GROQ_API_KEY",        has_key: false, notes: "30k calls/mo, ultra-fast" },
      { name: "cerebras",              tier: "free",     context: 8192,   capabilities: ["chat","code","reasoning"],               vault_key: "CEREBRAS_API_KEY",    has_key: false, notes: "Wafer-scale, 1M tokens/day" },
      { name: "gemini_flash",          tier: "free",     context: 1000000,capabilities: ["chat","code","vision","long_context"],  vault_key: "GEMINI_API_KEY",      has_key: true,  notes: "1M context window" },
      { name: "gemini_pro",            tier: "free",     context: 1000000,capabilities: ["reasoning","vision","long_context"],     vault_key: "GEMINI_API_KEY",      has_key: true,  notes: "1k/mo free tier" },
      { name: "mistral_small",         tier: "free",     context: 32000,  capabilities: ["chat","code","tool_call"],               vault_key: "MISTRAL_API_KEY",     has_key: false, notes: "European sovereign" },
      { name: "cohere_command_r",      tier: "free",     context: 128000, capabilities: ["chat","rag"],                            vault_key: "COHERE_API_KEY",      has_key: false, notes: "1k/mo trial, RAG-optimised" },
      { name: "hf_qwen_coder",         tier: "free",     context: 32000,  capabilities: ["code"],                                  vault_key: "HF_TOKEN",            has_key: false, notes: "HuggingFace Inference" },
      { name: "sambanova_llama_405b",  tier: "free",     context: 8192,   capabilities: ["reasoning","chat"],                      vault_key: "SAMBANOVA_API_KEY",   has_key: false, notes: "Llama 3.1 405B free tier" },
      { name: "anthropic_claude",      tier: "paid_api", context: 200000, capabilities: ["chat","code","reasoning","tool_call"],   vault_key: "ANTHROPIC_API_KEY",   has_key: false, notes: "Opt-in cloud — disabled by default" },
    ],
    search: '', tierFilter: '', onlyMissingKey: false,
    modalOpen: false, modalProvider: '', modalVaultKey: '', modalKey: '',
    toast: '',
    load() {},
    visible() {
      return this.rows.filter(p =>
        (!this.search || p.name.includes(this.search.toLowerCase())) &&
        (!this.tierFilter || p.tier === this.tierFilter) &&
        (!this.onlyMissingKey || (p.vault_key && !p.has_key))
      );
    },
    openModal(p) {
      this.modalProvider = p.name;
      this.modalVaultKey = p.vault_key;
      this.modalKey = '';
      this.modalOpen = true;
    },
    saveKey() {
      this.toast = 'Saved ' + this.modalVaultKey + ' → vault (***' + this.modalKey.slice(-4) + ')';
      const row = this.rows.find(r => r.name === this.modalProvider);
      if (row) row.has_key = true;
      this.modalOpen = false;
      setTimeout(() => { this.toast = ''; }, 3500);
    }
  }));
});
</script>
</body></html>"""


def write_html(content: str, name: str) -> Path:
    path = OUT_DIR / name
    path.write_text(content, encoding="utf-8")
    return path


def grab_frames(page, n_frames: int, interval_ms: int) -> list[Image.Image]:
    """Capture screenshots at fixed cadence."""
    frames = []
    for _ in range(n_frames):
        png_bytes = page.screenshot(type="png", full_page=False)
        frames.append(
            Image.open(io.BytesIO(png_bytes)).convert("P", palette=Image.ADAPTIVE, colors=128)
        )
        time.sleep(interval_ms / 1000.0)
    return frames


def save_gif(frames: list[Image.Image], out_path: Path, frame_ms: int) -> None:
    """Save list of frames as optimized GIF."""
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        optimize=True,
        duration=frame_ms,
        loop=0,
        disposal=2,
    )


def make_terminal_gif():
    html = write_html(TERMINAL_HTML, "_terminal.html")
    out = OUT_DIR / "demo_terminal.gif"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 920, "height": 640}, device_scale_factor=1)
        page.goto(f"file:///{html.as_posix()}")
        # Wait initial paint
        time.sleep(0.5)
        # Capture frames during the typing animation
        # Total animation ~10s (38 frames @ 500ms). Capture 30 frames @ 350ms.
        frames = grab_frames(page, n_frames=30, interval_ms=350)
        browser.close()

    save_gif(frames, out, frame_ms=300)
    print(f"[ok] {out} ({out.stat().st_size} bytes)")


def make_admin_gif():
    html = write_html(ADMIN_HTML, "_admin.html")
    out = OUT_DIR / "demo_admin_ui.gif"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 720}, device_scale_factor=1)
        page.goto(f"file:///{html.as_posix()}")
        page.wait_for_selector("#tier-filter")
        time.sleep(0.6)

        frames = []

        def capture(n=3, delay_ms=300):
            for _ in range(n):
                png = page.screenshot(type="png", full_page=False)
                frames.append(
                    Image.open(io.BytesIO(png)).convert("P", palette=Image.ADAPTIVE, colors=128)
                )
                time.sleep(delay_ms / 1000.0)

        # Scene 1 : initial view (full table)
        capture(n=4, delay_ms=350)

        # Scene 2 : filter to "Free cloud" tier
        page.select_option("#tier-filter", "free")
        time.sleep(0.4)
        capture(n=3, delay_ms=400)

        # Scene 3 : click set key on "groq" row
        page.click("#set-groq")
        time.sleep(0.5)
        capture(n=3, delay_ms=400)

        # Scene 4 : type API key
        page.fill("#key-input", "gsk_demo_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        time.sleep(0.4)
        capture(n=2, delay_ms=400)

        # Scene 5 : click save
        page.click("#save-btn")
        time.sleep(0.4)
        capture(n=4, delay_ms=400)

        # Scene 6 : show that groq now has key present + final pause
        page.evaluate(
            "document.querySelector('#tier-filter').value = ''; document.querySelector('#tier-filter').dispatchEvent(new Event('change'))"
        )
        page.select_option("#tier-filter", "")
        time.sleep(0.4)
        capture(n=4, delay_ms=500)

        browser.close()

    save_gif(frames, out, frame_ms=350)
    print(f"[ok] {out} ({out.stat().st_size} bytes)")


def main():
    print("[1/2] Generating terminal demo GIF...")
    make_terminal_gif()
    print("[2/2] Generating admin UI demo GIF...")
    make_admin_gif()
    print("\nDone. Files in :", OUT_DIR)


if __name__ == "__main__":
    sys.exit(main() or 0)
