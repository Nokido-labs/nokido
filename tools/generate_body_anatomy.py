"""
generate_body_anatomy.py — Corps Nokido, A4 lisible
Silhouette humaine + zones biologiques groupées, fontsize ≥9.
"""

import matplotlib

matplotlib.use("Agg")
import pathlib

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Ellipse, FancyBboxPatch

W, H = 8.27, 11.69  # A4 portrait inches
BG = "#07070f"

fig, ax = plt.subplots(figsize=(W, H), facecolor=BG)
ax.set_facecolor(BG)
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")

CX = W / 2  # 4.135

SKIN = "#22203a"
BORD = "#4a4070"
ORGAN = "#0d1a2a"


# ── Body silhouette ────────────────────────────────────────────────────────
def body():
    # Head
    ax.add_patch(Ellipse((CX, 10.0), 1.5, 1.8, fc=SKIN, ec=BORD, lw=1.2, zorder=2))
    # Neck
    ax.add_patch(
        FancyBboxPatch(
            (CX - 0.28, 9.0),
            0.56,
            0.95,
            boxstyle="round,pad=0.05",
            fc=SKIN,
            ec=BORD,
            lw=0.8,
            zorder=2,
        )
    )
    # Torso
    ax.add_patch(
        FancyBboxPatch(
            (CX - 1.5, 5.6),
            3.0,
            3.35,
            boxstyle="round,pad=0.15",
            fc=SKIN,
            ec=BORD,
            lw=1.2,
            zorder=2,
        )
    )
    # L arm
    ax.add_patch(
        FancyBboxPatch(
            (CX - 2.45, 5.2), 0.9, 3.1, boxstyle="round,pad=0.1", fc=SKIN, ec=BORD, lw=0.8, zorder=2
        )
    )
    # R arm
    ax.add_patch(
        FancyBboxPatch(
            (CX + 1.55, 5.2), 0.9, 3.1, boxstyle="round,pad=0.1", fc=SKIN, ec=BORD, lw=0.8, zorder=2
        )
    )
    # L forearm
    ax.add_patch(
        FancyBboxPatch(
            (CX - 2.65, 2.8),
            0.85,
            2.55,
            boxstyle="round,pad=0.1",
            fc=SKIN,
            ec=BORD,
            lw=0.8,
            zorder=2,
        )
    )
    # R forearm
    ax.add_patch(
        FancyBboxPatch(
            (CX + 1.8, 2.8),
            0.85,
            2.55,
            boxstyle="round,pad=0.1",
            fc=SKIN,
            ec=BORD,
            lw=0.8,
            zorder=2,
        )
    )
    # L leg
    ax.add_patch(
        FancyBboxPatch(
            (CX - 1.4, 2.4),
            1.25,
            3.25,
            boxstyle="round,pad=0.1",
            fc=SKIN,
            ec=BORD,
            lw=0.8,
            zorder=2,
        )
    )
    # R leg
    ax.add_patch(
        FancyBboxPatch(
            (CX + 0.15, 2.4),
            1.25,
            3.25,
            boxstyle="round,pad=0.1",
            fc=SKIN,
            ec=BORD,
            lw=0.8,
            zorder=2,
        )
    )
    # Feet
    ax.add_patch(Ellipse((CX - 0.8, 2.1), 1.4, 0.55, fc=SKIN, ec=BORD, lw=0.8, zorder=2))
    ax.add_patch(Ellipse((CX + 0.8, 2.1), 1.4, 0.55, fc=SKIN, ec=BORD, lw=0.8, zorder=2))


