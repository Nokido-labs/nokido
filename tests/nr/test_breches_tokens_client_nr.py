"""NR : Trois breches de tokens du client Claude (mesurees le 7/11).

(1) hook_stop_attente_passive laisse finir le tour si barriere active (job_watch_etat.json frais)
    ou geste owner.
(2) claude_inbox_tick UserPromptSubmit : alarme contexte une fois par palier de doublement
    (defaut 400 Ko), silence sur erreur.
(3) forge_contexte_par_source ventiler_cout : tours, tours notif vs owner, tokens, top 5 sans contenu.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import hook_stop_attente_passive as H
import claude_inbox_tick as tick
import forge_contexte_par_source as F


# ─── (1) Hook Stop et Barriere de surveillance ───

def test_barriere_surveillance_fraiche_laisse_finir_le_tour(tmp_path, monkeypatch):
    etat = tmp_path / "job_watch_etat.json"
    etat.write_text(json.dumps({"actif": True, "expiration": time.time() + 300}), encoding="utf-8")
    monkeypatch.setenv("NOKIDO_JOB_WATCH_ETAT", str(etat))
    monkeypatch.setenv("NOKIDO_GATE_ETAT", str(tmp_path / "gate_state_absent.json"))
    monkeypatch.setenv("NOKIDO_GATE_JOBS", str(tmp_path / "jobs_absent"))

    # Barrière fraîche -> barriere_active est True
    assert H.barriere_active(maintenant=time.time(), frais_s=120) is True

    # Message d'attente passive normalement bloqué
    texte = "Le job tourne toujours, je reprends dès son verdict."
    raison = H.decider(texte, deja_relance=False)
    assert raison is not None  # decider() trouve le motif

    # Mais dans main(), si barriere active, raison est neutralisée (laisse finir)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": texte}]}}) + "\n",
        encoding="utf-8",
    )
    # Exécution de main en mockant stdin
    monkeypatch.setattr("sys.stdin", type("Stdin", (), {"read": lambda self: json.dumps({"transcript_path": str(transcript), "stop_hook_active": False})})())
    
    sorties = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: sorties.append(" ".join(str(a) for a in args)))
    rc = H.main()
    assert rc == 0
    # Aucune décision "block" n'a été émise sur stdout
    assert not any("block" in s for s in sorties)


def test_barriere_surveillance_absente_ou_perimee_bloque(tmp_path, monkeypatch):
    etat = tmp_path / "job_watch_etat.json"
    monkeypatch.setenv("NOKIDO_JOB_WATCH_ETAT", str(etat))
    monkeypatch.setenv("NOKIDO_GATE_ETAT", str(tmp_path / "gate_state_absent.json"))
    monkeypatch.setenv("NOKIDO_GATE_JOBS", str(tmp_path / "jobs_absent"))

    # Fichier absent -> barriere inactive
    assert H.barriere_active(maintenant=time.time()) is False

    # Fichier périmé (> 120s)
    etat.write_text(json.dumps({"actif": True}), encoding="utf-8")
    t_vieux = time.time() + 1000
    assert H.barriere_active(maintenant=t_vieux, frais_s=120) is False

    etat.unlink()  # main() lit l'horloge reelle : un fichier frais laisserait finir le tour

    texte = "Le job tourne toujours, je reprends dès son verdict."
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": texte}]}}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sys.stdin", type("Stdin", (), {"read": lambda self: json.dumps({"transcript_path": str(transcript), "stop_hook_active": False})})())
    
    sorties = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: sorties.append(" ".join(str(a) for a in args)))
    rc = H.main()
    assert rc == 0
    # Bloqué
    assert any("block" in s for s in sorties)


def test_dernier_message_rend_la_main_owner_laisse_finir():
    texte = "Le job tourne toujours. Geste owner requis : valide la clé."
    assert H.decider(texte, deja_relance=False) is None


# ─── (2) Alarme de Contexte dans UserPromptSubmit ───

def _transcription(t, jetons, bourrage_octets=0):
    """JSONL façon Claude Code : bourrage (sorties d'outils, hooks) puis un message assistant avec usage."""
    import json as _json
    lignes = []
    if bourrage_octets:
        lignes.append(_json.dumps({"type": "user", "message": {"content": "x" * bourrage_octets}}))
    lignes.append(_json.dumps({"type": "assistant", "message": {"usage": {
        "input_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": jetons - 10,
        "output_tokens": 50}}}))
    t.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def test_alarme_contexte_franchit_seuil_une_ligne_et_doublement(tmp_path, monkeypatch):
    monkeypatch.setenv("LAFORGE_SEUIL_CONTEXTE_JETONS", "10000")
    t = tmp_path / "transcript.jsonl"

    _transcription(t, 5000)
    assert tick._alerte_taille_contexte(str(t), session="s1", etat_dir=tmp_path) == ""

    _transcription(t, 12000)
    msg1 = tick._alerte_taille_contexte(str(t), session="s1", etat_dir=tmp_path)
    assert "[contexte]" in msg1
    assert "12000 jetons" in msg1
    assert "nouvelle session" in msg1

    _transcription(t, 15000)
    assert tick._alerte_taille_contexte(str(t), session="s1", etat_dir=tmp_path) == ""

    _transcription(t, 22000)
    msg2 = tick._alerte_taille_contexte(str(t), session="s1", etat_dir=tmp_path)
    assert "22000 jetons" in msg2

    _transcription(t, 30000)
    assert tick._alerte_taille_contexte(str(t), session="s1", etat_dir=tmp_path) == ""

    _transcription(t, 45000)
    assert "45000 jetons" in tick._alerte_taille_contexte(str(t), session="s1", etat_dir=tmp_path)


def test_alarme_contexte_gros_fichier_petit_contexte_silence(tmp_path, monkeypatch):
    """Owner 9/11 « c'est pas viable de faire des reprises constantes » : 854 Ko de JSONL
    (hooks, sorties d'outils) ne sont PAS 854 Ko de contexte. Seul l'usage compte."""
    monkeypatch.setenv("LAFORGE_SEUIL_CONTEXTE_JETONS", "10000")
    t = tmp_path / "transcript.jsonl"
    _transcription(t, 3000, bourrage_octets=900 * 1024)
    assert tick._alerte_taille_contexte(str(t), session="s2", etat_dir=tmp_path) == ""


def test_alarme_contexte_usage_illisible_silence_et_journal(tmp_path, monkeypatch, capsys):
    """UNKNOWN != NO : sans usage lisible, ni fausse alerte ni repli sur la taille du fichier."""
    monkeypatch.setenv("LAFORGE_SEUIL_CONTEXTE_JETONS", "10")
    assert tick._alerte_taille_contexte(str(tmp_path / "absent.jsonl"), session="s1", etat_dir=tmp_path) == ""
    t = tmp_path / "sans_usage.jsonl"
    t.write_text("x" * (50 * 1024), encoding="utf-8")
    assert tick._alerte_taille_contexte(str(t), session="s3", etat_dir=tmp_path) == ""
    assert "illisible" in capsys.readouterr().err


# ─── (3) Ventilation du coût de session ───

def test_ventilation_cout_exacte_et_distingue_notif_et_owner():
    entrees = [
        # Tour 1 : Déclenché par message owner
        {"type": "user", "message": {"role": "user", "content": "Peux-tu lancer le build ?"}},
        {
            "type": "assistant",
            "message": {
                "id": "resp_1",
                "role": "assistant",
                "content": [{"type": "text", "text": "Bien sûr, je lance le build."}],
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 500,
                    "cache_creation_input_tokens": 50,
                    "output_tokens": 20,
                },
            },
        },
        # Tour 2 : Déclenché par une notification de tâche
        {"type": "user", "message": {"role": "user", "content": "<task-notification> job_123 finished rc=0"}},
        {
            "type": "assistant",
            "message": {
                "id": "resp_2",
                "role": "assistant",
                "content": [{"type": "text", "text": "Le job est fini, je vérifie."}],
                "usage": {
                    "input_tokens": 200,
                    "cache_read_input_tokens": 1000,
                    "cache_creation_input_tokens": 0,
                    "output_tokens": 40,
                },
            },
        },
        # Tour 3 : Déclenché par l'owner
        {"type": "user", "message": {"role": "user", "content": "Parfait, passe à la suite"}},
        {
            "type": "assistant",
            "message": {
                "id": "resp_3",
                "role": "assistant",
                "content": [{"type": "text", "text": "Suite en cours."}],
                "usage": {
                    "input_tokens": 300,
                    "cache_read_input_tokens": 1500,
                    "cache_creation_input_tokens": 100,
                    "output_tokens": 60,
                },
            },
        },
    ]

    res = F.ventiler_cout(entrees)
    assert res["tours"] == 3
    assert res["tours_owner"] == 2
    assert res["tours_notification"] == 1
    assert res["input"] == 100 + 200 + 300
    assert res["cache_read"] == 500 + 1000 + 1500
    assert res["cache_creation"] == 50 + 0 + 100
    assert res["output"] == 20 + 40 + 60
    assert len(res["top_5_tours"]) == 3
    # Le plus lourd est resp_3 (300 + 1500 + 100 + 60 = 1960)
    assert res["top_5_tours"][0]["id"] == "resp_3"
    assert res["top_5_tours"][0]["total_tokens"] == 1960
    assert res["top_5_tours"][0]["declencheur"] == "owner"
    # Vérification : aucun texte de message présent dans la sortie
    serialise = json.dumps(res)
    assert "Peux-tu lancer" not in serialise
    assert "Bien sûr" not in serialise
    assert "job_123 finished" not in serialise


