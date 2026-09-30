"""Adaptateurs d'usage LLM -- Claude, Codex et AGY dans UNE seule table.

__FORGE_COLOR__ = "observabilite/trace : usage tokens des CLI clients"

But, pose par l'owner le 2026-09-12 : repondre a une question qu'aucun CLI ne
peut trancher seul --

    combien de tokens Nokido a-t-il reellement EVITES a ses clients LLM ?

CE QU'ON ETEND, ET QU'ON NE REFAIT PAS. `token_usage` existe : elle est ecrite
par `forge_llm_transport._track_usage` et agregee par agent (CLAUDE, GEMINI,
ANTIGRAVITY, CODEX) par `tools/forge_token_meter.py`. Le bus transverse est
deja la. Deux manques seulement :

  1. ses colonnes ignorent cache_read / cache_write / reasoning -- or c'est la
     que se joue la depense reelle (un cache read ne coute pas un input) ;
  2. ses 14 ecrivains sont tous des PROVIDERS appeles par Nokido ; aucun
     n'alimente la table depuis les CLI CLIENTS.

Ce module comble le second et prepare le premier (`migrer`).

DEUX REGLES QUI GOUVERNENT TOUT LE FICHIER, parce que ce sont les deux facons
de fabriquer une mesure fausse qui a l'air juste :

  CHAMP ABSENT != ZERO. Un flux qui ne rapporte pas le cache n'a pas un cache
  nul, il a un cache INCONNU. Ecrire 0 fabrique une economie qui n'existe pas,
  et le faux est du cote flatteur -- donc indetectable a la relecture.

  QUOTA != USAGE. Le `/usage` d'un CLI montre un quota et un restant ; les
  evenements de tour montrent une consommation. Trois couches distinctes
  (quota de session, usage du tour, metrique OTel) qu'on ne melange jamais.
"""
from __future__ import annotations

# Colonnes que `token_usage` n'a pas et qui portent la depense reelle.
# Colonnes ajoutees a `token_usage`, avec leur TYPE DECLARE. C'etait un set,
# et `migrer()` creait tout en INTEGER : SQLite aurait range les chaines de
# provenance dans des colonnes entieres sans protester (affinite de type), et
# le defaut ne se serait vu qu'au tri ou a la comparaison.
COLONNES_AJOUTEES = {
    "cache_read_tokens": "INTEGER",
    "cache_write_tokens": "INTEGER",
    "reasoning_tokens": "INTEGER",
    # Identite de l'execution -- transportee depuis l'entree, jamais deduite.
    "provenance": "TEXT",
    "execution_mode": "TEXT",
    "transport": "TEXT",
    "execution_id": "TEXT",
    "parent_execution_id": "TEXT",
    # Nature de la mesure et du cout : trois etats chacun.
    "measurement_kind": "TEXT",
    "measurement_source": "TEXT",
    "cost_kind": "TEXT",
    "cost_source": "TEXT",
    # Le module qui ECRIT, a sa place : ce n'est pas l'identite du client.
    "writer_component": "TEXT",
}

_CHAMPS = (
    "provider", "model", "session_id", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
    "total_tokens", "context_window", "source",
)


def _entier(bloc, *noms):
    """Premiere valeur ENTIERE trouvee, sinon None.

    None et 0 ne sont pas interchangeables ici : None dit << non rapporte >>,
    0 dit << rapporte a zero >>. Les confondre est le defaut central que ce
    module doit eviter.
    """
    if not isinstance(bloc, dict):
        return None
    for n in noms:
        v = bloc.get(n)
        if isinstance(v, bool):      # bool est un int en Python : piege connu
            continue
        if isinstance(v, int):
            return v
    return None


def _ev(provider, model, session_id, usage, source, total=None, fenetre=None,
        provenance=None, execution_mode=None, transport=None,
        measurement_kind=None, execution_id=None):
    e = {c: None for c in _CHAMPS}
    e.update({
        "provider": provider,
        "model": model or None,
        "session_id": session_id or None,
        "source": source,
        "context_window": fenetre,
        "total_tokens": total,
        # L'identite vient de l'ADAPTER, qui sait de quel canal il lit. Ce
        # n'est pas une deduction sur un processus ou un nom de module : un
        # adaptateur est specifique a une entree, donc il la CONNAIT.
        "provenance": provenance or "UNKNOWN",
        "execution_mode": execution_mode or "UNKNOWN",
        "transport": transport or "UNKNOWN",
        "measurement_kind": measurement_kind or "UNKNOWN",
        "execution_id": execution_id or None,
    })
    e.update(usage)
    # Le total ne se DEDUIT que si toutes ses parts sont connues. Additionner
    # des inconnues rendrait une somme fausse presentee comme sure.
    if e["total_tokens"] is None:
        parts = [e["input_tokens"], e["output_tokens"]]
        if all(p is not None for p in parts):
            e["total_tokens"] = sum(parts) + (e["reasoning_tokens"] or 0)
    return e


