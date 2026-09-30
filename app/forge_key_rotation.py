"""
__FORGE_COLOR__ : immunitaire / métabolisme (clés providers)

forge_key_rotation — POOL multi-clés par provider + SANTÉ + rotation/skip automatique.

Problème (2026-06-14) : groq + cerebras avaient une clé INVALIDE (403) → tout le routage cloud
tombait, sans rotation ni skip. Ce module ajoute :
  - un POOL par variable (GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3...) lu via forge_secrets.
  - un store de SANTÉ par clé (empreinte sha256, JAMAIS la clé en clair) : ok / bad(401/403) /
    quota(429), avec TTL pour le quota (se réarme), bad persistant (clé morte = besoin neuve).
  - `resolve(env_base)` -> (managed, key) : 1re clé saine du pool ; (True, None) si pool géré mais
    TOUTES mortes (= le provider doit être SKIPPÉ) ; (False, None) si non géré (fallback legacy).

Consommé par forge_agent_proxy._load_api_key (préfère une clé saine, skip les mortes). Alimenté
par forge_endpoint_monitor (probe /models -> mark). 'Mieux monitorer/gérer les endpoints'.
Réutilise forge_secrets (vault DPAPI) — n'écrit jamais de clé hors vault.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
_HEALTH = ROOT / "sandbox" / "key_health.json"
_SUFFIXES = ["", "_2", "_3", "_4", "_5"]  # pool : GROQ_API_KEY, GROQ_API_KEY_2, ...
_QUOTA_TTL = int(os.environ.get("LAFORGE_KEY_QUOTA_TTL", str(3600)))  # 429 se réarme après 1h
# bad (401/403) n'est PLUS définitif : une clé re-fournie au vault ou transitoirement 401 doit
# pouvoir réessayer. Sans TTL, une clé valide re-mise reste morte à vie (bug groq/cerebras 2026-06-16).
_BAD_TTL = int(os.environ.get("LAFORGE_KEY_BAD_TTL", str(6 * 3600)))  # bad se réarme après 6h

# ── Cache TTL des lectures de coffre ────────────────────────────────────────────
# RCA 2026-08-16 (hub mort 18 min) : `forge_llm_router.all_status` evalue
# `is_configured` DEUX fois par slot (~31 slots), et chaque evaluation appelle
# `resolve` -> `_pool` -> 5 lectures vault DPAPI (_SUFFIXES). Soit ~300 acces au
# coffre, SYNCHRONES sur l'event-loop du hub, pour UN seul `list_providers`.
# Tant que le coffre repond en microsecondes, personne ne le voit (48-128 ms
# mesures) ; le jour ou il traine — rotation DPAPI du matin meme — la boucle
# gele 60 s et le watchdog `os._exit(1)` tue le hub.
# Un TTL court suffit : une cle ne change pas d'une seconde a l'autre, et les
# deux ecritures du module (`set_key`, `_save_health`) invalident ce qu'elles
# touchent. Contrepartie assumee : une cle posee au vault par un AUTRE process
# est vue avec au plus _SECRET_TTL de retard.
_SECRET_TTL = float(os.environ.get("LAFORGE_KEY_SECRET_TTL", "60"))
_secret_cache: dict = {}
_health_cache: tuple = (0.0, None)

# ── Exclusion INTER-PROCESSUS du ledger (2026-09-24) ─────────────────────────────
# MESURE : 6 processus x 25 `mark()` concurrents -> 50 marques sur 150 dans le
# ledger (100 perdues), et le 2026-09-23 22:39 un ledger illisible (« Extra data »).
# Deux causes : un temporaire FIXE partage par tous les ecrivains, et une sequence
# lire-modifier-ecrire sans exclusion. On REUTILISE la primitive de
# `forge_state_manager` (`filelock.FileLock`) plutot que d'en ecrire une troisieme.
# Borne courte : `mark()` peut etre appele depuis la boucle du hub ; la section
# critique dure quelques millisecondes (un petit JSON), attendre plus longtemps
# signalerait un ecrivain bloque, pas une file d'attente normale.
_LEDGER_LOCK_S = float(os.environ.get("LAFORGE_KEY_LEDGER_LOCK_S", "2"))


def _verrou_ledger():
    """Verrou fichier du ledger, ou None si `filelock` est absent (le DIRE, pas le taire)."""
    try:
        from filelock import FileLock
    except Exception as e:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger("forge.key_rotation").error(
            "[key_rotation] filelock INDISPONIBLE (%s) | consequence: ecritures du "
            "ledger SANS exclusion entre processus", type(e).__name__)
        return None
    return FileLock(str(_HEALTH) + ".lock", timeout=_LEDGER_LOCK_S)


def _modifier_ledger(modif) -> None:
    """Lire DU DISQUE, modifier, ecrire — sous le verrou inter-processus.

    Sans verrou obtenu, on ecrit QUAND MEME (une marque de revocation ne doit pas
    etre abandonnee parce qu'un autre ecrivain traine) et on le DIT : le fichier
    reste lisible grace au temporaire unique, seule une marque concurrente peut
    alors etre perdue.
    """
    verrou = _verrou_ledger()
    tenu = False
    if verrou is not None:
        try:
            verrou.acquire()
            tenu = True
        except Exception as e:  # noqa: BLE001
            import logging as _lg
            _lg.getLogger("forge.key_rotation").error(
                "[key_rotation] verrou du ledger NON obtenu en %.1fs (%s) | consequence: "
                "ecriture SANS exclusion, une marque concurrente peut etre perdue",
                _LEDGER_LOCK_S, type(e).__name__)
    try:
        h = dict(_relire_du_disque())
        modif(h)
        _save_health(h)
    finally:
        if tenu:
            try:
                verrou.release()
            except Exception:  # noqa: BLE001  # muet-ok : liberation best-effort, le verrou fichier expire avec le process
                pass


def _fp(key: str) -> str:
    return hashlib.sha256((key or "").encode()).hexdigest()[:12]


_ETAT_LEDGER = "VIDE"  # VIDE | LU | ILLISIBLE — voir `etat_du_ledger`


def _relire_du_disque() -> dict:
    """Lit le ledger SANS passer par le cache, et classe ce qui s'est passe.

    TROIS ETATS ET JAMAIS DEUX. L'ancienne version faisait `except: data = {}` :
    un fichier corrompu, un disque en panne et un premier demarrage rendaient le
    meme dict vide. Or `{}` signifie « aucune cle n'est marquee », donc
    `_usable(None) -> True`, donc TOUTES les cles redeviennent servables —
    revocations comprises, en silence, et aucun try/except de l'appelant ne
    pouvait le voir. C'est conclure d'une source qui se tait, du cote le plus
    cher.

    Ce module ne DECIDE pas a partir de cet etat : il l'EXPOSE. Refuser toutes
    les cles sur un ledger illisible couperait tout le routage cloud pour un
    fichier tronque — un garde qui crie a faux se fait desarmer. L'appelant qui
    fait de la SECURITE peut, lui, choisir de se fermer.
    """
    global _ETAT_LEDGER
    if not _HEALTH.exists():
        _ETAT_LEDGER = "VIDE"
        return {}
    try:
        data = json.loads(_HEALTH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        _ETAT_LEDGER = "ILLISIBLE"
        import logging as _lg
        _lg.getLogger("forge.key_rotation").error(
            "[key_rotation] ledger de sante ILLISIBLE (%s: %s) | consequence: "
            "toute cle marquee est relue comme INCONNUE, donc servable — les "
            "revocations sont levees jusqu'a reparation du fichier",
            type(e).__name__, str(e)[:90])
        return {}
    if not isinstance(data, dict):
        _ETAT_LEDGER = "ILLISIBLE"
        return {}
    _ETAT_LEDGER = "LU"
    return data


def etat_du_ledger() -> str:
    """VIDE (jamais ecrit) | LU | ILLISIBLE (present mais non exploitable).

    VIDE et ILLISIBLE ne se confondent pas : le premier est un demarrage, le
    second une panne. Les ranger ensemble fabrique soit des alertes fictives,
    soit des revocations levees sans temoin."""
    _relire_du_disque()
    return _ETAT_LEDGER


def _load_health() -> dict:
    global _health_cache
    ts, data = _health_cache
    if data is not None and (time.monotonic() - ts) < _SECRET_TTL:
        return data
    data = _relire_du_disque()
    _health_cache = (time.monotonic(), data)
    return data


def _save_health(h: dict) -> None:
    """Ecriture ATOMIQUE : temporaire puis remplacement.

    Un `write_text` direct laisse une fenetre ou le fichier est tronque. S'y
    lire rend un JSON invalide, donc un ledger vide, donc toutes les cles
    servables — la meme levee silencieuse que ci-dessus, par un autre chemin.
    """
    global _health_cache
    _health_cache = (time.monotonic(), h)  # l'ecriture fait autorite sur le cache
    # Temporaire UNIQUE par ecriture (pid + alea) : un nom FIXE etait partage par
    # tous les ecrivains, qui pouvaient y melanger leurs contenus (mesure 23/09).
    tmp = _HEALTH.with_name("%s.%d.%s.tmp" % (_HEALTH.name, os.getpid(), secrets.token_hex(4)))
    try:
        _HEALTH.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
        # Sous Windows, `os.replace` echoue si un lecteur tient la cible ouverte a
        # cet instant : quelques reessais courts avant de declarer l'echec.
        for essai in range(5):
            try:
                os.replace(tmp, _HEALTH)
                break
            except PermissionError:
                if essai == 4:
                    raise
                time.sleep(0.02 * (essai + 1))
    except Exception as e:  # noqa: BLE001
        try:
            tmp.unlink()
        except Exception:  # noqa: BLE001  # muet-ok : nettoyage d'un temporaire, l'echec principal est journalise juste apres
            pass
        # UN ECHEC D ECRITURE NE PEUT PAS ETRE MUET. `mark()` rendrait la main
        # normalement et l'appelant croirait avoir revoque une cle qui reste
        # servie partout : emettre reussit toujours, meme quand personne
        # n'enregistre. Le cache, lui, a deja ete mis a jour ci-dessus — donc
        # CE process voit la revocation et les autres NON, jusqu'au prochain
        # redemarrage qui l'effacera sans trace.
        import logging as _lg
        _lg.getLogger("forge.key_rotation").error(
            "[key_rotation] ECHEC d'ecriture du ledger (%s: %s) | consequence: "
            "les marques de ce process (revocations comprises) ne sont vues par "
            "AUCUN autre et disparaissent au redemarrage",
            type(e).__name__, str(e)[:90])


def _secret(name: str) -> Optional[str]:
    hit = _secret_cache.get(name)
    if hit is not None and (time.monotonic() - hit[0]) < _SECRET_TTL:
        return hit[1]
    try:
        from nokido_agent.app.forge_secrets import get_secret

        val = get_secret(name)
    except Exception:  # noqa: BLE001
        val = os.environ.get(name) or None
    _secret_cache[name] = (time.monotonic(), val)
    return val


def _pool(env_base: str):
    """[(env_name, key_value)] des clés présentes du pool."""
    out = []
    for sfx in _SUFFIXES:
        name = env_base + sfx
        v = _secret(name)
        if v:
            out.append((name, v))
    return out


def _usable(entry: Optional[dict]) -> bool:
    """Utilisable si inconnue, ok, quota expiré, OU bad expiré (re-tentative après _BAD_TTL).
    Bad n'est plus définitif : une clé re-fournie ou transitoirement 401/403 doit réessayer."""
    if not entry:
        return True  # inconnue = optimiste
    st = entry.get("status")
    if st in (None, "ok"):
        return True
    ts = entry.get("ts")
    if ts is None:
        return False
    if st == "quota":
        return (time.time() - ts) > _QUOTA_TTL
    if st == "bad":
        return (time.time() - ts) > _BAD_TTL
    # Tout autre statut — `revoked` au premier chef — est un etat de POLITIQUE
    # et NE SE RE-ARME PAS. `DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE` : une
    # cle retiree par decision ne revient que par une decision inverse, la ou
    # `bad` expire a dessein pour qu'un 403 transitoire puisse reessayer.
    return False


def resolve(env_base: str) -> Tuple[bool, Optional[str]]:
    """(managed, key). managed=True si le pool a >1 clé OU une santé enregistrée.
    key = 1re clé saine ; None si géré mais toutes mortes (=> skip provider)."""
    pool = _pool(env_base)
    if not pool:
        return (False, None)
    health = _load_health()
    fps = {_fp(v) for _n, v in pool}
    # `managed` commande si l'appelant doit RESPECTER la rotation :
    # `forge_agent_proxy._load_api_key` fait `if _managed: return _rk`, et
    # SINON retombe sur son cache `_API_KEYS`, qui n'est jamais purge.
    #
    # Le calculer sur les seules empreintes du POOL le rendait faux au pire
    # moment (2026-09-21) : depuis que le guichet ecarte les valeurs revoquees,
    # la cle retiree n'est plus dans le pool, son empreinte n'est plus testee,
    # et l'env cessait d'etre « gere » juste apres une revocation — donc
    # l'appelant quittait la voie gouvernee et pouvait resservir la cle
    # revoquee depuis son cache.
    #
    # On interroge donc le ledger par NOM D'ENV, et par egalite sur les noms du
    # pool plutot que par prefixe : `startswith` ferait capter `FOOBAR_KEY` par
    # `FOO_KEY`.
    _noms_du_pool = {env_base + sfx for sfx in _SUFFIXES}
    managed = (len(pool) > 1
               or any(fp in health for fp in fps)
               or any((e.get("env") or "") in _noms_du_pool for e in health.values()))
    for _name, key in pool:
        if _usable(health.get(_fp(key))):
            return (managed, key)
    if managed:
        import sys
        print(f"[key_rotation] {env_base}: toutes les clés du pool sont invalides (403/401/quota) -- skip provider", file=sys.stderr, flush=True)
    return (managed, None)  # toutes mortes


def quarantine_info(env_base: str) -> Optional[dict]:
    """{reason, retry_in_s} si TOUTES les cles du pool sont ecartees, sinon None.

    Sert a distinguer « cle ABSENTE » de « cle ECARTEE apres 403/401/quota ».
    Les deux produisaient le meme message cote appelant, ce qui envoie chercher
    une cle a re-saisir alors qu'elle est parfaitement valide et revient seule a
    l'expiration du TTL (fausse enquete vecue le 2026-08-11 : ~20 min passees a
    soupconner le coffre DPAPI pour un GROQ_API_KEY simplement en quarantaine).
    """
    pool = _pool(env_base)
    health = _load_health()
    if not pool:
        # LE POOL VIDE N'EST PLUS UNE REPONSE (2026-09-21). Depuis que
        # `forge_secrets` refuse de servir une valeur ecartee, `_secret` rend
        # None pour elle et `_pool` ne la voit plus : un env dont TOUTES les
        # cles sont ecartees devient indistinguable d'un env jamais configure.
        # C'est precisement la confusion que cette fonction existe pour tenir.
        #
        # Le ledger, lui, sait : ses entrees portent `env`. On le lui demande.
        ecartees = [e for e in health.values()
                    if (e.get("env") or "").startswith(env_base) and not _usable(e)]
        if not ecartees:
            return None          # vraiment inconnu : on ne fabrique pas d'alerte
        pire = max(ecartees, key=lambda e: e.get("ts") or 0)
        st = pire.get("status")
        ttl = _QUOTA_TTL if st == "quota" else (_BAD_TTL if st == "bad" else None)
        return {
            "reason": pire.get("reason") or st or "?",
            # `revoked` ne se re-arme pas : annoncer un delai de retour serait
            # un mensonge sur la nature du retrait.
            "retry_in_s": (max(0, int(pire.get("ts", 0) + ttl - time.time()))
                           if ttl is not None else None),
            "statut": st,
            "pool_vide": True,
        }
    worst = None
    for _name, key in pool:
        entry = health.get(_fp(key))
        if _usable(entry):
            return None  # au moins une cle utilisable => pas de quarantaine
        worst = entry or worst
    if not worst:
        return None
    ttl = _QUOTA_TTL if worst.get("status") == "quota" else _BAD_TTL
    return {
        "reason": worst.get("reason") or worst.get("status") or "?",
        "retry_in_s": max(0, int(worst.get("ts", 0) + ttl - time.time())),
    }


def healthy_key(env_base: str) -> Optional[str]:
    """Raccourci : clé saine si dispo, sinon la 1re du pool (legacy fail-safe)."""
    managed, key = resolve(env_base)
    if key:
        return key
    if managed:
        return None  # toutes mortes -> skip
    pool = _pool(env_base)
    return pool[0][1] if pool else None


def mark(env_base: str, key: str, status: str, reason: str = "") -> None:
    """Enregistre la santé d'une clé (par empreinte). status: ok|bad|quota."""
    if not key:
        return
    # FUSION, JAMAIS ECRASEMENT. `_load_health` peut rendre un cache vieux de
    # 60 s ; reecrire ce dict-la efface toute entree posee entre-temps par un
    # AUTRE process — et ils sont cinq hors de ce module a appeler `mark`.
    # Mesure du 2026-09-21 : `TOGETHER_API_KEY`, vue `bad` la veille, avait
    # disparu du ledger. Une revocation perdue par une course ne laisse aucune
    # trace : la cle redevient simplement servable.
    # La relecture seule ne suffisait pas (100 marques perdues sur 150 le 24/09) :
    # la sequence entiere passe sous le verrou inter-processus.
    fp = _fp(key)
    avant = {}

    def _poser(h):
        avant["status"] = (h.get(fp) or {}).get("status")
        h[fp] = {"env": env_base, "status": status, "reason": reason[:120], "ts": time.time()}

    _modifier_ledger(_poser)
    prev = avant.get("status")
    if status in ("bad", "quota") and prev != status:
        import sys
        print(f"[key_rotation] {env_base} clé {fp} marquée {status} ({reason}) -- sortie du pool sain", file=sys.stderr, flush=True)


# Un 403 qui porte l'un de ces marqueurs accuse le MODELE, pas la CLE.
# Mesure 2026-09-03 : `mistral-large-latest` rend
#   {"type":"tier_not_allowed","message":"This model is not available in your
#    subscription tier","code":"1910"}
# alors que `mistral-small-latest` repond 200 avec la MEME cle. Sans cette
# distinction, un seul appel au modele hors souscription marquait la cle « bad »
# et evincait TOUT le provider — une cle saine condamnee par un modele interdit.
_403_ACCUSE_LE_MODELE = (
    "tier_not_allowed", "model_not_found", "model_not_available",
    "does not exist", "not available in your subscription",
    "unsupported_model", "invalid_model",
)


def mark_http(env_base: str, key: str, http_status, detail: str = "") -> None:
    """Mappe un code HTTP -> sante (depuis le moniteur).

    `detail` = corps de la reponse, optionnel. Il sert a NE PAS condamner une
    cle pour une faute qui n'est pas la sienne : les appelants qui ne le
    passent pas gardent l'ancien comportement, mais perdent cette protection.
    """
    if http_status in (200, 201):
        mark(env_base, key, "ok")
    elif http_status in (401, 403):
        _bas = (detail or "").lower()
        if http_status == 403 and any(m in _bas for m in _403_ACCUSE_LE_MODELE):
            # La cle est SAINE : on ne la degrade pas, et on le dit — un skip
            # silencieux ferait rechercher la panne du mauvais cote.
            try:
                import logging as _lg
                _lg.getLogger(__name__).warning(
                    "[rotation] 403 imputable au MODELE, cle %s NON degradee (%s)",
                    env_base, _bas[:120])
            except Exception:  # noqa: BLE001  # muet-ok : journalisation seule
                pass
            return
        mark(env_base, key, "bad", f"http{http_status}")
    elif http_status == 429:
        mark(env_base, key, "quota", "http429")


def set_key(env_base: str, value: str, slot: int = 1) -> str:
    """Injecte une clé du pool dans le vault (slot 1 = base, 2 = _2, ...). Retourne le nom env."""
    name = env_base + ("" if slot <= 1 else f"_{slot}")
    from nokido_agent.app.forge_secrets import set_secret

    set_secret(name, value)
    _secret_cache.pop(name, None)  # la cle qu'on vient d'ecrire ne doit pas etre servie perimee
    # Relecture DU DISQUE sous verrou : partir du cache (jusqu'a 60 s) effacait
    # toute marque posee entre-temps par un autre processus.
    _modifier_ledger(lambda h: h.pop(_fp(value), None))  # nouvelle clé = santé remise à zéro
    return name


def pool_status(env_base: str) -> list:
    """État du pool (clés masquées + santé) pour audit."""
    health = _load_health()
    out = []
    for name, key in _pool(env_base):
        e = health.get(_fp(key)) or {}
        out.append({"env": name, "key": f"{key[:4]}...{key[-3:]}", "fp": _fp(key),
                    "status": e.get("status", "unknown"), "usable": _usable(e)})
    return out
