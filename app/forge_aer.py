# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = "regulation/aer-evenementiel"
AER — Address Event Representation pour les canaux vitaux de Nokido.

POURQUOI
========
La serie `vitals_history.jsonl` ecrit ~800 octets toutes les 15 s, que quelque chose
ait bouge ou non. Or la campagne du 2026-08-05 l'a mesure : sur 133 canaux candidats,
**la majorite sont constants sur la fenetre d'observation**. On paie donc de la bande
passante, du disque et du CPU pour re-dire que rien n'a change.

Le principe neuromorphique tient en une phrase : **l'inactivite ne coute rien**. Un
canal n'emet que lorsqu'il FRANCHIT un pas de quantification. Format inspire de l'AER
natif des puces (Loihi, Akida) : un evenement = [quand, qui, dans quel sens].

LE PIEGE QUE CE FORMAT DOIT EVITER — ET C'EST LE POINT CENTRAL
==============================================================
En delta-encoding pur, **le silence est ambigu** : un canal qui n'emet plus est-il
STABLE ou ILLISIBLE ? Nokido a paye ce defaut deux fois le 2026-08-05 seul (le canal
`swap` qui disparaissait sans un mot, un port surveille sans trafic qui s'evanouissait
du rapport) et le corpus d'aveux le classe comme LE defaut recurrent : transformer
« je n'ai rien vu » en « il n'y a rien ».

Encoder en evenements ferait REMONTER ce bug au niveau du protocole, la ou il est
bien plus difficile a voir. D'ou `pol = 0` reserve aux evenements de CONTROLE, dont
le keepalive : « toujours vivant, toujours stable ». Sans lui, un capteur mort
ressemble a un systeme calme.

FORMAT (8 octets, aligne, sans padding)
=======================================
    t_ms : u32  ms depuis l'ancre de session (wrap ~49 j -> voir CTRL_ANCRE)
    src  : u16  identifiant STABLE de canal
    pol  : i8   +1 hausse | -1 baisse | 0 = evenement de controle
    mag  : u8   pas de quantification franchis (1..255), ou code de controle

Equivalent Rust a compiler cote owner (`cargo` absent du sandbox) :

    #[repr(C)]
    #[derive(Clone, Copy, PartialEq, Debug)]
    pub struct Aer { pub t_ms: u32, pub src: u16, pub pol: i8, pub mag: u8 }
    // size_of::<Aer>() == 8, align == 4 — identique a struct.calcsize("=IHbB")

