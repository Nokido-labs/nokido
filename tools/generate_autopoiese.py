"""
generate_autopoiese.py — Carte Autopoïèse Nokido
Chaque module code → analogie biologique, organisé en cycles de self-production.
Produit : Desktop/Nokido_Autopoiese_2026.pdf
"""

__FORGE_COLOR__ = "observabilite/anatomy : carte autopoiese, module vers analogie biologique"  # organe declare le 2026-09-06 (audit de raccordement)

import matplotlib

matplotlib.use("Agg")
import pathlib

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

# ── Palette ──────────────────────────────────────────────────────────────────
BG = "#06060f"
RING_COL = {
    "SNC": "#1e2d6e",
    "Mémoire": "#1a4a2e",
    "Immun": "#4a1a1a",
    "Végétatif": "#2a2a10",
    "Phase H": "#2d1a4a",
    "Digestif": "#1a3a4a",
    "Locomoteur": "#3a2a10",
    "Sens": "#10302a",
    "Supervisor": "#0d0d0d",
}
TEXT_COL = {
    "SNC": "#8899ff",
    "Mémoire": "#66dd99",
    "Immun": "#ff7777",
    "Végétatif": "#dddd44",
    "Phase H": "#cc88ff",
    "Digestif": "#44ccdd",
    "Locomoteur": "#ddaa44",
    "Sens": "#44ddcc",
    "Supervisor": "#9999cc",
}

# ── Modules par système biologique ──────────────────────────────────────────
SYSTEMS = {
    "Supervisor": [
        ("supervisor.ts", "Cerveau\nreptilien\n(autonomique)"),
        ("LaForge-Master", "PID 1\nprocessus\n-mère"),
    ],
    "SNC": [
        ("nokido_hub.py", "Tronc\ncérébral"),
        ("forge_cognitive_router", "Cortex\npréfrontal"),
        ("forge_spike_router", "Cervelet SNN\n(PyTorch)"),
        ("forge_byte_router", "Moelle\népinière"),
        ("forge_mcp_registry", "Syst. Nerveux\nPériphérique"),
        ("forge_llm_router", "Métabolisme\nneural"),
        ("forge_nlu / intent_parser", "Thalamus\n(tri NLU)"),
        ("proxy_deno/core/brain.ts", "Cervelet\nDeno"),
        ("nervous_system.ts", "Bus neural\nBloodCell"),
    ],
    "Mémoire": [
        ("forge_self_correction", "Hippocampe\n(consolidation)"),
        ("RAG/embeddings.db\n106k chunks", "Cortex\nsensoriel LT"),
        ("brain_worker :5557\nBGE-M3 NPU", "Synapses\nvectorielles"),
        ("forge_rag_engine\nFAISS+BM25+RRF", "Réseau\nsynaptique"),
        ("forge_rag_warmup", "Plasticité\nsynaptique"),
        ("forge_rag_qualify\nLTP", "Potentialis.\nLong Terme"),
        ("forge_knowledge_distiller", "Consolidation\nsommeil"),
        ("forge_thought_interceptor", "Capture CoT\nChaîne de pensée"),
        ("forge_hippocampus", "Index\népisodique"),
    ],
    "Immun": [
        ("forge_semantic_firewall\n4 couches", "Barrière\nhémato-encéph."),
        ("forge_prompt_guard\n15 patterns", "Anticorps\nspécifiques"),
        ("forge_sovereign_membrane\nHMAC aliases", "Membrane\ncellulaire"),
        ("forge_integrity\nIntegrityRing", "Système\nHLA/RBAC"),
        ("SkillGuardian", "Macrophages"),
        ("NoiseGuardian\nforg_silo_fragmenter", "NK cells\nsanitize"),
        ("forge_conv_sanitizer\nDLP", "Complément\nimmunitaire"),
    ],
    "Phase H": [
        ("forge_homeostasis_orchestrator\n5min cycle", "Hypothalamus"),
        ("forge_autonomous_loops\n7 patterns circadiens", "Horloge\ncircadienne"),
        ("forge_coagulation_cascade", "Cascade\ncoagulation"),
        ("forge_hebbian_linker", "Plasticité\nHebbienne"),
        ("forge_endocrine", "Syst.\nEndocrinien"),
        ("forge_renal_clearance", "Reins\n(épuration)"),
        ("forge_immune_adaptive", "Immunité\nadaptative"),
        ("forge_pluripotent_workers", "Cellules\nsouches"),
    ],
    "Végétatif": [
        ("forge_inspector", "Bulbe\nrachidien"),
        ("forge_idle_watchdog", "Sympathique\n(alerte)"),
        ("forge_provider_watcher", "Parasympathique\n(boot)"),
        ("forge_ping_monitor", "Chémorécepteurs\n(monitoring)"),
    ],
    "Digestif": [
        ("/ingest/url /ingest/bulk", "Bouche\nœsophage"),
        ("forge_ingest_self\nMarkdownChunker", "Estomac\n(broyage)"),
        ("forge_rag_qualify\nabsorption", "Intestin grêle\n(absorption)"),
        ("forge_secret_guard\nDLP redact", "Foie\n(détox)"),
        ("forge_rag_store\nengrams", "Pancréas\n(sécrétion index)"),
    ],
    "Locomoteur": [
        ("forge_silo_engine\n7 SiloDomain", "Muscles\nstriés"),
        ("forge_runtime", "Squelette"),
        ("forge_runner\nmmap IPC", "Tendons\n(IPC)"),
        ("forge_orchestrator", "Syst. moteur\ncortex"),
        ("forge_message_frame\nforge_broker_base", "Articulations"),
    ],
    "Sens": [
        ("forge_browser_tool\nforge_crawl_tool", "Vision\n(web)"),
        ("MCP STDIO bridge\nClaude Desktop", "Ouïe\n(clients)"),
        ("netcfg PTY SSH", "Toucher\n(effecteur)"),
        ("forge_wasm_cervelet\nDeno WASM :7401", "Myéline\n(isolation)"),
        ("laforge-cervelet\nwasmedge :55555", "Cervelet\nextérocept."),
    ],
}