def organs():
    # Brain
    ax.add_patch(Ellipse((CX, 10.15), 1.1, 0.9, fc="#1a2660", ec="#5566cc", lw=1.5, zorder=3))
    # Spine dots
    for y in np.arange(6.0, 9.1, 0.55):
        ax.add_patch(Ellipse((CX, y), 0.18, 0.16, fc="#2a1a4a", ec="#6644aa", lw=0.6, zorder=3))
    # Heart
    ax.add_patch(Ellipse((CX - 0.55, 7.9), 0.6, 0.65, fc="#3a0808", ec="#cc2222", lw=1.5, zorder=3))
    # Lungs
    ax.add_patch(
        Ellipse((CX - 1.0, 7.7), 0.75, 1.3, fc="#0a2015", ec="#228855", lw=1, zorder=3, alpha=0.85)
    )
    ax.add_patch(
        Ellipse((CX + 1.0, 7.7), 0.75, 1.3, fc="#0a2015", ec="#228855", lw=1, zorder=3, alpha=0.85)
    )
    # Liver
    ax.add_patch(
        FancyBboxPatch(
            (CX - 1.2, 6.7),
            1.3,
            0.8,
            boxstyle="round,pad=0.08",
            fc="#151f05",
            ec="#557722",
            lw=1,
            zorder=3,
        )
    )
    # Stomach
    ax.add_patch(Ellipse((CX + 0.65, 7.1), 0.75, 0.65, fc="#1a1a05", ec="#aaaa22", lw=1, zorder=3))
    # Kidneys
    ax.add_patch(Ellipse((CX - 0.85, 6.5), 0.38, 0.55, fc="#081520", ec="#2299bb", lw=1, zorder=3))
    ax.add_patch(Ellipse((CX + 0.85, 6.5), 0.38, 0.55, fc="#081520", ec="#2299bb", lw=1, zorder=3))
    # Intestines
    ax.add_patch(
        Ellipse((CX, 5.9), 1.3, 0.75, fc="#0d1f08", ec="#338844", lw=1, zorder=3, alpha=0.8)
    )
    # Aorta
    ax.plot([CX, CX], [5.6, 8.8], color="#770000", lw=2, zorder=3, alpha=0.5)
    # Immune nodes
    for pos in [(CX - 1.4, 8.7), (CX + 1.4, 8.7), (CX - 1.35, 6.15), (CX + 1.35, 6.15)]:
        ax.add_patch(Ellipse(pos, 0.22, 0.22, fc="#200808", ec="#992222", lw=0.8, zorder=3))


body()
organs()


# ── Callout helper ─────────────────────────────────────────────────────────
def callout(bio, modules, body_pt, label_pt, color, side="left"):
    bx, by = body_pt
    lx, ly = label_pt
    bw = 2.55 if side == "left" else 2.55
    bh = 0.18 + 0.155 * len(modules)
    ox = lx if side == "left" else lx - bw
    # Box
    ax.add_patch(
        FancyBboxPatch(
            (ox, ly - bh / 2),
            bw,
            bh,
            boxstyle="round,pad=0.06",
            fc="#0d0d1e",
            ec=color,
            lw=1.1,
            zorder=8,
        )
    )
    # Bio label
    ax.text(
        ox + bw / 2,
        ly + bh / 2 - 0.13,
        bio,
        ha="center",
        va="top",
        fontsize=9,
        color=color,
        fontweight="bold",
        zorder=9,
    )
    # Module lines
    for i, mod in enumerate(modules):
        ax.text(
            ox + 0.12,
            ly + bh / 2 - 0.27 - i * 0.155,
            f"• {mod}",
            ha="left",
            va="top",
            fontsize=7,
            color="#aaaacc",
            fontfamily="monospace",
            zorder=9,
        )
    # Arrow to body
    ax.annotate(
        "",
        xy=(bx, by),
        xytext=(lx, ly),
        arrowprops=dict(
            arrowstyle="-|>", color=color, alpha=0.6, lw=0.9, connectionstyle="arc3,rad=0.1"
        ),
        zorder=7,
    )


# ── Callouts LEFT ─────────────────────────────────────────────────────────
LX = 2.45  # right edge of left label column
callout(
    "Cortex préfrontal",
    ["forge_cognitive_router", "forge_llm_router"],
    (CX - 0.3, 10.4),
    (LX, 10.9),
    "#7788ff",
    "left",
)

callout(
    "Hippocampe",
    ["forge_self_correction", "forge_hippocampus"],
    (CX - 0.4, 10.1),
    (LX, 10.2),
    "#44dd88",
    "left",
)

callout(
    "Thalamus / NLU",
    ["forge_nlu", "forge_intent_parser"],
    (CX - 0.2, 9.75),
    (LX, 9.4),
    "#9988ff",
    "left",
)

callout(
    "Cervelet SNN",
    ["forge_spike_router (PyTorch)", "proxy_deno/brain.ts"],
    (CX + 0.3, 10.0),
    (LX, 8.6),
    "#6677ff",
    "left",
)

callout(
    "Barrière immunitaire",
    ["forge_semantic_firewall", "forge_prompt_guard"],
    (CX - 1.4, 8.7),
    (LX, 7.85),
    "#ff5555",
    "left",
)

callout(
    "Poumons / Métab.",
    ["NokidoAutonomousLoops", "forge_llm_router cascade"],
    (CX - 1.0, 7.5),
    (LX, 7.1),
    "#44cc88",
    "left",
)

callout(
    "Cœur / Hypothalamus",
    ["forge_homeostasis_orchestrator", "forge_coagulation_cascade"],
    (CX - 0.55, 7.9),
    (LX, 6.35),
    "#ff6688",
    "left",
)