def _lecture(ident, chemin, sortie, limit=None):
    entree = {"file_path": chemin}
    if limit is not None:
        entree["limit"] = limit
    return [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": ident, "name": "Read", "input": entree}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": ident, "content": sortie}]}},
    ]


def test_lectures_par_zone_distingue_depot_memoire_et_forme():
    """Mesure 9/11 : 41 Read natifs = 12,3 % du coût, tous sous le seuil de 14 000 o du garde.
    Le levier ne se dimensionne qu'en sachant OÙ vont les lectures et SOUS QUELLE FORME."""
    depot = "%NOKIDO_ROOT%/tools/x.py"
    memoire = "%USERPROFILE%/.claude/projects/p/memory/fiche.md"
    entrees = (_lecture("a", depot, "A" * 3000) + _lecture("b", depot, "B" * 500, limit=40)
               + _lecture("c", memoire, "C" * 2000) + _lecture("d", "C:/tmp/r.json", "D" * 100)
               + _lecture("a", depot, "A" * 3000))  # rejouée après compaction : comptée une fois
    zones = {(z["zone"], z["forme"]): z for z in F.lectures_par_zone(entrees)}
    assert zones[("depot", "entiere")]["n"] == 1
    assert zones[("depot", "entiere")]["car"] > 3000
    assert zones[("depot", "bornee")]["n"] == 1
    assert zones[("memoire", "entiere")]["n"] == 1
    assert zones[("tmp", "entiere")]["n"] == 1
    assert sum(z["n"] for z in zones.values()) == 4
    # Aucun contenu lu ne fuit dans le rapport : chemins et tailles seulement.
    assert "AAAA" not in json.dumps(F.lectures_par_zone(entrees))