def depuis_claude(charge):
    """Statusline Claude Code. `current_usage` vit SOUS `context_window`."""
    if not isinstance(charge, dict):
        return None
    fenetre = charge.get("context_window")
    cu = charge.get("current_usage")
    if not isinstance(cu, dict) and isinstance(fenetre, dict):
        # Mesure 2026-09-12 sur le payload REEL de la statusline : Claude
        # Code place `current_usage` SOUS `context_window`. La forme a la
        # racine reste lue -- la retrocompat ne coute rien, alors qu'un
        # champ cherche au mauvais niveau rendait None, c'est-a-dire un
        # UNKNOWN affiche comme une absence de depense.
        cu = fenetre.get("current_usage")
    if not isinstance(cu, dict):
        return None
    modele = charge.get("model")
    if isinstance(modele, dict):
        modele = modele.get("id")
    return _ev(
        "claude", modele, charge.get("session_id"),
        {
            "input_tokens": _entier(cu, "input_tokens"),
            "output_tokens": _entier(cu, "output_tokens"),
            "cache_read_tokens": _entier(cu, "cache_read_input_tokens"),
            "cache_write_tokens": _entier(cu, "cache_creation_input_tokens"),
            "reasoning_tokens": _entier(cu, "reasoning_output_tokens"),
        },
        "claude_statusline",
        fenetre=_entier(fenetre, "total_input_tokens"),
        # Claude Code transmet ces compteurs dans son payload : ils sont
        # RAPPORTES par le client, pas estimes localement.
        provenance="CLAUDE",
        execution_mode="INTERACTIVE",
        transport="CLI_HTTP",
        measurement_kind="REPORTED",
    )


def depuis_codex(charge):
    """Codex `turn.completed`. `cached_input_tokens` est un cache READ."""
    if not isinstance(charge, dict) or charge.get("type") != "turn.completed":
        return None
    u = charge.get("usage")
    if not isinstance(u, dict):
        return None
    return _ev(
        "codex", charge.get("model"), charge.get("session_id"),
        {
            "input_tokens": _entier(u, "input_tokens"),
            "output_tokens": _entier(u, "output_tokens"),
            "cache_read_tokens": _entier(u, "cached_input_tokens"),
            "cache_write_tokens": _entier(u, "cache_write_input_tokens"),
            "reasoning_tokens": _entier(u, "reasoning_output_tokens"),
        },
        "codex_turn",
    )


def depuis_agy(charge):
    """Antigravity `stream-json`. `thinking_tokens` est du reasoning.

    Refuse explicitement un `usage_summary` : c'est un QUOTA, pas une
    consommation. Les confondre donne un chiffre qui ne veut rien dire et qui
    a l'air d'une mesure.
    """
    if not isinstance(charge, dict):
        return None
    if charge.get("type") not in ("step_update", "turn_complete", "result"):
        return None
    if "quota" in charge:
        return None
    u = charge.get("usage")
    if not isinstance(u, dict):
        return None
    return _ev(
        "agy", charge.get("model"), charge.get("session_id"),
        {
            "input_tokens": _entier(u, "input_tokens"),
            "output_tokens": _entier(u, "output_tokens"),
            "cache_read_tokens": _entier(u, "cache_read_tokens"),
            "cache_write_tokens": _entier(u, "cache_creation_tokens"),
            "reasoning_tokens": _entier(u, "thinking_tokens"),
        },
        "agy_stream",
        total=_entier(u, "total_tokens"),
        fenetre=_entier(u, "context_window_size"),
    )


def migrer(conn):
    """DEMENAGE vers `forge_token_monitor.migrer` le 2026-09-12.

    Un ADAPTER de formats fournisseurs ne touche pas la base : il normalise
    des payloads vers `forge_llm_usage_event`, point. Le DDL suit le DML chez
    le proprietaire unique de la table (regle UNIQUE_WRITER, owner 2026-09-12).

    Alias conserve pour les appelants existants ; l'implementation, et donc
    l'`ALTER TABLE`, vit desormais chez le proprietaire.
    """
    from forge_token_monitor import migrer as _migrer  # type: ignore

    return _migrer(conn)