STABILITE DES IDENTIFIANTS
==========================
Un `src` qui se decale corrompt tout l'historique deja encode. Les ids NE SONT DONC
PAS derives d'un tri : ils sont EXPLICITES ci-dessous, et un nouveau canal prend le
prochain libre. Les canaux dynamiques (un par service) recoivent un id dans une plage
reservee, persiste dans `sandbox/aer_src_registry.json`.
"""
from __future__ import annotations

import json
import struct
import time
from pathlib import Path

FORMAT = "=IHbB"          # u32, u16, i8, u8 — sans padding
TAILLE = struct.calcsize(FORMAT)
assert TAILLE == 8, "le format AER doit tenir en 8 octets, mesure: %d" % TAILLE

_ROOT = Path(__file__).resolve().parent.parent
REGISTRE = _ROOT / "sandbox" / "aer_src_registry.json"

# ── Evenements de CONTROLE (pol = 0) ─────────────────────────────────────────
CTRL_ILLISIBLE = 1   # le canal ne peut plus etre lu (droit refuse, module absent)
CTRL_LISIBLE = 2     # il est redevenu lisible
CTRL_KEEPALIVE = 3   # vivant et stable — c'est CE code qui desambigue le silence
CTRL_RESET = 4       # la reference ne vaut plus (PID change, service redemarre)
CTRL_ANCRE = 5       # nouvelle ancre temporelle (t_ms repart de zero)
# VALEUR ABSOLUE — trou de protocole trouve par le banc du 2026-08-05. Apres une
# periode ILLISIBLE, l'encodeur se resynchronisait sur la valeur brute alors que
# `CTRL_LISIBLE` ne transporte AUCUNE valeur : un decodeur restait sur son ancienne
# reference et derivait pour toujours (MSE mesuree 1,8e10 sur `ctx`). Un canal a
# compteur cumulatif rend `None` a chaque remise a zero, donc le cas est FREQUENT,
# pas marginal. CTRL_ABS annonce que la trame SUIVANTE porte la valeur absolue.
CTRL_ABS = 6
_CTRL_NOMS = {1: "illisible", 2: "lisible", 3: "keepalive", 4: "reset", 5: "ancre",
              6: "valeur absolue (la trame suivante porte le float)"}
# Trame de continuation : meme 8 octets, relus comme (u32 t_ms, f32 valeur). Garder
# une trame de taille FIXE permet le `cast_slice` cote Rust ; une trame de taille
# variable interdirait la lecture zero-copie, qui est tout l'interet du format.
FORMAT_VAL = "=If"

# ── Identifiants STABLES. Ne JAMAIS renumeroter : un id qui bouge rend illisible
# tout l'historique deja encode. Un canal retire garde son id, definitivement.
SRC = {
    # scalaires machine (deja dans la serie avant l'elargissement)
    "ram_pct": 1, "ram_used_gb": 2, "ram_free_gb": 3, "cpu_pct": 4,
    "disk_pct": 5, "gpu_pct": 6, "tdr_recent": 7,
    # canaux ajoutes le 2026-08-05 (cf forge_vitals_channels.SCHEMA)
    "cmax": 10, "cect": 11, "ctx": 12, "irq": 13, "np": 14,
    "ior": 20, "iow": 21, "nr": 22, "ns": 23, "swp": 24,
    "emax": 30, "esum": 31, "en": 32,
    # debit par port (forge_port_callers)
    "q8099": 40, "q8100": 41, "q8091": 42, "q11434": 43, "q8766": 44,
}
SRC_DYNAMIQUE_BASE = 100   # plage reservee aux canaux par service (svc.<nom>.<champ>)

# Pas de quantification par defaut, en UNITES DU CANAL. Derives de la campagne du
# 2026-08-05 (~0,25 ecart-type mesure) — pas devines. Recalibrables en rejouant
# `tools/forge_vitals_channel_probe.py` : le pas suit la variance REELLE du canal,
# il n'est pas une constante d'auteur.
PAS = {
    "ram_pct": 0.5, "ram_used_gb": 0.15, "ram_free_gb": 0.15, "cpu_pct": 3.0,
    "disk_pct": 0.2, "gpu_pct": 5.0, "tdr_recent": 1.0,
    "cmax": 5.0,      # ecart-type mesure 20,25 -> 0,25 sigma
    "cect": 1.4,      # 5,44
    "ctx": 1200.0,    # 4853
    "irq": 700.0,     # 2808
    "np": 2.0,        # 1,95
    "ior": 11.0,      # 44,93
    "iow": 0.4,       # 1,64
    "nr": 28.0,       # 114,95
    "ns": 4.0,        # 16,94
    "swp": 0.5,
    "emax": 0.005, "esum": 0.01, "en": 1.0,
    "q8099": 5.0, "q8100": 5.0, "q8091": 5.0, "q11434": 5.0, "q8766": 5.0,
}
PAS_DEFAUT_RELATIF = 0.05   # canal inconnu : 5 % de la valeur de reference
KEEPALIVE_S = 300.0         # au-dela, un canal muet DOIT se signaler vivant


# Cache MEMOIRE du registre. Mesure du 2026-08-05 : sans lui, `src_id()` relisait le
# fichier JSON pour CHAQUE canal dynamique, soit 18 lectures disque par tic — d'ou
# 53,63 us/tic contre 5,74 pour l'ancien format. Le surcout n'etait pas celui du
# delta-encoding, c'etait le mien. Un encodeur cense ALLEGER le monitoring ne doit
# pas devenir la charge qu'il observe.
_REG_CACHE: dict | None = None


def _registre() -> dict:
    global _REG_CACHE
    if _REG_CACHE is None:
        try:
            _REG_CACHE = json.loads(REGISTRE.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            _REG_CACHE = {}
    return _REG_CACHE


def src_id(canal: str) -> int:
    """Id stable du canal. Les canaux dynamiques sont persistes pour que leur id
    survive a un redemarrage — sinon l'historique encode deviendrait illisible."""
    if canal in SRC:
        return SRC[canal]
    reg = _registre()
    if canal in reg:
        return int(reg[canal])
    prochain = max([SRC_DYNAMIQUE_BASE - 1] + [int(v) for v in reg.values()]) + 1
    reg[canal] = prochain
    try:
        REGISTRE.parent.mkdir(parents=True, exist_ok=True)
        REGISTRE.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return prochain


