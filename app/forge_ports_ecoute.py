"""Ports en ecoute, lus dans la seule classe fiable de la table TCP Windows.

Mesure du 6/11 (build 26300.9818, 49 passages, job_c00ec2f251fb) : classe LISTENER 49/49 sur :8765 et :8766, comme une
connexion reelle. `netstat -ano` et la classe ALL (psutil aussi) : 0 a 8/49. Les listeners y figurent bien, mais leur
colonne d'etat est fausse (etat 0 inexistant, FIN1, CLOSED), et des connexions mortes de PID 0 y portent LISTEN : cette
ligne fantome a fait tuer deux fois le superviseur par l'inspecteur. Lire ici, jamais l'etat de la table complete.

`ecouteurs_tcp` rend None quand l'API est illisible : ce n'est pas « aucun port en ecoute » (UNKNOWN != NO).
"""
from __future__ import annotations

import socket
import struct
import sys

__FORGE_COLOR__ = "Observabilite/Trace/capteur"

_AF_INET, _AF_INET6 = 2, 23
_CLASSE_LISTENER = 3  # TCP_TABLE_OWNER_PID_LISTENER
_ERREUR_TAMPON = 122  # ERROR_INSUFFICIENT_BUFFER


def decoder_table(tampon: bytes, famille: int = _AF_INET) -> list[tuple[int, int]]:
    """Pur. (port, pid) de chaque ligne d'une table MIB_TCP(6)TABLE_OWNER_PID."""
    n = struct.unpack_from("<I", tampon, 0)[0]
    lignes = []
    for i in range(n):
        if famille == _AF_INET:  # etat, adresse, port, adresse distante, port distant, pid
            _e, _a, port, _ra, _rp, pid = struct.unpack_from("<IIIIII", tampon, 4 + i * 24)
        else:  # adresse 16, scope, port, adresse distante 16, scope, port distant, etat, pid
            _a, _s, port, _ra, _rs, _rp, _e, pid = struct.unpack_from("<16sII16sIIII", tampon, 4 + i * 56)
        lignes.append((socket.ntohs(port & 0xFFFF), pid))
    return lignes


def _lire(iphlpapi, famille: int) -> list[tuple[int, int]] | None:
    import ctypes
    from ctypes import wintypes

    taille = wintypes.DWORD(0)
    rc = iphlpapi.GetExtendedTcpTable(None, ctypes.byref(taille), False, famille, _CLASSE_LISTENER, 0)
    for _ in range(4):
        if rc not in (0, _ERREUR_TAMPON):
            return None
        tampon = ctypes.create_string_buffer(taille.value + 4096)
        taille = wintypes.DWORD(len(tampon))
        rc = iphlpapi.GetExtendedTcpTable(tampon, ctypes.byref(taille), False, famille, _CLASSE_LISTENER, 0)
        if rc == 0:
            return decoder_table(tampon.raw, famille)
    return None


def ecouteurs_tcp() -> dict[int, set[int]] | None:
    """{port: {pid}} des listeners IPv4 et IPv6 ; None si la table est illisible. PID 0 ou 4 : pas un processus Nokido."""
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        iphlpapi = ctypes.windll.iphlpapi
        v4 = _lire(iphlpapi, _AF_INET)
        v6 = _lire(iphlpapi, _AF_INET6)
    except OSError:  # muet-ok : rendu None juste en dessous, jamais lu comme « rien en ecoute »
        return None
    if v4 is None:
        return None
    out: dict[int, set[int]] = {}
    for port, pid in v4 + (v6 or []):
        if pid > 4:
            out.setdefault(port, set()).add(pid)
    return out