# ── Cycles autopoïèse (flèches entre systèmes) ────────────────────────────
CYCLES = [
    # (from_system, to_system, label, color)
    ("Sens", "Digestif", "données brutes", "#4499ff"),
    ("Digestif", "Mémoire", "chunks indexés", "#44ff99"),
    ("Mémoire", "SNC", "contexte vectoriel", "#9944ff"),
    ("SNC", "Locomoteur", "intent → action", "#ffaa44"),
    ("Locomoteur", "Sens", "percepts nouveaux", "#ff4499"),
    ("Phase H", "Mémoire", "anchor RAG", "#cc44ff"),
    ("Phase H", "SNC", "homéostasie", "#ff88cc"),
    ("Immun", "SNC", "filtrage sécurité", "#ff4444"),
    ("Supervisor", "Végétatif", "spawn + watch", "#6666aa"),
    ("Végétatif", "SNC", "signaux vitaux", "#aaaa44"),
    ("Mémoire", "Phase H", "consolidation", "#44ddaa"),
]

# ── Layout : anneaux concentriques ────────────────────────────────────────
fig, ax = plt.subplots(figsize=(28, 28), facecolor=BG)
ax.set_facecolor(BG)
ax.set_xlim(-11, 11)
ax.set_ylim(-11, 11)
ax.axis("off")

# Rayon par anneau
RING_R = {
    "Supervisor": 1.5,
    "SNC": 3.2,
    "Mémoire": 5.0,
    "Phase H": 6.6,
    "Immun": 7.8,
    "Végétatif": 8.8,
    "Digestif": 9.5,
    "Locomoteur": 10.2,
    "Sens": 10.8,
}

node_positions = {}  # system -> [(x,y), ...]

