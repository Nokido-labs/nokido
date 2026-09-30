# -*- coding: utf-8 -*-
"""forge_log_redact.py — RedactingFormatter : secrets/PII jamais écrits sur disque.

MOTIF (hermes-agent `hermes_logging.RedactingFormatter`, veille 2026-06-17) :
un Formatter logging qui scrubbe le message AVANT écriture fichier. Défense-en-
profondeur (complète le vault DPAPI) — un log ne doit jamais fuiter un token.

ANTI-DUP (§3) : NE réimplémente PAS la détection de secrets. RÉUTILISE le redactor
souverain LOG existant `forge_semantic_firewall.redact_for_log` (récursif, fail-safe).
Ce module n'apporte QUE l'adaptateur logging.Formatter + l'installeur.

Usage :
    import forge_log_redact
    forge_log_redact.install()            # enveloppe les handlers du root logger
    # ou par handler explicite :
    handler.setFormatter(forge_log_redact.RedactingFormatter("%(asctime)s %(message)s"))
"""
from __future__ import annotations

import logging

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:log-redact|risk:0.10|color:GREEN]"


def _default_redactor():
    """Rédacteur de journaux. Ordre corrigé le 2026-09-19, sur mesure.

    ⚠️ CE QUI ÉTAIT FAUX. Le premier choix était `redact_for_log`, dont le nom
    désigne exactement cet usage — et qui ne retire RIEN. Mesuré sur un témoin
    fabriqué portant un chemin Windows, une adresse privée et un jeton :

        redact_for_log     chemin RESTE · ip RESTE · jeton RESTE
        redact_text        chemin retiré · ip retirée · jeton RESTE
        redact_tool_output les DEUX jeux de motifs

    Les jeux `_REDACT_PATTERNS` (infrastructure) et `_OUTBOUND_PATTERNS` (clefs
    d'API) sont DISJOINTS à 100 % — mesure du 2026-09-12. Seul
    `redact_tool_output` applique les deux, c'est donc lui le porteur.

    ⚠️ ET LE REPLI IDENTITÉ. `lambda s: s` rendait le texte intact, en silence,
    pendant que l'appelant croyait filtrer. Il subsiste — perdre une ligne de
    journal serait pire — mais il est désormais DÉCLARÉ : `_est_identite` le
    signale, et le bilan du CLI cesse d'annoncer un rédacteur disponible.
    """
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_tool_output

        def _porteur(s: str) -> str:
            texte, _bilan = redact_tool_output(s, outil="journal")
            return texte

        _porteur._nokido_redacteur = "redact_tool_output"  # type: ignore[attr-defined]
        return _porteur
    except Exception:  # muet-ok : le repli suivant est tente, et le dernier se NOMME
        pass
    try:
        from nokido_agent.app.forge_semantic_firewall import redact_text

        def _partiel(s: str) -> str:
            r = redact_text(s)
            return r[0] if isinstance(r, tuple) else r

        _partiel._nokido_redacteur = "redact_text (INFRA seule, PAS les clefs)"  # type: ignore[attr-defined]
        return _partiel
    except Exception:  # muet-ok : l'identite ci-dessous est DECLAREE, pas silencieuse
        pass

    def _identite(s: str) -> str:
        return s

    _identite._nokido_redacteur = "IDENTITE — aucune redaction"  # type: ignore[attr-defined]
    return _identite


def _est_identite(fn) -> bool:
    """Un repli qui ne rédige rien doit pouvoir être NOMMÉ par l'appelant."""
    return str(getattr(fn, "_nokido_redacteur", "")).startswith("IDENTITE")


