"""Contrat canonique d'un evenement d'usage LLM. ZERO I/O, ZERO SQL.

Ce module ne collecte rien et n'ecrit nulle part : il DEFINIT ce qu'est un
evenement d'usage valide, et il REFUSE le reste en le disant. Les adapters
(`forge_llm_usage_adapters`) normalisent les formats fournisseurs vers cette
forme ; le recorder unique (`forge_token_monitor.log_call`) la persiste. Trois
responsabilites, trois modules -- pour que le contrat n'ait pas a etre re-decrit
a chaque point d'ecriture, ce qui est exactement ce qui l'avait fracture.

CE QU'IL EMPECHE, mesure le 2026-09-12 sur 7839 lignes de `token_usage`
(baseline `docs/baselines/usage_T0_2026-09-12.json`) :

  agent_id = 'forge_agent_proxy' sur 7671/7839 (97,9 %). `agent_id` etant un
  parametre de signature, chaque appelant y inscrivait SON nom : on mesurait
  qui ECRIT, jamais qui DEMANDE. session_id renseigne 0/7839, meta 2/7839 --
  les deux champs prevus pour la provenance n'ont jamais servi.

DEUX INVARIANTS, non negociables :

1. La provenance est un TUPLE (provenance, execution_mode, transport), jamais
   une etiquette unique. AGY/INTERACTIVE/CLI_OAUTH et AGY/AUTONOMOUS/M2M
   partagent modele et fournisseur mais sont deux consommateurs distincts,
   avec des mecanismes differents. Les confondre rend un tableau de couts
   presentable et FAUX.

2. `measurement_kind` separe ce que le FOURNISSEUR a rapporte (REPORTED) de ce
   que Nokido a estime localement (ESTIMATED, p. ex. tiktoken) et de ce qu'on
   n'a pas pu mesurer (UNKNOWN). Une estimation n'est pas une preuve de
   facturation : un compteur tiktoken ne dit pas ce que le fournisseur a
   compte. Les melanger en silence est la facon precise dont une telemetrie
   devient un mensonge confortable -- d'ou le refus explicite d'un REPORTED
   adosse a une source d'estimation.

Et la symetrie, qui coute autant quand on l'oublie : un usage NON MESURE porte
des compteurs a None, jamais a zero. Un zero se somme sans bruit et fabrique
une consommation nulle ; un None se voit et se compte comme non mesure.
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/comptabilite-usage-llm"

import uuid

PROVENANCES = ("CLAUDE", "AGY", "CODEX", "NOKIDO", "UNKNOWN")
MODES = ("INTERACTIVE", "AUTONOMOUS", "M2M", "EXEC", "UNKNOWN")
TRANSPORTS = ("DESKTOP_STDIO", "CLI_HTTP", "CLI_OAUTH", "M2M", "HTTP",
              "JSONL", "UNKNOWN")
MESURES = ("REPORTED", "ESTIMATED", "UNKNOWN")
STATUTS = ("OK", "PENDING", "FAILED", "UNKNOWN")

# Trois etats pour le cout, pour la meme raison qu'il y en a trois pour la
# mesure. Mesure du 2026-09-12 : `cost_usd = 0.0` sur 4663 lignes sur 7859,
# et ZERO NULL -- ollama (gratuit) et groq (tarife mais non tabule) portaient
# la meme valeur. Un tarif absent rendu 0 se somme en silence et produit un
# cout non seulement faux, mais faussement PRECIS.
COUTS = ("KNOWN", "FREE", "UNKNOWN_PRICING")

COMPTEURS = ("input_tokens", "output_tokens", "reasoning_tokens",
             "cache_read_tokens", "cache_creation_tokens")

# Marqueurs d'une mesure LOCALE. Une source qui en porte un ne peut pas
# etayer un REPORTED : elle dit ce que NOUS avons compte, pas ce que le
# fournisseur a facture.
_MARQUEURS_ESTIMATION = ("tiktoken", "heuristique", "approx", "estim")

CHAMPS = (
    "event_id", "execution_id", "parent_execution_id", "session_id",
    "provenance", "execution_mode", "transport",
    "provider", "model",
    "input_tokens", "output_tokens", "reasoning_tokens",
    "cache_read_tokens", "cache_creation_tokens",
    "measurement_kind", "measurement_source",
    "cost_usd", "cost_kind", "cost_source",
    "started_at", "completed_at", "duration_ms", "status",
)

# Composants du CONTEXTE traite. Deliberement distincts de `output_tokens` :
# ce qui est envoye au modele n'est pas ce qu'il rend. Et deliberement sans
# champ `total_tokens` -- une metrique agregee doit porter sa definition, or
# `total = input + output` a rendu `4` pour un appel a 433 309 tokens de
# cache lu (mesure du 2026-09-12).
COMPOSANTS_CONTEXTE = ("input_tokens", "cache_read_tokens",
                       "cache_creation_tokens")


class ErreurContrat(ValueError):
    """Le contrat refuse -- et il nomme ce qu'il refuse."""


def _dans(valeur, permis, champ):
    """None -> UNKNOWN (on ne sait pas). Valeur hors enum -> REFUS explicite.

    La dissymetrie est voulue : ne pas savoir est un etat legitime, inventer
    une categorie ne l'est pas. C'est ce qui empeche `forge_agent_proxy` de
    redevenir une provenance parce qu'un appelant l'a passe.
    """
    if valeur is None:
        return "UNKNOWN"
    if valeur not in permis:
        raise ErreurContrat(
            "%s=%r hors contrat ; admis : %s" % (champ, valeur, ", ".join(permis)))
    return valeur


