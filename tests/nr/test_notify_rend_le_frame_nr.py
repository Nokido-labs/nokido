"""NR -- l'accuse de `notify` rend l'identifiant du message et son destinataire REEL (derogation owner 15/10).

Codex, debat anatomie du 15/10 : « l'accuse ne contenait pas d'identifiant unique ; je peux preciser la boite et le
sujet, pas un identifiant ». `handle_notify` calculait le frame (`_first_frame`) puis rendait « OK notification
envoyee » : l'emetteur ne pouvait ni citer son envoi ni prouver sa livraison. Et un message sans destinataire
identifie partait en EVENTBUS_ARCHIVE (personne ne le lit) avec le meme « OK ».

Chemin REEL : la methode est appelee, l'archive ecrit dans une base M2M temporaire ; l'identifiant rendu doit etre
celui qui est en base -- pas seulement une chaine qui ressemble a un identifiant."""
from __future__ import annotations

import asyncio
import re
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

reg = pytest.importorskip("nokido_agent.app.forge_mcp_registry")
dbp = pytest.importorskip("nokido_agent.app.forge_db_path")
mf = pytest.importorskip("nokido_agent.app.forge_message_frame")


@pytest.fixture
def base(monkeypatch, tmp_path):
    chemin = tmp_path / "m2m.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE agent_messages (id TEXT PRIMARY KEY, from_agent TEXT, to_agent TEXT, correlation_id TEXT,"
              " method TEXT, payload TEXT, status TEXT, created_at TEXT)")
    c.commit()
    c.close()
    monkeypatch.setattr(dbp, "open_m2m", lambda timeout=15.0: sqlite3.connect(chemin, timeout=timeout,
                                                                              isolation_level=None))
    monkeypatch.setattr(mf, "INBOX", SimpleNamespace(push=lambda frame: None))
    return chemin


def _notifier(args: dict) -> str:
    moi = SimpleNamespace(state_mgr=SimpleNamespace(add_notification=lambda *a, **k: None), root=ROOT)
    return asyncio.run(reg.ToolRegistry.handle_notify(moi, args, "CLAUDE", 1))


def test_l_accuse_rend_le_frame_ecrit_en_base_et_le_destinataire(base):
    r = _notifier({"message": "[CLAUDE->CODEX] point de test de l'accuse"})
    m = re.search(r"frame=(frm_[0-9a-f]{12})", r)
    assert r.startswith("OK notification envoyee") and m, r
    assert "to=agt_codex" in r, r
    ligne = sqlite3.connect(base).execute("SELECT to_agent FROM agent_messages WHERE id = ?", (m.group(1),)).fetchone()
    assert ligne == ("agt_codex",), "l'identifiant rendu doit etre celui archive en base"


def test_sans_destinataire_l_accuse_dit_que_personne_ne_lira(base):
    r = _notifier({"message": "message sans aucun prefixe de destinataire"})
    assert r.startswith("ARCHIVE SEULEMENT") and "to=EVENTBUS_ARCHIVE" in r and "personne ne lira" in r, r
    assert re.search(r"frame=frm_[0-9a-f]{12}", r), r


def test_le_broadcast_rend_aussi_sa_reference(base):
    r = _notifier({"message": "annonce a tous", "to": "ALL"})
    assert r.startswith("OK broadcast envoye") and re.search(r"frame=frm_[0-9a-f]{12}", r), r