for sys_name, modules in SYSTEMS.items():
    r = RING_R[sys_name]
    n = len(modules)
    # offset angle per system to avoid overlap
    offset = {
        "Supervisor": 0,
        "SNC": 0,
        "Mémoire": 20,
        "Phase H": 10,
        "Immun": 5,
        "Végétatif": 15,
        "Digestif": 25,
        "Locomoteur": 35,
        "Sens": 45,
    }.get(sys_name, 0)
    angles = [np.radians(offset + i * 360 / n) for i in range(n)]
    positions = [(r * np.cos(a), r * np.sin(a)) for a in angles]
    node_positions[sys_name] = positions

    # Draw ring arc
    theta = np.linspace(0, 2 * np.pi, 300)
    ax.plot(
        r * np.cos(theta),
        r * np.sin(theta),
        color=TEXT_COL[sys_name],
        alpha=0.12,
        linewidth=1.5,
        linestyle="--",
    )

    # Draw nodes
    col_bg = RING_COL[sys_name]
    col_tx = TEXT_COL[sys_name]
    box_r = 0.55 if r < 4 else 0.65 if r < 7 else 0.72

    for (x, y), (code, bio) in zip(positions, modules):
        # Box
        fancy = FancyBboxPatch(
            (x - box_r, y - box_r * 0.9),
            2 * box_r,
            2 * box_r * 0.9,
            boxstyle="round,pad=0.05",
            facecolor=col_bg,
            edgecolor=col_tx,
            linewidth=1.2,
            alpha=0.92,
            zorder=3,
        )
        ax.add_patch(fancy)
        # Code name (small)
        ax.text(
            x,
            y + 0.1,
            code,
            ha="center",
            va="center",
            fontsize=4.5,
            color="#ccccee",
            zorder=4,
            fontfamily="monospace",
            wrap=True,
        )
        # Bio name (bold)
        ax.text(
            x,
            y - 0.3,
            bio,
            ha="center",
            va="center",
            fontsize=5.5,
            color=col_tx,
            zorder=4,
            fontweight="bold",
            linespacing=1.1,
        )

    # System label on ring
    label_a = np.radians(offset + (360 / n) * (n / 2 + 0.5))
    lx = (r + 0.35) * np.cos(label_a)
    ly = (r + 0.35) * np.sin(label_a)
    ax.text(
        lx,
        ly,
        sys_name.upper(),
        ha="center",
        va="center",
        fontsize=7,
        color=TEXT_COL[sys_name],
        fontweight="bold",
        alpha=0.7,
        zorder=5,
    )


# ── Cycles autopoïèse : flèches inter-systèmes ───────────────────────────
def system_center(sys_name):
    r = RING_R[sys_name]
    return (r * 0.5, 0)  # simplified: point on ring


def avg_pos(positions):
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    return (np.mean(xs), np.mean(ys))


for from_s, to_s, label, color in CYCLES:
    p1 = avg_pos(node_positions[from_s])
    p2 = avg_pos(node_positions[to_s])
    ax.annotate(
        "",
        xy=p2,
        xytext=p1,
        arrowprops=dict(
            arrowstyle="->",
            color=color,
            alpha=0.55,
            lw=1.5,
            connectionstyle="arc3,rad=0.3",
        ),
        zorder=2,
    )
    mx = (p1[0] + p2[0]) / 2
    my = (p1[1] + p2[1]) / 2
    ax.text(
        mx,
        my,
        label,
        ha="center",
        va="center",
        fontsize=4,
        color=color,
        alpha=0.8,
        bbox=dict(facecolor=BG, edgecolor="none", alpha=0.7, pad=1),
        zorder=6,
    )

# ── Centre : titre autopoïèse ─────────────────────────────────────────────
ax.text(
    0,
    0.5,
    "Nokido",
    ha="center",
    va="center",
    fontsize=18,
    color="#9999ff",
    fontweight="bold",
    zorder=10,
)
ax.text(
    0,
    -0.2,
    "A U T O P O Ï È S E",
    ha="center",
    va="center",
    fontsize=10,
    color="#5555aa",
    fontweight="bold",
    zorder=10,
)
ax.text(0, -0.7, "2026-05-04", ha="center", va="center", fontsize=6, color="#333366", zorder=10)
ax.text(
    0,
    -1.0,
    "Corps Cognitif Auto-Producteur",
    ha="center",
    va="center",
    fontsize=5.5,
    color="#444488",
    style="italic",
    zorder=10,
)

# ── Légende cycles ────────────────────────────────────────────────────────
legend_patches = []
for from_s, to_s, label, color in CYCLES[:6]:
    legend_patches.append(mpatches.Patch(color=color, label=f"{from_s}→{to_s}: {label}"))
ax.legend(
    handles=legend_patches,
    loc="lower right",
    fontsize=5,
    facecolor="#0a0a1a",
    edgecolor="#333366",
    labelcolor="white",
    framealpha=0.85,
    bbox_to_anchor=(1.0, -0.02),
)

# ── Export ────────────────────────────────────────────────────────────────
out = pathlib.Path(__import__("os").path.expanduser(r"~\Desktop\Nokido_Autopoiese_2026.pdf"))
plt.tight_layout(pad=0)
plt.savefig(str(out), dpi=200, bbox_inches="tight", facecolor=BG, format="pdf")
plt.close()
print(f"PDF: {out} ({out.stat().st_size // 1024} KB)")
