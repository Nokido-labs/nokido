"""NR -- le tray montre le corps REEL (demande owner 15/10 : « le mode, les agents utilises -- dynamiques, avec leur
provenance exacte -- et les ordres ne s'affichent pas »).

Avant : la liste d'agents venait d'un fichier d'etat FIGE (CLAUDE, CLINE_PLAN, CLINE_ACT, test_agent), le mode DEV et
l'autorite etaient lus mais jamais affiches, les ordres n'apparaissaient qu'en erreur. Le tray (pystray, coffre) n'est
pas importe : on teste les organes qu'il appelle, et sa source."""
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ordres_bureau as ob  # noqa: E402
import forge_presence as fp  # noqa: E402

IDS = {
    "CLAUDE": {"ring": 1, "kind": "cli_agent", "surface": "interactive", "channel": "STDIO_CLAUDE",
               "transport": "http", "machine": "local", "aliases": ["CLAUDE_CODE"]},
    "STATE_ENCODER": {"ring": 3, "kind": "daemon", "surface": "internal", "channel": "INTERNAL_HUB",
                      "transport": "internal", "machine": "local"},
}


def _presence(tmp_path, now):
    porte = tmp_path / "presence"
    porte.mkdir()
    (porte / "CLAUDE.seen").write_text(json.dumps({"ts": now - 5}), encoding="utf-8")
    (porte / "STATE_ENCODER.seen").write_text(json.dumps({"ts": now - 60}), encoding="utf-8")
    (porte / "VIEUX.seen").write_text(json.dumps({"ts": now - 7200}), encoding="utf-8")
    # empreinte du hub (heure locale naive, comme `datetime.now().isoformat()`) : ring, outil, client mesure
    (tmp_path / "presence_claude.seen").write_text(json.dumps({
        "agent": "CLAUDE", "ring": 1, "ts": datetime.fromtimestamp(now - 2).isoformat(), "last_tool": "run",
        "client": "127.0.0.1", "reseau": "local"}), encoding="utf-8")
    (tmp_path / "presence_inconnu.seen").write_text(json.dumps({
        "agent": "INCONNU", "ring": 4, "ts": datetime.fromtimestamp(now - 30).isoformat()}), encoding="utf-8")
    return porte


def test_presence_fusionne_les_deux_empreintes_avec_la_provenance(tmp_path):
    now = time.time()
    porte = _presence(tmp_path, now)
    e = {x["agent"]: x for x in fp.etat_presence(900, maintenant=now, identites=IDS, dossier=porte)}
    assert set(e) == {"CLAUDE", "STATE_ENCODER", "INCONNU"}          # VIEUX hors fenetre
    c = e["CLAUDE"]
    assert c["age_s"] < 3 and c["dernier_outil"] == "run" and c["client"] == "127.0.0.1"   # le plus recent gagne
    assert c["declare"] and c["canal"] == "STDIO_CLAUDE" and c["interlocuteur"] is True
    assert e["STATE_ENCODER"]["interlocuteur"] is False                 # organe interne, range a part
    inc = e["INCONNU"]
    assert inc["declare"] is False and inc["interlocuteur"] is True     # non declare : montre, jamais cache


def test_presence_trie_par_recence_et_resout_les_alias(tmp_path):
    now = time.time()
    porte = tmp_path / "presence"
    porte.mkdir()
    (porte / "CLAUDE_CODE.seen").write_text(json.dumps({"ts": now - 1}), encoding="utf-8")
    (porte / "STATE_ENCODER.seen").write_text(json.dumps({"ts": now - 50}), encoding="utf-8")
    r = fp.etat_presence(900, maintenant=now, identites=IDS, dossier=porte)
    assert [x["agent"] for x in r] == ["CLAUDE_CODE", "STATE_ENCODER"]
    assert r[0]["declare"] and r[0]["kind"] == "cli_agent"


def test_ordres_recents_lus_sans_rien_consommer(tmp_path):
    j = tmp_path / "ordres.jsonl"
    lignes = [{"id": "o1", "action": "restart", "demandeur": "CLAUDE", "raison": "x" * 500, "ts": 1.0,
               "evenement": "depose"},
              {"id": "o1", "action": "restart", "consommateur": "TRAY", "ts": 2.0, "evenement": "pris"},
              {"ordre": "funnel-ouvrir", "demandeur": "CLAUDE", "ok": True, "ts": 3.0, "evenement": "execute_hub"}]
    j.write_text("\n".join(json.dumps(x) for x in lignes) + "\nPAS DU JSON\n", encoding="utf-8")
    avant = j.read_text(encoding="utf-8")
    r = ob.recents(10, journal=j)
    assert [x["evenement"] for x in r] == ["depose", "pris", "execute_hub", "ILLISIBLE"]
    assert "raison" not in r[0] and r[2]["ordre"] == "funnel-ouvrir" and r[2]["ok"] is True
    assert j.read_text(encoding="utf-8") == avant                      # lecture seule
    assert ob.recents(2, journal=j)[-1]["evenement"] == "ILLISIBLE"
    assert ob.recents(5, journal=tmp_path / "absent.jsonl") == []


def test_un_journal_illisible_n_est_pas_aucun_ordre(tmp_path):
    # Revue AGY 15/10 : `except OSError: return []` affichait « aucun ordre » pour un journal refuse ou verrouille.
    r = ob.recents(5, journal=tmp_path)            # un DOSSIER a la place du fichier : OSError a la lecture
    assert len(r) == 1 and "ILLISIBLE" in r[0]["evenement"]


def test_une_meta_du_hub_perimee_ne_s_attache_pas_a_un_agent_frais(tmp_path):
    # Revue AGY 15/10 : un agent arrive a l'instant par la porte heritait d'un outil et d'un client vieux de jours.
    now = time.time()
    porte = tmp_path / "presence"
    porte.mkdir()
    (porte / "CLAUDE.seen").write_text(json.dumps({"ts": now - 5}), encoding="utf-8")
    (tmp_path / "presence_claude.seen").write_text(json.dumps({
        "agent": "CLAUDE", "ring": 1, "ts": datetime.fromtimestamp(now - 3 * 86400).isoformat(),
        "last_tool": "vieux_outil", "client": "100.64.1.2", "reseau": "tailscale"}), encoding="utf-8")
    c = {x["agent"]: x for x in fp.etat_presence(900, maintenant=now, identites=IDS, dossier=porte)}["CLAUDE"]
    assert c["age_s"] < 10 and c["dernier_outil"] is None and c["client"] is None
    assert c["meta_hub_perimee"] is True


def test_le_tray_affiche_presence_mode_dev_et_ordres():
    src = (ROOT / "tools" / "nokido_tray.py").read_text(encoding="utf-8")
    assert "etat_presence(FENETRE_AGENTS_S)" in src and "recents(6)" in src
    assert "Mode DEV :" in src and "Autorité dev :" in src and "Ordres récents" in src
    assert "_lire_corps()" in src.split("def _poll_loop", 1)[1]
    # la liste FIGEE de get_mode n'alimente plus le menu
    menu = src.split("def _build_menu", 1)[1].split("\ndef ", 1)[0]
    assert '_state.get("agents")' not in menu
    # UNKNOWN != NO : un jeton illisible n'est jamais affiche « desarme »
    mode_dev = src.split("def _mode_dev", 1)[1].split("\ndef ", 1)[0]
    assert "non valide" in mode_dev and "illisible" in mode_dev
