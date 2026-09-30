"""Non-regression : l'ecoute reelle est-elle bornee au loopback ?

Le hub verifiait deja `HUB_HOST` avant de servir (garde Phase 18) -- mais c'est
l'INTENTION. Trois chemins exposent un port sans jamais toucher cette variable :
un mapping de conteneur, un proxy place devant, un socket herite. Ce garde
constate l'EFFET.

L'invariant qui compte ici : **une sonde aveugle ne rend jamais « sain »**. Sous
Windows, l'enumeration des connexions peut etre refusee au compte de service, et
un refus d'acces ressemble trait pour trait a « aucune ecoute ». Confondre les
deux fabriquerait une securite imaginaire -- exactement le motif que Nokido paie
depuis des mois.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_bind_guard as bg  # noqa: E402


class _Adr:
    def __init__(self, ip, port):
        self.ip, self.port = ip, port


class _Conn:
    def __init__(self, ip, port, status="LISTEN"):
        self.laddr, self.status = _Adr(ip, port), status


def _psutil(monkeypatch, conns=None, exc=None):
    import psutil

    def _fake(kind="inet"):
        if exc is not None:
            raise exc
        return conns or []

    monkeypatch.setattr(psutil, "net_connections", _fake)


# --------------------------------------------------------------------------- #
# Le cas sain
# --------------------------------------------------------------------------- #

def test_loopback_seul_est_conforme(monkeypatch):
    _psutil(monkeypatch, [_Conn("127.0.0.1", 8766), _Conn("::1", 8766)])
    v = bg.verdict(8766)
    assert v["etat"] == bg.OK
    assert v["conforme"] is True


def test_un_port_voisin_n_influence_pas_le_verdict(monkeypatch):
    """Une ecoute sur 0.0.0.0:9999 ne doit pas condamner le port 8766."""
    _psutil(monkeypatch, [_Conn("127.0.0.1", 8766), _Conn("0.0.0.0", 9999)])
    assert bg.verdict(8766)["etat"] == bg.OK


# --------------------------------------------------------------------------- #
# L'exposition -- ce que le garde existe pour voir
# --------------------------------------------------------------------------- #

def test_toutes_interfaces_est_une_exposition(monkeypatch):
    _psutil(monkeypatch, [_Conn("0.0.0.0", 8766)])
    v = bg.verdict(8766)
    assert v["etat"] == bg.EXPOSE
    assert v["conforme"] is False
    assert "NON DECLAREE" in v["message"]


def test_une_ip_de_lan_est_une_exposition(monkeypatch):
    """Le cas du mapping de conteneur : HUB_HOST reste juste, le socket non."""
    _psutil(monkeypatch, [_Conn("localhost", 8766)])
    assert bg.verdict(8766)["etat"] == bg.EXPOSE


def test_une_exposition_declaree_reste_une_exposition(monkeypatch):
    """L'override rend l'exposition ASSUMEE, jamais invisible."""
    monkeypatch.setenv("LAFORGE_HUB_BIND_EXTERNAL", "1")
    _psutil(monkeypatch, [_Conn("0.0.0.0", 8766)])
    v = bg.verdict(8766)
    assert v["etat"] == bg.EXPOSE, "l'override ne doit pas changer le CONSTAT"
    assert v["conforme"] is True, "il change seulement la conformite"
    assert "ASSUMEE" in v["message"]


# --------------------------------------------------------------------------- #
# Le troisieme etat : ne pas savoir n'est pas etre sain
# --------------------------------------------------------------------------- #

def test_acces_refuse_rend_INCONNU_et_pas_LOOPBACK(monkeypatch):
    """LE test qui compte. Un refus d'ACL ressemble a « aucune ecoute »."""
    import psutil

    _psutil(monkeypatch, exc=psutil.AccessDenied())
    v = bg.verdict(8766)
    assert v["etat"] == bg.INCONNU
    assert v["conforme"] is None, "une cecite ne doit JAMAIS valoir conformite"


def test_aucun_listener_rend_INCONNU(monkeypatch):
    """Port pas encore bind : on ne sait pas, on ne declare pas sain."""
    _psutil(monkeypatch, [])
    v = bg.verdict(8766)
    assert v["etat"] == bg.INCONNU
    assert v["conforme"] is None


def test_une_erreur_inattendue_rend_INCONNU(monkeypatch):
    _psutil(monkeypatch, exc=RuntimeError("pilote reseau indisponible"))
    assert bg.verdict(8766)["etat"] == bg.INCONNU


# --------------------------------------------------------------------------- #
# Le garde ne doit jamais casser le demarrage
# --------------------------------------------------------------------------- #

def test_controler_n_arrete_jamais_le_processus(monkeypatch):
    """Un garde qui tue le control-plane transforme une exposition POSSIBLE en
    indisponibilite CERTAINE. Le corps a deja paye un service sain arrete."""
    _psutil(monkeypatch, [_Conn("0.0.0.0", 8766)])
    v = bg.controler(8766, logger=None)   # ne doit pas lever
    assert v["etat"] == bg.EXPOSE


def test_controler_survit_a_un_logger_casse(monkeypatch):
    class _Casse:
        def critical(self, *a, **k):
            raise RuntimeError("logger hs")
        warning = info = critical

    _psutil(monkeypatch, [_Conn("0.0.0.0", 8766)])
    assert bg.controler(8766, logger=_Casse())["etat"] == bg.EXPOSE


def test_le_patch_du_hub_est_idempotent_et_verifie_l_ancre():
    """Le patch vise un CRITICAL_FILE : il doit refuser plutot que deviner."""
    src = (ROOT / "tools" / "forge_patch_bind_guard.py").read_text(
        encoding="utf-8", errors="replace")
    assert "DEJA BRANCHE" in src, "le patch doit etre idempotent"
    assert "ancre introuvable" in src, "il doit refuser si le hub a change"
    assert "ast.parse(nouveau)" in src, "il doit verifier la syntaxe AVANT d'ecrire"
    assert "os.replace" in src, "l'ecriture doit etre atomique"
