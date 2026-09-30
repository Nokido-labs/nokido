"""NR — le corps arbitre entre drain local et campagne cloud, pas le client.

Mesure 2026-09-01. Une campagne Modal et le drain local vectorisent la MEME file.
Lances ensemble :
  - ils se disputent l'unique writer SQLite -> la campagne est morte a
    11 776/200 868 sur `database is locked`, et le GPU distant DEJA PAYE pour ce
    lot a ete perdu (le credit Modal restant etait de 4,20 $) ;
  - le drain reclame `embed.wanted` des qu'il ne trouve pas :8099, si bien que
    l'embedder local a ete RALLUME 19 s apres son arret -- 12 Go repris pour
    doubler un travail que Modal faisait 26 fois plus vite (14,4 ms/chunk contre
    372 ms), machine a 98 % de RAM, admission des jobs refusee.

Le remede n'est PAS qu'un client eteigne des services a la main pour se faire de
la place : c'est le corps qui regule, le client se contente de reclamer. Ces
tests tiennent cette regulation.

Piege a ne pas reintroduire : un battement PERIME ne doit rien geler. Une
campagne morte qui laisserait le drain abstenu pour toujours transformerait une
regulation en panne silencieuse -- le motif « garde branche sur un signal que
personne n'emet », paye le 2026-07-30.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import forge_embed_auto_trigger as T  # noqa: E402
import forge_embed_router as R  # noqa: E402


def _battement(tmp_path, monkeypatch, **champs):
    p = tmp_path / "modal_campagne.heartbeat"
    p.write_text(json.dumps(champs), encoding="utf-8")
    monkeypatch.setattr(T, "CAMPAGNE_BATTEMENT", p)
    return p


def test_drain_sabstient_quand_la_campagne_bat(tmp_path, monkeypatch):
    _battement(tmp_path, monkeypatch, ts=time.time(), faits=1000, vise=20000)
    assert T.campagne_cloud_active() is True


def test_battement_perime_ne_gele_pas_le_drain(tmp_path, monkeypatch):
    # Une campagne morte ne doit pas abstenir le drain indefiniment.
    _battement(tmp_path, monkeypatch, ts=time.time() - (T.CAMPAGNE_FRAICHE_S + 60))
    assert T.campagne_cloud_active() is False


def test_campagne_finie_rend_la_main(tmp_path, monkeypatch):
    _battement(tmp_path, monkeypatch, ts=time.time(), fini=True)
    assert T.campagne_cloud_active() is False


def test_absence_de_campagne_laisse_le_drain_travailler(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "CAMPAGNE_BATTEMENT", tmp_path / "jamais_ecrit.heartbeat")
    assert T.campagne_cloud_active() is False


def test_pas_de_reclamation_de_l_embedder_pendant_une_campagne(tmp_path, monkeypatch):
    """LE point qui a coute 12 Go : reclamer un pilier dont un autre chemin fait
    deja le travail n'est pas une intention, c'est du bruit."""
    monkeypatch.setattr(R, "_campagne_cloud_bat", lambda *a, **k: True)
    pose = []
    monkeypatch.setattr(R, "declare_wanted", lambda *a, **k: pose.append(a) or True)
    assert R.declare_embed_wanted() is False
    assert not pose, "embed.wanted reclame alors qu'une campagne cloud couvre la file"


def test_reclamation_legitime_quand_aucune_campagne(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_campagne_cloud_bat", lambda *a, **k: False)
    pose = []
    monkeypatch.setattr(R, "declare_wanted", lambda *a, **k: pose.append(a) or True)
    assert R.declare_embed_wanted() is True
    assert pose and pose[0][0] == "embed.wanted"