def creer(execution_id, provider, model, measurement_kind,
          measurement_source=None, provenance=None, execution_mode=None,
          transport=None, session_id=None, parent_execution_id=None,
          input_tokens=None, output_tokens=None, reasoning_tokens=None,
          cache_read_tokens=None, cache_creation_tokens=None,
          cost_usd=None, cost_kind=None, cost_source=None,
          started_at=None, completed_at=None, duration_ms=None,
          status="OK", event_id=None):
    """Construit un evenement VALIDE, ou leve `ErreurContrat` en le nommant.

    Rend un dict plat : il traverse des adapters, un recorder et une base, et
    un dict se serialise sans que chaque etape ait a connaitre une classe.
    """
    if not execution_id:
        raise ErreurContrat(
            "execution_id obligatoire : sans lui un usage n'appartient a "
            "aucune execution, et la provenance redevient une devinette")

    kind = _dans(measurement_kind, MESURES, "measurement_kind")
    source = measurement_source or None
    locale = bool(source) and any(m in source.lower() for m in _MARQUEURS_ESTIMATION)

    if kind == "ESTIMATED" and not source:
        raise ErreurContrat(
            "measurement_kind=ESTIMATED exige measurement_source : une "
            "estimation sans instrument nomme n'est pas verifiable")
    if kind == "REPORTED" and locale:
        raise ErreurContrat(
            "measurement_kind=REPORTED adosse a une source d'estimation "
            "(%r) : ce que NOUS comptons n'est pas ce que le fournisseur "
            "facture" % source)

    compteurs = {
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
    }
    if kind == "UNKNOWN":
        fournis = [c for c, v in compteurs.items() if v is not None]
        if fournis:
            raise ErreurContrat(
                "measurement_kind=UNKNOWN avec des compteurs fournis (%s) : "
                "une valeur chiffree est une mesure, elle doit se declarer "
                "REPORTED ou ESTIMATED" % ", ".join(sorted(fournis)))

    kcout = _dans(cost_kind, COUTS, "cost_kind")
    if cost_kind is None:
        # Non declare = on ne sait pas. Le defaut ne doit jamais etre la
        # gratuite : c'est ainsi qu'un cout inconnu devient un zero credible.
        kcout = "UNKNOWN_PRICING"
    if kcout == "UNKNOWN_PRICING" and cost_usd is not None:
        raise ErreurContrat(
            "cost_kind=UNKNOWN_PRICING avec cost_usd=%r : un tarif qu'on ne "
            "connait pas ne porte aucune valeur, pas meme 0" % cost_usd)
    if kcout == "KNOWN" and cost_usd is None:
        raise ErreurContrat(
            "cost_kind=KNOWN sans cost_usd : un cout declare connu doit "
            "porter sa valeur")
    if kcout == "FREE" and cost_usd != 0:
        raise ErreurContrat(
            "cost_kind=FREE avec cost_usd=%r : la gratuite PROUVEE vaut 0, et "
            "elle se distingue d'un tarif inconnu, qui vaut NULL" % cost_usd)

    ev = {
        "event_id": event_id or uuid.uuid4().hex,
        "cost_usd": cost_usd,
        "cost_kind": kcout,
        "cost_source": cost_source or None,
        "execution_id": execution_id,
        "parent_execution_id": parent_execution_id or None,
        "session_id": session_id or None,
        "provenance": _dans(provenance, PROVENANCES, "provenance"),
        "execution_mode": _dans(execution_mode, MODES, "execution_mode"),
        "transport": _dans(transport, TRANSPORTS, "transport"),
        "provider": provider or None,
        "model": model or None,
        "measurement_kind": kind,
        "measurement_source": source,
        "started_at": started_at, "completed_at": completed_at,
        "duration_ms": duration_ms,
        "status": _dans(status, STATUTS, "status"),
    }
    ev.update(compteurs)
    return ev


def context_tokens(ev):
    """Tokens de CONTEXTE traites, ou None. Definition explicite :

        context_tokens = input_tokens
                       + cache_read_tokens
                       + cache_creation_tokens

    Rend None des qu'un composant manque : sommer en traitant l'inconnu comme
    zero fabriquerait un contexte trop petit, presente avec la meme assurance
    qu'une mesure complete. C'est le defaut exact de l'ancien `total_tokens`.

    Ne PAS confondre avec des tokens FACTURES : un cache lu n'est pas tarife
    comme une entree neuve. Cette metrique dit ce que le modele a traite, pas
    ce que le fournisseur a compte.
    """
    if ev.get("measurement_kind") == "UNKNOWN":
        return None
    valeurs = [ev.get(c) for c in COMPOSANTS_CONTEXTE]
    if any(v is None for v in valeurs):
        return None
    return sum(valeurs)


def cle_agregation(ev):
    """La cle par laquelle un cout se ventile. Trois dimensions, pas une.

    C'est elle qui distingue AGY_CLI de AGY_M2M sur le meme modele.
    """
    return (ev["provenance"], ev["execution_mode"], ev["transport"])


def est_mesure(ev):
    """True seulement si l'evenement porte une mesure ASSUMEE (REPORTED ou
    ESTIMATED). Un agregat qui somme sans ce filtre compte des UNKNOWN pour
    zero -- la liste BLANCHE, jamais la liste noire."""
    return ev.get("measurement_kind") in ("REPORTED", "ESTIMATED")
