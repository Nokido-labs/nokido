"""NR 6/11 : l'inspecteur lisait la table complete de netstat, dont la colonne d'etat est fausse sur ce build.

- Absence fausse : un port vivant lu « DOWN » lancait `nssm start NokidoMCP` sur un hub vivant (8 sorties 7034).
- Ligne fantome : `DUPLICATE :8765 PIDs=['0', <superviseur>]` a fait tuer deux fois le superviseur par taskkill /F.

Les listeners viennent de forge_ports_ecoute. Un port absent ne vaut DOWN que si la connexion est refusee, et un delai
depasse reste INCONNU. Un doublon est un signal, jamais un ordre de tuer.
"""
import socket
import struct
import types

import forge_inspector as fi
import forge_ports_ecoute as pe


class _Connexion:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _isoler(monkeypatch, ecoute=None):
    """Listeners simules, canal d'alerte coupe, appels systeme enregistres (aucun taskkill ni nssm reel)."""
    appels = []

    def faux_run(cmd, *a, **k):
        appels.append(cmd)
        return types.SimpleNamespace(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(fi.subprocess, "run", faux_run)
    monkeypatch.setattr(fi, "_log", lambda *a, **k: None)
    monkeypatch.setattr(fi, "_last_action", {})
    monkeypatch.setattr(fi, "ecouteurs_tcp", lambda: ecoute)
    return appels


def test_port_vivant_absent_de_la_table_reste_ok(monkeypatch):
    _isoler(monkeypatch, {})
    with socket.socket() as ecoute:
        ecoute.bind(("127.0.0.1", 0))
        ecoute.listen(1)
        port = ecoute.getsockname()[1]
        monkeypatch.setattr(fi, "CRITICAL_PORTS", {port: "essai"})
        assert fi._check_ports()[port] == "OK"


def test_port_ferme_reste_down(monkeypatch):
    _isoler(monkeypatch, {})
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr(fi, "CRITICAL_PORTS", {port: "essai"})
    assert fi._check_ports()[port] == "DOWN"


def test_delai_depasse_est_inconnu_pas_down(monkeypatch):
    _isoler(monkeypatch, {})

    def delai(*a, **k):
        raise TimeoutError("delai")

    monkeypatch.setattr(fi.socket, "create_connection", delai)
    monkeypatch.setattr(fi, "CRITICAL_PORTS", {8766: "hub"})
    assert fi._check_ports()[8766] == "INCONNU"


def test_port_vu_dans_la_table_ne_sonde_pas(monkeypatch):
    _isoler(monkeypatch, {8766: {123}})

    def interdit(*a, **k):
        raise AssertionError("la table a vu le port : aucune connexion a ouvrir")

    monkeypatch.setattr(fi.socket, "create_connection", interdit)
    monkeypatch.setattr(fi, "CRITICAL_PORTS", {8766: "hub"})
    assert fi._check_ports()[8766] == "OK"


def test_table_illisible_se_confirme_par_connexion(monkeypatch):
    """UNKNOWN != NO : None n'est pas « aucun port en ecoute »."""
    _isoler(monkeypatch, None)
    monkeypatch.setattr(fi.socket, "create_connection", lambda *a, **k: _Connexion())
    monkeypatch.setattr(fi, "CRITICAL_PORTS", {8765: "LaForge-Master"})
    assert fi._check_ports()[8765] == "OK"


def test_un_doublon_se_signale_et_ne_se_tue_jamais(monkeypatch):
    appels = _isoler(monkeypatch, {8766: {111, 222}})
    monkeypatch.setattr(fi, "CRITICAL_PORTS", {8766: "hub"})
    assert fi._check_ports()[8766] == "DUPLICATE"
    assert not [c for c in appels if "taskkill" in c]


def test_l_inspecteur_ne_lit_plus_netstat_pour_ses_ports(monkeypatch):
    appels = _isoler(monkeypatch, {8766: {123}})
    monkeypatch.setattr(fi, "CRITICAL_PORTS", {8766: "hub"})
    fi._check_ports()
    assert not [c for c in appels if "netstat" in c]


def test_hub_vivant_absent_de_la_table_ne_lance_pas_nssm(monkeypatch):
    """Le chemin reel de l'incident : table muette, hub et Master vivants."""
    appels = _isoler(monkeypatch, {})
    monkeypatch.setattr(fi.socket, "create_connection", lambda *a, **k: _Connexion())
    fi._heal_ports(fi._check_ports())
    assert not [c for c in appels if "nssm" in c]


def test_hub_inconnu_ne_lance_pas_nssm(monkeypatch):
    appels = _isoler(monkeypatch, {})

    def delai(*a, **k):
        raise TimeoutError("delai")

    monkeypatch.setattr(fi.socket, "create_connection", delai)
    fi._heal_ports(fi._check_ports())
    assert not [c for c in appels if "nssm" in c]


def test_hub_ferme_lance_encore_nssm(monkeypatch):
    """Le soin n'est pas retire : hub et Master refuses, la relance part toujours."""
    appels = _isoler(monkeypatch, {})

    def refus(*a, **k):
        raise ConnectionRefusedError("refus")

    monkeypatch.setattr(fi.socket, "create_connection", refus)
    fi._heal_ports({8766: "DOWN", 8765: "DOWN"})
    assert [c for c in appels if "nssm" in c]


# ── Capteur ──
def _ligne_v4(port, pid):
    return struct.pack("<IIIIII", 2, 0, socket.htons(port), 0, 0, pid)


def test_le_capteur_decode_le_port_et_le_pid():
    t = struct.pack("<I", 2) + _ligne_v4(8765, 19408) + _ligne_v4(8766, 5792)
    assert pe.decoder_table(t) == [(8765, 19408), (8766, 5792)]


def test_le_capteur_decode_ipv6():
    ligne = struct.pack("<16sII16sIIII", b"\0" * 16, 0, socket.htons(8080), b"\0" * 16, 0, 0, 2, 321)
    assert pe.decoder_table(struct.pack("<I", 1) + ligne, 23) == [(8080, 321)]


def test_le_capteur_ecarte_pid_zero_et_systeme(monkeypatch):
    monkeypatch.setattr(pe, "_lire", lambda api, famille: [(8765, 0), (8765, 19408), (445, 4)] if famille == 2 else [])
    monkeypatch.setattr(pe.sys, "platform", "win32")
    assert pe.ecouteurs_tcp() == {8765: {19408}}


def test_le_capteur_illisible_rend_none(monkeypatch):
    monkeypatch.setattr(pe, "_lire", lambda api, famille: None)
    monkeypatch.setattr(pe.sys, "platform", "win32")
    assert pe.ecouteurs_tcp() is None
