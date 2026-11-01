"""forge_mesure.py -- primitive constitutionnelle `Mesure` (UNKNOWN != NO).

__FORGE_COLOR__ = "immunitaire/epistemique : statuts de mesure, temoin, liste blanche"

Pourquoi un module DEDIE : aucun hote existant ne convient, a cause du POIDS D'IMPORT. L'ancien hote
(tools/forge_cli_swarm.py) importe forge_agent_proxy des son chargement : tout utilisateur de `Mesure`
(census, catalogue, juge, hub) chargerait le proxy entier, et le jour ou le proxy importera `Mesure`,
ce serait un import CIRCULAIRE. Une primitive constitutionnelle reste LEGERE : bibliotheque standard
seule, AUCUN import de Nokido au chargement (contexte_courant() importe a l'appel seulement).
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent

# Un provider peut rendre ok=True avec un TEXTE d'erreur (« [ERR pollinations] HTTP
# Error 401 ») ou un texte VIDE. Et « backend non pret » depuis un compte qui ne voit pas
# le binaire du profil owner est une lecture IMPOSSIBLE, pas un pair mort : UNKNOWN != NO.
_MARQUES_ERREUR = ("[err", "[agy]", "error:", "http error")
_MARQUES_ILLISIBLE = ("backend non pret", "backend non prêt")


def _visible(texte: str) -> str:
    """Le texte sans espaces ni caracteres invisibles (categories Unicode Cf/Z*). 24/10 : une reponse U+200B seule
    passait `strip()` et etait comptee OK (groq:allam-2-7b dans l'essaim)."""
    import unicodedata
    return "".join(c for c in (texte or "") if not (c.isspace() or unicodedata.category(c) in ("Cf", "Zs", "Zl", "Zp")))


def _classer(ok: bool, texte: str, erreur) -> str:
    """OK · VIDE · KO · INDETERMINE -- liste BLANCHE : n'est OK que la vraie reponse."""
    err = str(erreur or "").lower()
    if any(m in err for m in _MARQUES_ILLISIBLE):
        return "INDETERMINE"
    if not ok:
        return "KO"
    if not _visible(texte):
        return "VIDE"
    if texte.lstrip().lower().startswith(_MARQUES_ERREUR):
        return "KO"
    return "OK"


# Une mesure ne rend JAMAIS un booleen ou un 0 nu : un statut, un temoin, un contexte, un age.
STATUTS_MESURE = frozenset({
    "VALEUR", "ZERO", "ABSENT", "NON_APPLICABLE", "UNKNOWN", "ILLISIBLE", "STALE", "INSUFFISANT",
    "TRANSPORT_ERROR", "AUTH_ERROR", "ECHEC_METIER"})
_LISIBLES = frozenset({"VALEUR", "ZERO", "ABSENT"})


class MesureIllisible(Exception):
    """Lecture d'une mesure qui n'est ni VALEUR, ni ZERO/ABSENT etalonne."""


@dataclass(frozen=True)
class Mesure:
    statut: str
    valeur: object = None
    temoin_positif: Optional[bool] = None
    cible_resolue: str = ""
    contexte: Optional[dict] = None  # forge_process_inventory.contexte_execution() (voir contexte_courant)
    mesure_le: Optional[float] = None
    ttl_s: Optional[float] = None
    source: str = ""
    motif: str = ""

    def __post_init__(self):
        if self.statut not in STATUTS_MESURE:
            raise ValueError("statut de mesure inconnu : %r" % (self.statut,))
        if self.statut in ("ZERO", "ABSENT") and self.temoin_positif is not True:
            object.__setattr__(self, "statut", "ILLISIBLE")
            object.__setattr__(self, "motif", "instrument non étalonné")

    def statut_lu(self, maintenant: Optional[float] = None) -> str:
        """Statut a la LECTURE : une mesure plus vieille que son ttl est STALE."""
        if self.mesure_le is not None and self.ttl_s is not None:
            now = time.time() if maintenant is None else maintenant
            if now - self.mesure_le > self.ttl_s:
                return "STALE"
        return self.statut

    def valeur_ou_leve(self, maintenant: Optional[float] = None):
        s = self.statut_lu(maintenant)
        if s not in _LISIBLES:
            raise MesureIllisible("mesure %s illisible (%s) : %s" % (s, self.source or "?", self.motif))
        return self.valeur


def agreger_sain(mesures, maintenant: Optional[float] = None) -> bool:
    """Liste BLANCHE : sain = non vide ET toutes prouvees saines (VALEUR, ou ZERO/ABSENT etalonne)."""
    ms = list(mesures)
    return bool(ms) and all(m.statut_lu(maintenant) in _LISIBLES for m in ms)


def prequalifier(temoin):
    """Decorateur : le temoin positif tourne AVANT la sonde metier. Temoin faux/en exception -> ILLISIBLE sans
    executer la sonde ; exception de la sonde -> ILLISIBLE (type + message), jamais un 0."""
    import functools

    def deco(sonde):
        @functools.wraps(sonde)
        def enveloppe(*args, **kwargs):
            src = getattr(sonde, "__name__", "sonde")
            try:
                ok = bool(temoin())
            except Exception as e:
                return Mesure("ILLISIBLE", source=src, motif="exception du témoin : %s" % type(e).__name__)
            if not ok:
                return Mesure("ILLISIBLE", source=src, motif="témoin muet")
            try:
                v = sonde(*args, **kwargs)
            except Exception as e:
                return Mesure("ILLISIBLE", temoin_positif=True, source=src,
                              motif="%s: %s" % (type(e).__name__, e))
            return Mesure("VALEUR", valeur=v, temoin_positif=True, source=src, mesure_le=time.time())
        return enveloppe
    return deco


def exiger_tools(payload) -> Mesure:
    """Banc « outils » : une requete sortante sans `tools` non vide n'est pas notee (angle mort qwen 7b 0/10)."""
    tools = payload.get("tools") if isinstance(payload, dict) else None
    if not tools:
        return Mesure("NON_APPLICABLE", source="exiger_tools", motif="tools non transmis")
    return Mesure("VALEUR", valeur=payload, source="exiger_tools", mesure_le=time.time())


def artefact_reference(chemin, sha256_attendu=None) -> Mesure:
    """Un rapport cite doit exister (et concorder au sha256 si fourni), sinon ILLISIBLE « référence absente »."""
    import hashlib
    src = str(chemin)
    p = Path(chemin)
    try:
        if not p.is_file():
            return Mesure("ILLISIBLE", source=src, motif="référence absente")
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError as e:
        return Mesure("ILLISIBLE", source=src, motif="référence absente (%s)" % type(e).__name__)
    if sha256_attendu and sha.lower() != str(sha256_attendu).lower():
        return Mesure("ILLISIBLE", source=src, motif="référence absente : sha256 discordant")
    return Mesure("VALEUR", valeur=sha, source=src, mesure_le=time.time())


def contexte_courant() -> dict:
    """Contexte d'execution reel (sonde reseau comprise) -- import PARESSEUX, a l'appel seulement."""
    sys.path.insert(0, str(ROOT / "tools"))
    from forge_process_inventory import contexte_execution
    return contexte_execution()


def depuis_http(code, corps="", contexte=None, source: str = "", mesure_le=None, ttl_s=None) -> Mesure:
    """Reponse HTTP -> Mesure. Jamais un score : 401/403 AUTH_ERROR, 429/5xx/timeout TRANSPORT_ERROR,
    200 portant un texte d'erreur TRANSPORT_ERROR (meme classement que `_classer`)."""
    def _m(statut, valeur=None, motif=""):
        return Mesure(statut=statut, valeur=valeur, contexte=contexte, source=source,
                      mesure_le=time.time() if mesure_le is None else mesure_le, ttl_s=ttl_s, motif=motif)
    if code is None:
        return _m("TRANSPORT_ERROR", motif="timeout / pas de reponse")
    if code in (401, 403):
        return _m("AUTH_ERROR", motif="HTTP %s" % code)
    if code == 429 or code >= 500:
        return _m("TRANSPORT_ERROR", motif="HTTP %s" % code)
    if not 200 <= code < 300:
        return _m("ECHEC_METIER", motif="HTTP %s" % code)
    classe = _classer(True, str(corps or ""), None)
    if classe == "KO":
        return _m("TRANSPORT_ERROR", motif="HTTP %s mais corps = texte d'erreur" % code)
    if classe == "VIDE":
        return _m("INSUFFISANT", motif="HTTP %s corps vide" % code)
    return _m("VALEUR", valeur=corps)