def pas_de(canal: str, reference: float | None) -> float:
    """Pas de quantification. Un canal inconnu prend un pas RELATIF plutot qu'une
    constante arbitraire : 5 % d'un debit reseau et 5 % d'un pourcentage de RAM
    n'ont pas la meme echelle, et fixer la meme valeur pour les deux serait un
    reglage d'auteur deguise en defaut."""
    if canal in PAS:
        return PAS[canal]
    base = abs(reference) if reference else 1.0
    return max(base * PAS_DEFAUT_RELATIF, 1e-9)


class Encodeur:
    """Transforme une suite d'instantanes en evenements AER.

    L'etat porte, par canal : la reference courante (accumulateur, PAS la derniere
    valeur brute — sinon les arrondis derivent), la lisibilite, et la date du dernier
    evenement emis (pour le keepalive).
    """

    def __init__(self, ancre_ms: float | None = None):
        self.ancre = ancre_ms if ancre_ms is not None else time.time() * 1000.0
        self.ref: dict = {}
        self.lisible: dict = {}
        self.dernier: dict = {}

    def _t(self, ts: float) -> int:
        # u32 en ms = ~49,7 jours. Au-dela on RE-ANCRE explicitement plutot que de
        # laisser le compteur boucler en silence sur un historique long.
        d = int(ts * 1000.0 - self.ancre)
        return d if 0 <= d < 2**32 else 0

    def re_ancrer(self, ts: float) -> list:
        self.ancre = ts * 1000.0
        return [(0, 0, 0, CTRL_ANCRE)]

    def encode(self, echantillon: dict, ts: float) -> list:
        """Evenements produits par cet instantane. `echantillon` = {canal: valeur|None}.
        Une valeur None signifie ILLISIBLE, jamais zero."""
        evts = []
        t = self._t(ts)
        if t == 0 and self.ref:
            evts += self.re_ancrer(ts)
            t = 0
        for canal, val in echantillon.items():
            sid = src_id(canal)
            etait = self.lisible.get(canal)
            if val is None:
                if etait is not False:
                    self.lisible[canal] = False
                    self.dernier[canal] = ts
                    evts.append((t, sid, 0, CTRL_ILLISIBLE))
                continue
            val = float(val)
            if etait is False:
                self.lisible[canal] = True
                self.dernier[canal] = ts
                evts.append((t, sid, 0, CTRL_LISIBLE))
                evts += self._absolu(t, sid, canal, val)
                continue
            if canal not in self.ref:
                self.lisible[canal] = True
                self.dernier[canal] = ts
                evts.append((t, sid, 0, CTRL_RESET))   # premiere reference posee
                evts += self._absolu(t, sid, canal, val)
                continue
            pas = pas_de(canal, self.ref[canal])
            n = int((val - self.ref[canal]) / pas)
            if n:
                pol = 1 if n > 0 else -1
                reste = abs(n)
                # Une variation enorme peut depasser 255 pas : on emet plusieurs
                # evenements plutot que de SATURER en silence a 255, ce qui ferait
                # perdre l'amplitude exactement quand elle compte le plus.
                while reste > 0:
                    m = min(255, reste)
                    evts.append((t, sid, pol, m))
                    reste -= m
                # La reference avance de n pas ENTIERS, pas jusqu'a la valeur brute :
                # sinon l'erreur d'arrondi s'accumule et le signal reconstruit derive.
                self.ref[canal] += n * pas
                self.dernier[canal] = ts
            elif ts - self.dernier.get(canal, 0.0) >= KEEPALIVE_S:
                self.dernier[canal] = ts
                evts.append((t, sid, 0, CTRL_KEEPALIVE))
        return evts


    def _absolu(self, t: int, sid: int, canal: str, val: float) -> list:
        """Pose la reference ET la TRANSMET. Sans ces deux trames, le decodeur garde
        une reference perimee : c'est le defaut que le banc a rendu visible."""
        self.ref[canal] = val
        return [(t, sid, 0, CTRL_ABS), ("VAL", t, val)]