class RedactingFormatter(logging.Formatter):
    """logging.Formatter qui passe le message formaté par le redactor souverain.

    Le redactor est résolu paresseusement au 1er format() (évite les imports
    circulaires au boot). Fail-safe : si le redactor lève, on renvoie le message
    brut (le logging ne doit JAMAIS casser).
    """

    def __init__(self, *args, redactor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._redactor = redactor
        self._resolved = redactor is not None

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        if not self._resolved:
            self._redactor = _default_redactor()
            self._resolved = True
        try:
            out = self._redactor(s)
            return out if isinstance(out, str) else s
        except Exception:
            return s


def install(logger: "logging.Logger | None" = None) -> int:
    """Enveloppe les formatters des handlers existants par RedactingFormatter.

    Idempotent (un handler déjà redacted est sauté). Retourne le nombre de
    handlers enveloppés. À appeler APRÈS la mise en place des handlers (boot).
    """
    root = logger or logging.getLogger()
    n = 0
    for h in list(root.handlers):
        fmt = h.formatter
        if isinstance(fmt, RedactingFormatter):
            continue
        rf = RedactingFormatter(
            getattr(fmt, "_fmt", None),
            getattr(fmt, "datefmt", None),
        )
        h.setFormatter(rf)
        n += 1
    return n


# Alias pratique pour scrubber une chaîne hors logging.
_ECHEC_SIGNALE = False


def redact(text: str) -> str:
    """Rédige un texte. Si le rédacteur est indisponible, le DIT une fois.

    ⚠️ Cette fonction rend le texte EN CLAIR quand la rédaction échoue, et c'est
    volontaire : elle est appelée depuis un `logging.Formatter`, où lever
    ferait perdre la ligne de journal — le remède serait pire. Mais un
    fail-open MUET sur une fonction de sécurité laisse croire à une sortie
    filtrée ; la version d'origine (`except Exception: return text`) ne disait
    rien du tout. On signale donc, une seule fois pour ne pas inonder, et par
    `stderr` direct pour ne pas récurser dans le logging qu'on est en train de
    formater.
    """
    global _ECHEC_SIGNALE
    try:
        return _default_redactor()(text)
    except Exception as e:  # noqa: BLE001
        if not _ECHEC_SIGNALE:
            _ECHEC_SIGNALE = True
            try:
                import sys as _sys
                print("[log_redact] redacteur INDISPONIBLE (%s: %s) — les journaux "
                      "sortent EN CLAIR" % (type(e).__name__, str(e)[:100]),
                      file=_sys.stderr, flush=True)
            except Exception:  # muet-ok : signaler ne doit jamais casser l'appelant
                pass
        return text


def rediger_fichier(source, destination=None) -> dict:
    """Rédige un journal AVANT de le partager. C'est le besoin réel, mesuré.

    Mesure du 2026-09-19 : 120 journaux lus (0 illisible) contiennent **0 jeton**
    (GitHub, OpenAI, Slack, AWS, Bearer) mais **412 chemins du profil owner**
    dans 19 fichiers. Ces fichiers sont ignorés par git (`.gitignore:72 logs/`,
    0 fichier suivi), donc rien ne sort par le dépôt — mais joindre un journal à
    un rapport de bug est un geste courant, et là le nom d'utilisateur part.

    On ne rédige PAS les journaux à la source : en local, ces chemins servent au
    débogage. On outille le moment du PARTAGE.

    Rend un bilan qui DIT ce qui a été fait ; un filtrage muet ne se distingue
    pas d'un filtrage absent.
    """
    from pathlib import Path

    src = Path(source)
    texte = src.read_text(encoding="utf-8", errors="replace")
    redige = redact(texte)
    dst = Path(destination) if destination else src.with_suffix(src.suffix + ".redige")
    dst.write_text(redige, encoding="utf-8")
    return {
        "source": str(src),
        "destination": str(dst),
        "octets_lus": len(texte),
        "octets_ecrits": len(redige),
        "modifie": redige != texte,
        # UNKNOWN n'est pas NO : si le rédacteur était indisponible ou réduit à
        # l'identité, « aucune modification » ne prouve pas « rien à rédiger ».
        "redacteur_disponible": not _ECHEC_SIGNALE and not _est_identite(_default_redactor()),
        "redacteur": str(getattr(_default_redactor(), "_nokido_redacteur", "inconnu")),
    }


def main(argv=None) -> int:
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(
        prog="forge_log_redact",
        description="Redige un journal avant partage (chemins, adresses, clefs).")
    ap.add_argument("fichier", help="journal a rediger")
    ap.add_argument("-o", "--sortie", default=None,
                    help="destination (defaut : <fichier>.redige)")
    a = ap.parse_args(argv)
    bilan = rediger_fichier(a.fichier, a.sortie)
    print(_json.dumps(bilan, indent=2, ensure_ascii=False))
    if not bilan["redacteur_disponible"]:
        print("ATTENTION : le redacteur etait indisponible — la sortie n'est PAS "
              "garantie propre.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