callout(
    "Foie — Détox DLP",
    ["forge_secret_guard", "forge_conv_sanitizer"],
    (CX - 0.55, 7.1),
    (LX, 5.6),
    "#99bb33",
    "left",
)

callout(
    "Reins — Épuration",
    ["forge_renal_clearance", "forge_rag_qualify (LTP)"],
    (CX - 0.85, 6.5),
    (LX, 4.85),
    "#44aacc",
    "left",
)

callout(
    "Système végétatif",
    ["forge_inspector (bulbe)", "forge_idle_watchdog"],
    (CX, 8.0),
    (LX, 4.1),
    "#cccc44",
    "left",
)

callout(
    "Muscles striés",
    ["forge_silo_engine 7 domaines", "forge_orchestrator"],
    (CX - 2.0, 4.5),
    (LX, 3.35),
    "#ddaa33",
    "left",
)

# ── Callouts RIGHT ────────────────────────────────────────────────────────
RX = W - 2.45  # left edge of right label column

callout(
    "Tronc cérébral — Hub",
    ["nokido_hub.py :8766", "supervisor.ts :8765"],
    (CX + 0.3, 10.3),
    (RX, 10.9),
    "#8899ff",
    "right",
)

callout(
    "Synapses vectorielles",
    ["brain_worker :5557 BGE-M3", "forge_rag_engine FAISS+BM25"],
    (CX + 0.4, 10.1),
    (RX, 10.1),
    "#55ffaa",
    "right",
)

callout(
    "SN Périphérique",
    ["forge_mcp_registry", "forge_byte_router (moelle)"],
    (CX, 9.0),
    (RX, 9.3),
    "#5566ee",
    "right",
)

callout(
    "Vision / Ouïe",
    ["forge_browser_tool / crawl", "MCP STDIO → Claude Desktop"],
    (CX + 0.6, 9.7),
    (RX, 8.55),
    "#44ddcc",
    "right",
)

callout(
    "Membrane cellulaire",
    ["forge_sovereign_membrane", "forge_integrity HMAC/RBAC"],
    (CX + 1.35, 8.7),
    (RX, 7.8),
    "#ff4444",
    "right",
)

callout(
    "Estomac — Ingest",
    ["/ingest/url  /ingest/bulk", "forge_ingest_self MarkdownChunker"],
    (CX + 0.65, 7.1),
    (RX, 7.05),
    "#ccee55",
    "right",
)

callout(
    "Cortex LT — RAG",
    ["RAG/embeddings.db 106k", "forge_rag_store + forge_rag_warmup"],
    (CX + 0.5, 10.4),
    (RX, 6.3),
    "#33cc66",
    "right",
)

callout(
    "Intestin grêle",
    ["forge_rag_qualify absorption", "forge_rag_cache LRU"],
    (CX, 5.9),
    (RX, 5.55),
    "#55cc77",
    "right",
)

callout(
    "Myéline — WASM",
    ["supervisor.ts LaForge-Master", "forge_wasm_cervelet :7401"],
    (CX + 1.6, 3.8),
    (RX, 4.8),
    "#88eeff",
    "right",
)

callout(
    "Macrophages / NK",
    ["SkillGuardian (review)", "NoiseGuardian IPs/MACs"],
    (CX + 1.35, 6.15),
    (RX, 4.05),
    "#dd3333",
    "right",
)

callout(
    "Locomoteur / Squelette",
    ["forge_runner mmap IPC", "forge_runtime + forge_broker_base"],
    (CX + 1.9, 3.5),
    (RX, 3.3),
    "#bb9922",
    "right",
)

# ── Title ──────────────────────────────────────────────────────────────────
ax.text(
    CX,
    11.4,
    "Nokido — Corps Cognitif",
    ha="center",
    fontsize=15,
    color="#8888ff",
    fontweight="bold",
)
ax.text(
    CX,
    11.15,
    "Analogie biologique · chaque module à sa place · 2026-05-04",
    ha="center",
    fontsize=8,
    color="#444477",
)
ax.text(
    CX,
    1.55,
    "branch alpha · supervisor.ts LaForge-Master · 17 services · 106k chunks RAG",
    ha="center",
    fontsize=7,
    color="#333355",
)

plt.tight_layout(pad=0.1)
out = pathlib.Path(__import__("os").path.expanduser(r"~\Desktop\Nokido_Corps_Anatomique_2026.pdf"))
plt.savefig(
    str(out),
    dpi=200,
    bbox_inches="tight",
    facecolor=BG,
    format="pdf",
    metadata={"Title": "Nokido Corps Anatomique 2026"},
)
plt.close()
print(f"PDF: {out} ({out.stat().st_size // 1024} KB)")
