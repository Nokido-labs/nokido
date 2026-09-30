"""
forge_desktop/views/interaction_view.py
========================================
Vue Interactions multi-agents — arbre de sélection guidé.
Mode → agents selon les slots requis → lancement.
MCP toujours connecté. MASTER_DEV affiché dans le titre.
"""
from __future__ import annotations
import asyncio
import copy
import time
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPlainTextEdit, QPushButton,
    QLineEdit, QComboBox, QGroupBox,
    QSizePolicy, QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QColor, QFont

ROOT = Path(__file__).resolve().parent.parent.parent

# ── Couleurs agents ────────────────────────────────────────────────────────────
AGENT_COLORS = {
    "laforge":      "#2196f3",
    "llamacpp":     "#ff9800",
    "llamacpp_2":   "#f44336",
    "gemini":       "#4caf50",
    "CLAUDE":       "#00bcd4",
    "CLINE_PLAN":   "#00bcd4",
    "CLINE_ACT":    "#009688",
    "groq":         "#ff5722",
    "deepseek":     "#795548",
    "mistral":      "#607d8b",
}

def _color(agent_id: str) -> str:
    for k, v in AGENT_COLORS.items():
        if k.lower() in agent_id.lower():
            return v
    return "#888"

DARK = ("background:#0a0a0a; color:#c2c0b6;"
        " font-family:'Cascadia Code','Consolas'; font-size:11px;"
        " border:1px solid #333; border-radius:4px;")

# ── Définition des modes ───────────────────────────────────────────────────────
MODES = {
    "debat":      {"label": "⚖  Débat",           "slots": ["Planificateur", "Critique"],        "turns": False},
    "ping_pong":  {"label": "🏓  Ping-Pong",        "slots": ["Agent A", "Agent B"],               "turns": True},
    "chef":       {"label": "👑  Chef / Exécutant", "slots": ["Chef", "Exécutant"],                "turns": False},
    "swarm":      {"label": "🐝  Swarm",            "slots": ["Agent 1","Agent 2","Agent 3","Agent 4"], "turns": True},
    "chain":      {"label": "⛓  Chain",            "slots": ["Agent 1","Agent 2","Agent 3"],      "turns": False},
    "parallel":   {"label": "⚡  Parallel",         "slots": ["Agent 1","Agent 2","Agent 3"],      "turns": False},
    "auto":       {"label": "🤖  Auto",             "slots": ["Agent principal"],                   "turns": False},
    "direct_dev": {"label": "🔓  Direct Dev",       "slots": ["Agent dev"],                         "turns": False, "requires_master": True},
    "rag_collab": {"label": "📚  RAG Collab",       "slots": ["Générateur","Validateur"],           "turns": False},
}

