"""
forge_desktop/widgets/security_shield.py
=========================================
SecurityShield — v17.04-RT
Affiche le statut de chaque clé API depuis win32cred.
Icônes lock/unlock. Refresh à la demande.
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QGroupBox, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor

KEYS = [
    ("GEMINI_API_KEY",   "Gemini",    "✨"),
    ("GROQ_API_KEY",     "Groq",      "⚡"),
    ("XAI_API_KEY",      "xAI Grok",  "𝕏"),
    ("DEEPSEEK_API_KEY", "DeepSeek",  "🐋"),
    ("MISTRAL_API_KEY",  "Mistral",   "🌊"),
    ("HF_TOKEN",         "HuggingFace","🤗"),
    ("GITHUB_TOKEN",     "GitHub",    "⛙"),
    ("CODEBERG_TOKEN",   "Codeberg",  "🌲"),
    ("FORGE_MCP_TOKEN",  "MCP Token", "⚙"),
]

STYLE_LOCKED   = ("background:#1a1a1a; border:1px solid #4caf50; border-radius:6px;"
                  " padding:4px 8px;")
STYLE_MISSING  = ("background:#1a1a1a; border:1px solid #f4433622; border-radius:6px;"
                  " padding:4px 8px;")


def _check_key(key: str) -> tuple[bool, int]:
    """Retourne (found, len) via win32cred."""
    try:
        import win32cred
        cred = win32cred.CredRead(f"{key}@LaForge", win32cred.CRED_TYPE_GENERIC)
        blob = cred.get("CredentialBlob", b"")
        val = blob.decode("utf-16-le","replace").rstrip("\x00") if blob else ""
        return bool(val), len(val)
    except Exception:
        return False, 0


class _KeyCard(QWidget):
    def __init__(self, key: str, label: str, icon: str, parent=None):
        super().__init__(parent)
        self._key = key
        lo = QHBoxLayout(self)
        lo.setContentsMargins(6, 4, 6, 4)
        lo.setSpacing(6)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFixedWidth(18)
        self._icon_lbl.setStyleSheet("font-size:13px;")
        lo.addWidget(self._icon_lbl)

        self._name_lbl = QLabel(label)
        self._name_lbl.setFixedWidth(80)
        self._name_lbl.setStyleSheet("color:#c2c0b6; font-size:11px;")
        lo.addWidget(self._name_lbl)

        lo.addStretch()

        self._status_lbl = QLabel("—")
        self._status_lbl.setStyleSheet("font-size:10px;")
        lo.addWidget(self._status_lbl)

        self._lock_lbl = QLabel("🔒")
        self._lock_lbl.setStyleSheet("font-size:13px;")
        lo.addWidget(self._lock_lbl)

        self.setStyleSheet(STYLE_MISSING)
        self.refresh()

    def refresh(self):
        found, length = _check_key(self._key)
        if found:
            self._status_lbl.setText(f"{length} chars")
            self._status_lbl.setStyleSheet("color:#4caf50; font-size:10px;")
            self._lock_lbl.setText("🔓")
            self.setStyleSheet(STYLE_LOCKED)
        else:
            self._status_lbl.setText("manquant")
            self._status_lbl.setStyleSheet("color:#f44336; font-size:10px;")
            self._lock_lbl.setText("🔒")
            self.setStyleSheet(STYLE_MISSING)
        return found


class SecurityShield(QWidget):
    """
    Panneau sécurité — win32cred status par clé API.
    Icônes 🔓/🔒, refresh manuel et auto (60s).
    """
    security_ok    = Signal(int, int)  # (found, total)
    key_missing    = Signal(str)       # clé manquante

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[_KeyCard] = []
        self._build_ui()

        # Auto-refresh toutes les 60s
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_all)
        self._timer.start(60000)
        QTimer.singleShot(100, self.refresh_all)

    def _build_ui(self):
        lo = QVBoxLayout(self)
        lo.setSpacing(6)
        lo.setContentsMargins(4, 4, 4, 4)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("🛡  Security Shield — win32cred")
        title.setStyleSheet("font-size:13px; font-weight:600; color:#c2c0b6;")
        hdr.addWidget(title)
        hdr.addStretch()
        self._summary_lbl = QLabel("")
        self._summary_lbl.setStyleSheet("font-size:11px;")
        hdr.addWidget(self._summary_lbl)
        btn = QPushButton("↻")
        btn.setFixedSize(22, 22)
        btn.setStyleSheet(
            "background:#1a1a1a; border:1px solid #555; color:#888;"
            " border-radius:4px; font-size:12px;"
        )
        btn.clicked.connect(self.refresh_all)
        hdr.addWidget(btn)
        lo.addLayout(hdr)

        # Grille de cartes — 3 colonnes
        grp = QGroupBox("Clés API — Windows Credential Manager")
        grp.setStyleSheet(
            "QGroupBox { border:1px solid #333; border-radius:6px;"
            " margin-top:6px; color:#666; padding-top:4px; }"
        )
        grid = QGridLayout(grp)
        grid.setSpacing(4)
        for i, (key, label, icon) in enumerate(KEYS):
            card = _KeyCard(key, label, icon)
            self._cards.append(card)
            grid.addWidget(card, i // 3, i % 3)
        lo.addWidget(grp)

    def refresh_all(self):
        found = sum(1 for card in self._cards if card.refresh())
        total = len(self._cards)
        color = "#4caf50" if found == total else ("#ff9800" if found > 0 else "#f44336")
        self._summary_lbl.setText(f"{found}/{total} clés")
        self._summary_lbl.setStyleSheet(f"color:{color}; font-size:11px; font-weight:600;")
        self.security_ok.emit(found, total)
        for card in self._cards:
            found_k, _ = _check_key(card._key)
            if not found_k:
                self.key_missing.emit(card._key)