class Decodeur:
    """Reconstruit les valeurs depuis les evenements SEULS — c'est le seul test
    honnete du format : si le decodeur ne retrouve pas le signal, l'encodeur ment.

    Livre AVEC l'encodeur volontairement : un consommateur qui re-implemente le
    decodage finit par diverger de l'emetteur, et la divergence se voit des annees
    plus tard sur des donnees deja ecrites."""

    def __init__(self):
        self.val: dict = {}
        self.lisible: dict = {}
        self._attente_abs: int | None = None

    def applique(self, evt) -> None:
        if isinstance(evt, tuple) and len(evt) == 3 and evt[0] == "VAL":
            if self._attente_abs is not None:
                self.val[self._attente_abs] = float(evt[2])
                self._attente_abs = None
            return
        t, sid, pol, mag = evt
        if pol == 0:
            if mag == CTRL_ABS:
                self._attente_abs = sid
            elif mag == CTRL_ILLISIBLE:
                self.lisible[sid] = False
            elif mag == CTRL_LISIBLE:
                self.lisible[sid] = True
            return
        if sid not in self.val:
            return   # pas de reference : on n'invente pas de valeur
        self.val[sid] += pol * mag * pas_de(nom_de(sid), self.val[sid])

    def lire(self, sid: int):
        """Valeur reconstruite, ou None si le canal est declare ILLISIBLE — jamais
        une derniere valeur connue presentee comme actuelle."""
        if self.lisible.get(sid) is False:
            return None
        return self.val.get(sid)


def nom_de(sid: int) -> str:
    """Id -> nom de canal. Necessaire au decodeur : le pas de quantification depend
    du CANAL, pas de l'identifiant."""
    for k, v in SRC.items():
        if v == sid:
            return k
    for k, v in _registre().items():
        if int(v) == sid:
            return k
    return "src%d" % sid


def empaqueter(evts) -> bytes:
    """Buffer binaire plat, pret pour une socket ou un fichier. Les trames de valeur
    absolue sont serialisees dans le MEME cadre de 8 octets, relu differemment."""
    out = []
    for e in evts:
        if isinstance(e, tuple) and len(e) == 3 and e[0] == "VAL":
            out.append(struct.pack(FORMAT_VAL, e[1] & 0xFFFFFFFF, float(e[2])))
        else:
            out.append(struct.pack(FORMAT, *e))
    return b"".join(out)


def depaqueter(buf: bytes):
    """Relit un buffer. `struct.iter_unpack` evite de decouper le buffer en N objets."""
    return list(struct.iter_unpack(FORMAT, buf))


def decrire(evt) -> str:
    """Un evenement en clair — un format binaire doit rester DEBOGGABLE."""
    t, sid, pol, mag = evt
    nom = next((k for k, v in SRC.items() if v == sid), None)
    if nom is None:
        nom = next((k for k, v in _registre().items() if int(v) == sid), "src%d" % sid)
    if pol == 0:
        return "t=%dms %s CONTROLE:%s" % (t, nom, _CTRL_NOMS.get(mag, "code%d" % mag))
    return "t=%dms %s %s%d pas" % (t, nom, "+" if pol > 0 else "-", mag)