# ── Matrice compatibilité agents ──────────────────────────────────────────────
# Basée sur les capacités réelles : taille modèle, spécialisation, instruction following
AGENT_MATRIX = {
    "Planificateur":  {"rec": ["laforge","qwen3_8b","gemini","groq_70b","xai_grok","mistral_direct","deepseek_direct","nokido_mcp"],   "avoid": ["starcoder2_latest","tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b","deepseek_coder_6_7b"]},
    "Critique":       {"rec": ["qwen3_8b","gemini","groq_70b","xai_grok","mistral_direct","deepseek_direct","nokido_mcp"],               "avoid": ["starcoder2_latest","tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
    "Chef":           {"rec": ["laforge","qwen3_8b","gemini","groq_70b","xai_grok","nokido_mcp"],                                        "avoid": ["starcoder2_latest","tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b","deepseek_coder"]},
    "Exécutant":      {"rec": ["llamacpp","ollama_qwen2_5_coder_latest","deepseek_direct","groq_direct","ollama_qwen3_8b"],                 "avoid": ["tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
    "Agent A":        {"rec": ["laforge","qwen3_8b","llamacpp","gemini","groq_70b"],                                                       "avoid": ["tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
    "Agent B":        {"rec": ["llamacpp","qwen3_8b","groq_70b","xai_grok","deepseek_direct"],                                            "avoid": ["tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
    "Générateur":     {"rec": ["laforge","qwen3_8b","gemini","groq_70b","deepseek_direct","xai_grok"],                                    "avoid": ["starcoder2_latest","deepseek_coder","tinyllama_1_1b"]},
    "Validateur":     {"rec": ["qwen3_8b","gemini","groq_70b","xai_grok","nokido_mcp","mistral_direct"],                                 "avoid": ["starcoder2_latest","tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
    "Agent dev":      {"rec": ["nokido_mcp","laforge","ollama_qwen2_5_coder_latest","deepseek_direct","groq_70b"],                        "avoid": ["tinyllama_1_1b","multiagent","gemini","xai_grok"]},
    "Agent principal":{"rec": ["laforge","qwen3_8b","gemini","groq_70b","xai_grok","nokido_mcp"],                                        "avoid": ["tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
    "Agent 1":        {"rec": ["laforge","qwen3_8b","gemini","groq_70b","llamacpp"],                                                       "avoid": ["tinyllama_1_1b","multiagent"]},
    "Agent 2":        {"rec": ["llamacpp","qwen3_8b","groq_70b","xai_grok","deepseek_direct"],                                            "avoid": ["tinyllama_1_1b","multiagent"]},
    "Agent 3":        {"rec": ["gemini","groq_70b","xai_grok","nokido_mcp","qwen3_8b"],                                                  "avoid": ["tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
    "Agent 4":        {"rec": ["xai_grok","groq_70b","gemini","nokido_mcp"],                                                              "avoid": ["tinyllama_1_1b","multiagent","qwen2_5_coder_1_5b"]},
}

def _compat_score(slot_name: str, pid: str) -> int:
    """Retourne 2=recommandé 1=ok 0=déconseillé."""
    matrix = AGENT_MATRIX.get(slot_name, {})
    pid_key = pid.replace(":","_").replace(".","_").replace("-","_").replace("/","_")
    # Check recommandé
    if any(r in pid_key or pid_key in r for r in matrix.get("rec", [])):
        return 2
    # Check éviter
    if any(a in pid_key or pid_key in a for a in matrix.get("avoid", [])):
        return 0
    return 1


# ── Worker ─────────────────────────────────────────────────────────────────────

class InteractionWorker(QThread):
    turn_ready    = Signal(str, str, int)
    scenario_done = Signal(dict)

    def __init__(self, scenario: str, topic: str,
                 agents: list, turns: int, parent=None):
        super().__init__(parent)
        self._scenario = scenario
        self._topic    = topic
        self._agents   = agents
        self._turns    = turns

    def run(self):
        if str(ROOT / "app") not in sys.path:
            sys.path.insert(0, str(ROOT / "app"))

        scenario = self._scenario
        try:
            if scenario in ("debat","ping_pong","chef","swarm","chain","parallel","auto","direct_dev"):
                import forge_swarm_team as _fst

                async def _run():
                    team = _fst._default_team()
                    seen = {}
                    for pid in self._agents:
                        if not pid:
                            continue
                        if pid not in seen:
                            team.activate(pid)
                            seen[pid] = 1
                        else:
                            base = next((p for p in team.participants if p.id == pid), None)
                            if base:
                                clone = copy.deepcopy(base)
                                clone.id = pid + f"_{seen[pid]+1}"
                                clone.config = dict(base.config)
                                clone.config["system"] = "Tu es un critique. Identifie les failles."
                                clone.active = True
                                team.participants.append(clone)
                            seen[pid] += 1

                    if scenario == "direct_dev":
                        import json as _j, time as _t
                        state = _j.loads((ROOT/"config"/"authority_state.json").read_text(encoding="utf-8"))
                        md = state.get("master_dev", {})
                        now = _t.time()
                        last = md.get("last_beat") or md.get("acquired_at") or 0
                        if md.get("agent_id") != "CLAUDE" or (now - last) > md.get("ttl", 1800):
                            return [("SYSTEM", "Mode Direct Dev: MASTER_DEV=CLAUDE requis.", 0)]

                    orc = _fst.LeadOrchestrator()
                    res = await orc.run(self._topic, team, context="")
                    return [(r["participant_id"], str(r.get("response","")), i+1)
                            for i, r in enumerate(res.get("results", []))]

                loop = asyncio.new_event_loop()
                turns = loop.run_until_complete(_run())
                loop.close()

                for agent_id, content_text, turn_n in turns:
                    self.turn_ready.emit(agent_id, content_text, turn_n)
                self.scenario_done.emit({
                    "scenario": scenario, "agents": self._agents,
                    "elapsed": 0, "ok": True,
                    "summary": f"{len(turns)} tours", "turns": len(turns),
                })

            else:
                from forge_interaction_test import run_scenario
                result = asyncio.run(run_scenario(
                    name=scenario, topic=self._topic,
                    agents=self._agents, turns=self._turns,
                ))
                for msg in result.turns:
                    self.turn_ready.emit(msg.agent_id, msg.content, msg.turn)
                self.scenario_done.emit({
                    "scenario": result.scenario, "agents": result.agents,
                    "elapsed": result.elapsed_ms, "ok": result.ok,
                    "summary": result.summary, "turns": len(result.turns),
                })

        except Exception as e:
            import traceback
            self.scenario_done.emit({
                "scenario": scenario, "agents": self._agents,
                "elapsed": 0, "ok": False,
                "summary": "", "error": str(e)[:300], "turns": 0,
            })


# ── Vue principale ─────────────────────────────────────────────────────────────

class InteractionView(QWidget):
    """Vue Interactions — arbre guidé Mode→Agents→Lancer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: InteractionWorker | None = None
        self._providers: list = []  # [(pid, label, available)]
        self._slot_combos: list[QComboBox] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Titre + badge MASTER_DEV ─────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("⚡  Interactions multi-agents")
        title.setStyleSheet("font-size:14px; font-weight:600; color:#c2c0b6;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._master_badge = QLabel("")
        self._master_badge.setStyleSheet("font-size:11px; font-weight:700; padding:2px 8px;"
                                          " border-radius:4px;")
        hdr.addWidget(self._master_badge)
        layout.addLayout(hdr)

        # ── Sélection du mode ─────────────────────────────────────────────────
        mode_grp = QGroupBox("1. Mode de collaboration")
        mode_grp.setStyleSheet(
            "QGroupBox { border:1px solid #444; border-radius:6px;"
            " margin-top:6px; color:#888; padding-top:4px; }"
        )
        mode_lo = QVBoxLayout(mode_grp)
        self._mode_sel = QComboBox()
        self._mode_sel.setStyleSheet(
            "background:#111; color:#c2c0b6; border:1px solid #555;"
            " border-radius:4px; padding:4px 8px; font-size:12px;"
        )
        for key, info in MODES.items():
            self._mode_sel.addItem(info["label"], key)
        self._mode_sel.currentIndexChanged.connect(self._on_mode_changed)
        mode_lo.addWidget(self._mode_sel)

        # Description du mode
        self._mode_desc = QLabel("")
        self._mode_desc.setStyleSheet("color:#666; font-size:10px; padding:2px 4px;")
        self._mode_desc.setWordWrap(True)
        mode_lo.addWidget(self._mode_desc)
        layout.addWidget(mode_grp)

        # ── Slots agents ──────────────────────────────────────────────────────
        self._slots_grp = QGroupBox("2. Agents")
        self._slots_grp.setStyleSheet(
            "QGroupBox { border:1px solid #2196f3; border-radius:6px;"
            " margin-top:6px; color:#2196f3; padding-top:4px; }"
        )
        self._slots_lo = QVBoxLayout(self._slots_grp)
        layout.addWidget(self._slots_grp)

        # ── Topic ─────────────────────────────────────────────────────────────
        task_grp = QGroupBox("3. Tâche / Question")
        task_grp.setStyleSheet(
            "QGroupBox { border:1px solid #444; border-radius:6px;"
            " margin-top:6px; color:#888; padding-top:4px; }"
        )
        task_lo = QVBoxLayout(task_grp)
        self._topic_input = QLineEdit()
        self._topic_input.setPlaceholderText("Décris la tâche à soumettre aux agents…")
        self._topic_input.setStyleSheet(
            "background:#111; border:1px solid #555; border-radius:4px;"
            " padding:6px 8px; color:#c2c0b6; font-size:12px;"
        )
        task_lo.addWidget(self._topic_input)
        layout.addWidget(task_grp)

        # ── Bouton lancer ─────────────────────────────────────────────────────
        self._run_btn = QPushButton("▶  Lancer")
        self._run_btn.setFixedHeight(36)
        self._run_btn.setStyleSheet(
            "background:#1a3a1a; border:2px solid #4caf50; color:#4caf50;"
            " border-radius:6px; font-size:13px; font-weight:600;"
        )
        self._run_btn.clicked.connect(self._run)

        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setFixedHeight(36)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setStyleSheet(
            "background:#1a1a1a; border:1px solid #f44336; color:#f44336;"
            " border-radius:6px; font-size:12px;"
        )
        self._stop_btn.clicked.connect(self._stop)

        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(self._run_btn)
        ctrl_row.addWidget(self._stop_btn)
        layout.addLayout(ctrl_row)

        # ── Log output ────────────────────────────────────────────────────────
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setStyleSheet(DARK + " min-height:150px;")
        layout.addWidget(self._log, 1)

        # ── Init ──────────────────────────────────────────────────────────────
        self._load_providers()
        self._on_mode_changed(0)

        # Timer gouvernance — refresh toutes les 30s
        self._gov_timer = QTimer(self)
        self._gov_timer.timeout.connect(self._refresh_governance)
        self._gov_timer.start(30000)
        self._refresh_governance()

    # ── Providers ─────────────────────────────────────────────────────────────

    def _load_providers(self):
        """Charge tous les providers depuis _default_team + détection runtime."""
        import urllib.request as _ur, json as _j, os as _os, sys as _sys
        if str(ROOT / "app") not in _sys.path:
            _sys.path.insert(0, str(ROOT / "app"))

        providers = []

        # llamacpp — test dispo
        llamacpp_ok = False
        try:
            from forge_llamacpp import LlamaCppBridge
            b = LlamaCppBridge()
            llamacpp_ok = b.is_available()
            model = Path(b.model_path).stem[:24] if b.model_path else "llamacpp"
            providers.append(("llamacpp", f"⚡ LlamaCPP ({model})", llamacpp_ok))
        except Exception:
            providers.append(("llamacpp", "⚡ LlamaCPP", False))

        # Ollama — tous les modèles détectés dynamiquement
        try:
            resp = _ur.urlopen("http://localhost:11434/api/tags", timeout=3)
            data = _j.loads(resp.read())
            skip = ["embed", "bge", "nomic"]
            for m in data.get("models", []):
                mname = m["name"]
                if any(x in mname for x in skip):
                    continue
                if mname == "qwen2.5-coder:latest":
                    providers.append(("laforge", f"⚒ Nokido ({mname})", True))
                else:
                    pid = "ollama_" + mname.replace(":","_").replace(".","_").replace("-","_")
                    providers.append((pid, f"🦙 {mname}", True))
        except Exception:
            providers.append(("laforge", "⚒ Nokido (Ollama)", True))

        # Charger les clés depuis keyring (forge_secrets) puis os.environ
        def _get_key(name):
            val = _os.environ.get(name, "").strip()
            if val:
                return val
            try:
                from forge_secrets import get_secret
                return get_secret(name) or ""
            except Exception:
                return ""

        gemini_ok     = bool(_get_key("GEMINI_API_KEY"))
        groq_ok       = bool(_get_key("GROQ_API_KEY"))
        xai_ok        = bool(_get_key("XAI_API_KEY"))
        mistral_ok    = bool(_get_key("MISTRAL_API_KEY"))
        deepseek_ok   = bool(_get_key("DEEPSEEK_API_KEY"))
        hf_ok         = bool(_get_key("HF_TOKEN"))

        def _tag(ok): return "" if ok else " [clé manquante]"

        # Cloud — Gemini
        providers.append(("gemini",         "✨ Gemini 2.5 Flash"      + _tag(gemini_ok),   gemini_ok))

        # Cloud — Groq (2 modèles)
        providers.append(("groq_direct",    "⚡ Groq Llama3.1 8B"      + _tag(groq_ok),     groq_ok))
        providers.append(("groq_70b",       "⚡ Groq Llama3.3 70B"     + _tag(groq_ok),     groq_ok))

        # Cloud — xAI
        providers.append(("xai_grok",       "𝕏 xAI Grok-3 Mini"       + _tag(xai_ok),      xai_ok))

        # Cloud — Mistral
        providers.append(("mistral_direct", "🌊 Mistral Small Direct"  + _tag(mistral_ok),  mistral_ok))

        # Cloud — DeepSeek
        providers.append(("deepseek",       "🐋 DeepSeek V3/Coder"     + _tag(deepseek_ok), deepseek_ok))

        # Cloud — HuggingFace
        providers.append(("hf_qwen",        "🤗 HF Qwen2.5-Coder 32B" + _tag(hf_ok),       hf_ok))

        # Ring 8 router (cascade auto — utilise les clés disponibles)
        providers.append(("groq",    "🔄 Ring8 — Groq fast",    groq_ok))
        providers.append(("mistral", "🔄 Ring8 — Mistral EU",   mistral_ok))

        # Agents MCP / locaux
        providers.append(("nokido_mcp", "⚙ Nokido MCP (One-MCP)",   True))
        providers.append(("CLINE_PLAN",  "🏗 Cline Planificateur",      False))
        providers.append(("CLINE_ACT",   "🏗 Cline Acteur",             False))

        # LiteLLM gateway
        providers.append(("litellm",  "🔀 LiteLLM Gateway",            True))

        # Ollama Remote (Freebox)
        providers.append(("ollama_remote", "🌐 Ollama Remote (Freebox)", False))

        self._providers = providers

    # ── Mode changed ──────────────────────────────────────────────────────────

    def _on_mode_changed(self, idx):
        mode_key = self._mode_sel.currentData()
        if not mode_key:
            return
        info = MODES[mode_key]
        slots = info["slots"]

        # Description
        descs = {
            "debat":      "Deux agents débattent — Planificateur propose, Critique identifie les failles.",
            "ping_pong":  "Échange alterné entre deux agents sur N tours.",
            "chef":       "Le Chef orchestre, l'Exécutant implémente.",
            "swarm":      "Tous les agents sélectionnés répondent en parallèle.",
            "chain":      "Réponse enrichie en cascade — chaque agent s'appuie sur le précédent.",
            "parallel":   "Tous les agents répondent simultanément sans contexte partagé.",
            "auto":       "Nokido détecte automatiquement le meilleur modèle pour la tâche.",
            "direct_dev": "Mode développeur direct — requiert MASTER_DEV=CLAUDE actif.",
            "rag_collab": "Génération RAG + validation — le Validateur vérifie les sources.",
        }
        self._mode_desc.setText(descs.get(mode_key, ""))

        # Vider les slots précédents
        while self._slots_lo.count():
            item = self._slots_lo.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._slot_combos.clear()

        # Créer un ComboBox par slot
        for slot_name in slots:
            row = QHBoxLayout()
            lbl = QLabel(slot_name + " :")
            lbl.setFixedWidth(110)
            lbl.setStyleSheet("color:#c2c0b6; font-size:11px;")
            row.addWidget(lbl)

            sel = QComboBox()
            sel.setStyleSheet(
                "background:#111; color:#c2c0b6; border:1px solid #555;"
                " border-radius:4px; padding:3px 8px; font-size:11px;"
            )

            # Trier les providers par compatibilité : rec(2) > ok(1) > avoid(0)
            sorted_providers = sorted(
                self._providers,
                key=lambda x: (_compat_score(slot_name, x[0]), int(x[2])),
                reverse=True
            )

            best_pid = None
            for pid, label, avail in sorted_providers:
                score = _compat_score(slot_name, pid)
                if score == 2:
                    prefix = "★ "    # recommandé
                elif score == 0:
                    prefix = "✗ "    # déconseillé
                else:
                    prefix = "  "    # ok

                display = prefix + (label if avail else f"[off] {label}")
                sel.addItem(display, pid)

                item_idx = sel.count() - 1
                if not avail:
                    sel.model().item(item_idx).setEnabled(False)
                if score == 0:
                    from PySide6.QtGui import QColor as _QC
                    sel.model().item(item_idx).setForeground(_QC("#555"))

                # Premier recommandé disponible = défaut
                if best_pid is None and score == 2 and avail:
                    best_pid = pid

            # Appliquer le défaut
            if best_pid:
                for i in range(sel.count()):
                    if sel.itemData(i) == best_pid:
                        sel.setCurrentIndex(i)
                        break

            # Tooltip compatibilité
            matrix = AGENT_MATRIX.get(slot_name, {})
            tip = (f"Rôle : {slot_name}\n"
                   f"★ Recommandés : {', '.join(matrix.get('rec',[])[:5])}\n"
                   f"✗ Déconseillés : {', '.join(matrix.get('avoid',[])[:4])}")
            sel.setToolTip(tip)

            row.addWidget(sel, 1)
            self._slot_combos.append(sel)
            self._slots_lo.addLayout(row)

        # Warn si direct_dev
        if info.get("requires_master"):
            warn = QLabel("⚠ Requiert MASTER_DEV=CLAUDE actif (voir badge en haut)")
            warn.setStyleSheet("color:#ff9800; font-size:10px; padding:2px 4px;")
            self._slots_lo.addWidget(warn)

    # ── Gouvernance ───────────────────────────────────────────────────────────

    def _refresh_governance(self):
        import json as _j, time as _t
        try:
            state = _j.loads((ROOT / "config" / "authority_state.json")
                             .read_text(encoding="utf-8"))
            md    = state.get("master_dev", {})
            agent = md.get("agent_id") or "—"
            now   = _t.time()
            last  = md.get("last_beat") or md.get("acquired_at") or 0
            ttl   = md.get("ttl", 1800)
            expired = (now - last) > ttl
            orcs  = state.get("orchestrators", [])

            if agent == "CLAUDE" and not expired:
                remaining = int(ttl - (now - last))
                h, m = divmod(remaining // 60, 60)
                self._master_badge.setText(
                    f"🔓 MASTER_DEV=CLAUDE  {h}h{m:02d}m"
                )
                self._master_badge.setStyleSheet(
                    "color:#0a0a0a; background:#4caf50; font-size:11px;"
                    " font-weight:700; padding:3px 10px; border-radius:4px;"
                )
            else:
                self._master_badge.setText(
                    f"🔒 MASTER_DEV={agent}{'  expiré' if expired else ''}"
                )
                self._master_badge.setStyleSheet(
                    "color:#c2c0b6; background:#333; font-size:11px;"
                    " font-weight:600; padding:3px 10px; border-radius:4px;"
                )
        except Exception as e:
            self._master_badge.setText("gouvernance ?")

    # ── Run / Stop ────────────────────────────────────────────────────────────

    def _run(self):
        topic = self._topic_input.text().strip()
        if not topic:
            self._log.appendPlainText("[WARN] Renseigne la tâche avant de lancer.")
            return
        if self._worker and self._worker.isRunning():
            return

        mode_key = self._mode_sel.currentData()
        agents   = [sel.currentData() for sel in self._slot_combos if sel.currentData()]
        turns    = 4

        self._log.clear()

        # ── Guard isolation llamacpp ─────────────────────────────────────
        llamacpp_count = sum(1 for a in agents if a and "llamacpp" in a)
        ollama_count   = sum(1 for a in agents if a and ("laforge" in a or "ollama" in a))
        if llamacpp_count > 1:
            self._log.appendPlainText(
                "⚠ ISOLATION: LlamaCPP assigné à plusieurs slots.\n"
                "  → Exécution forcée en séquentiel (pas de parallélisme VRAM).\n"
            )
        if llamacpp_count >= 1 and ollama_count >= 1:
            self._log.appendPlainText(
                "⚠ ISOLATION: LlamaCPP + Ollama simultanés.\n"
                "  → GPU layers LlamaCPP réduits automatiquement à 5 max.\n"
            )

        self._log.appendPlainText(
            f"[START] mode={mode_key}  agents={agents}\n"
            f"        tâche={topic[:80]}\n"
            f"{'─'*60}"
        )

        self._worker = InteractionWorker(mode_key, topic, agents, turns, parent=self)
        self._worker.turn_ready.connect(self._on_turn)
        self._worker.scenario_done.connect(self._on_done)
        self._worker.start()

        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._log.appendPlainText("[STOP] Arrêt demandé.")
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _on_turn(self, agent_id: str, text: str, turn_n: int):
        col = _color(agent_id)
        self._log.appendPlainText(f"\n[T{turn_n}] {agent_id}\n{text[:500]}")

    def _on_done(self, result: dict):
        ok = result.get("ok", False)
        turns = result.get("turns", 0)
        err = result.get("error", "")
        self._log.appendPlainText(
            f"\n{'─'*60}\n"
            f"[DONE] {'OK' if ok else 'ERR'}  {turns} tours"
            + (f"\n[ERR] {err}" if err else "")
        )
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
