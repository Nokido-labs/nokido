"""forge_endocrine.py — Régulation endocrinienne transverse Nokido.

Mapping bio↔code (extension du mapping neurones du même chantier) :
- Hormone        = signal scalaire avec demi-vie, émis par un organe, lu par récepteurs distants
- Glande         = module qui produit (release)
- Récepteur      = module qui lit + adapte son comportement
- Demi-vie       = decay exponentiel (signal s'estompe sans renouvellement)
- Seuil          = un organe ne réagit qu'au-delà d'un dosage
- Hypothalamus   = forge_circadian_loop (chef d'orchestre des cycles)
                   ⚠️ RÉDUCTION ASSUMÉE (2026-07-16) : le circadien n'est que le
                   noyau suprachiasmatique — 1 noyau hypothalamique sur ~11. L'aire
                   préoptique (thermorégulation), l'arqué (balance énergétique), le
                   PVN (axe du stress), le supraoptique (osmolarité) n'ont PAS
                   d'équivalent ici. Conséquence directe : Nokido n'a pas
                   d'INTÉGRATEUR qui POSSÈDE ses consignes. Les set-points sont
                   gravés en dur dans chaque tissu (0.05 novelty, 70% CPU, 85% RAM,
                   0.8 budget) et aucun signal ne peut les déplacer → pas de fièvre,
                   alors que déplacer sa propre consigne (PGE2 sur l'aire préoptique
                   → frisson jusqu'à 39°) est justement la régulation d'ordre
                   supérieur du vivant. SEULE exception câblée :
                   forge_homeostasis_orchestrator._endocrine_factor(), qui module le
                   seuil de nouveauté ×1.0..1.5 sous threat_salience/cortisol.
- Hypophyse      = ce module (releasing factors → hormones spécifiques)

POURQUOI
========
Les workers Nokido ne se coordonnent pas (daemon biblio + rss_watcher + skill_enricher
tous tirent sur les mêmes ressources sans modulation). Les bugs identifiés par
forge_health_diagnostic (32% vectorisé, 73% mailbox unread, rss_watcher heartbeat
stale) sont des **désordres endocriniens** : pas de signal de régulation entre
organes.

HORMONES CANONIQUES (extensibles via release/read API)
======================================================
- INSULIN_VECTORIZATION  : produite quand pct_chunks_vectorized > 95% (saturation OK).
                           Récepteur : forge_rag_warmup → reduce_batch (économie GPU).
- TSH_VECTORIZATION      : produite quand pct < 80% (déficit). Récepteur : warmup → boost.
- CORTISOL_QUOTA_CLOUD   : produite quand cost_usd_today / daily_budget > 0.8.
                           Récepteur : forge_llm_router → force local cascade.
- ADRENALINE_HUB_PRESSURE : produite quand network_log.req_per_min > seuil.
                           Récepteur : forge_*_daemon → augmente intervals (back-pressure).
- LEPTIN_MAILBOX_FULL    : produite quand agent_messages.unread_pct > 50%.
                           Récepteur : forge_mailbox_purger (futur) ou anchor_alert.
- DOPAMINE_SUCCESS       : produite par anchor_solution(quality_score>0.85).
                           Récepteur : skill_enricher → priorise les domains correspondants.

Chaque hormone a une demi-vie configurée. Le decay est appliqué à chaque cycle
de read() ou via un cron explicite. Si pas renouvelée, l'hormone tend vers 0.
=======
DECAY & CHRONICITÉ
==================
Chaque hormone a une demi-vie configurée. Le decay est appliqué à chaque cycle
de read() ou via un cron explicite. Si pas renouvelée, l'hormone tend vers 0.

Ré-émettre une hormone ENCORE VIVANTE prolonge l'épisode en cours : `released_at`
repart (c'est le pic), mais `episode_start` est CONSERVÉ et `renew_count` monte.
Sans cette distinction (avant 2026-07-16), un émetteur qui ré-évalue sa condition
à chaque cycle — forge_health_diagnostic sous MAPE-K — remettait `released_at` à
zéro indéfiniment : une perturbation PERMANENTE paraissait éternellement fraîche
(age=0), le decay ne s'appliquait JAMAIS à une condition chronique, et un pic
isolé était indiscernable de six heures de stress continu.

Ce que la distinction rend mesurable — `HormoneReading.chronic` :
une hormone de STIMULATION qui ne redescend pas accuse son RÉCEPTEUR, pas son
émetteur. C'est le raisonnement clinique de l'endocrinologie : TSH haute + T4
basse = la thyroïde ne répond plus ; ACTH haute + cortisol bas = Addison. Ici,
TSH_VECTORIZATION chronique = personne ne vectorise (récepteur mort ou impuissant).
Le rétro-contrôle négatif du vivant passe par le PRODUIT de la réponse (T4 inhibe
TRH) ; Nokido n'a que le capteur qui re-mesure — la chronicité est donc son SEUL
témoin disponible d'un effecteur défaillant. Corollaire McEwen : un épisode qui
dure est une charge allostatique, pas une régulation qui marche.

Extinction ACTIVE : il n'existe pas de clear()/inhibit(). `release(h, level=0.0)`
en tient lieu — le niveau passe sous le plancher 0.01 → `expired` → le prochain
release ouvre un NOUVEL épisode. Sinon, seules sorties : le TTL, ou purge_expired().

SOMMATION MULTI-GLANDES — CORRIGÉE le 2026-07-26 (mandat owner). `hormone` reste
PRIMARY KEY, mais release() ne se contente plus d'écraser : les contributions sont
tenues PAR SOURCE dans `meta._contrib`, sommées puis plafonnées à SATURATION_CEILING.
Une même glande qui ré-émet RAFRAÎCHIT sa part (pas de double comptage) ; deux glandes
distinctes s'AJOUTENT. Un pic à 1.0 de forge_coagulation_cascade n'est donc plus effacé
par un 0.1 émis ailleurs. La PK composite n'a pas été nécessaire.

⚠️ Cet avertissement a annoncé « NON CORRIGÉE » pendant près d'un mois APRÈS la
correction, et une analyse externe l'a lu, l'a cru, et a recommandé de refaire le
travail (2026-08-21). Une limite qu'on lève doit être dé-déclarée dans le même geste :
un avertissement périmé coûte plus cher qu'un avertissement absent, parce qu'on lui
fait confiance.
=====
Chaque hormone a une demi-vie configurée. Le decay est appliqué à chaque cycle
de read() ou via un cron explicite. Si pas renouvelée, l'hormone tend vers 0.

USAGE
=====
    from forge_endocrine import release, read, scan, all_hormones

    # Émission par une glande
    release("CORTISOL_QUOTA_CLOUD", level=0.85, ttl_s=3600,
            source="forge_token_monitor", reason="cost_usd 4.2$/5.0$ daily")

    # Lecture par un récepteur
    cortisol = read("CORTISOL_QUOTA_CLOUD")
    if cortisol > 0.5:
        # forge_llm_router adapte la cascade
        ...

    # Scan global pour debug / monitoring
    print(scan())
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent

# SSoT du chemin DB = forge_db_path.db_path(). SURTOUT PAS `ROOT/"RAG"/"embeddings.db"` :
# ce chemin est un SYMLINK C: -> V:, et écrire à travers lui lève « attempt to write a
# readonly database » depuis tout contexte non-service (sandbox, runners), parce que le
# journal -wal/-shm ne peut pas être créé côté C:. Ce module codait le symlink EN DUR —
# exactement la faute que forge_db_path a été écrit pour empêcher (« Source de vérité
# unique du chemin DB — les modules qui écrivent doivent passer par db_path() »), et qui
# a déjà cassé EN SILENCE create_job (veille morte 5j), access_count, l'eco-embed et
# watch_jobs. Corrigé le 2026-07-16.
# Effet voulu : l'override `LAFORGE_DB` est désormais honoré ici aussi.
# NB : `_conn()` relit ce global à CHAQUE appel — c'est ce qui permet aux tests de
# rediriger l'organe (monkeypatch fe.DB, cf tests/conftest.py) sans que le code de
# production ait à savoir qu'il est testé.
try:
    from nokido_agent.app.forge_db_path import db_path as _db_path

    DB = Path(_db_path())
except Exception:  # bootstrap / import isolé -> repli sur l'ancien chemin
    DB = ROOT / "RAG" / "embeddings.db"

# Demi-vies par défaut (peut être override par release(ttl_s=...))
DEFAULT_HALF_LIVES = {
    "INSULIN_VECTORIZATION": 1800,  # 30 min
    "TSH_VECTORIZATION": 3600,  # 1h
    "CORTISOL_QUOTA_CLOUD": 7200,  # 2h
    "ADRENALINE_HUB_PRESSURE": 600,  # 10 min (réaction rapide)
    "LEPTIN_MAILBOX_FULL": 3600,  # 1h
    "DOPAMINE_SUCCESS": 1800,  # 30 min
    "CORTISOL_FRUSTRATION": 3600,  # 1h — échecs dialogue (forge_motivation.punish)
    "DIALOGUE_SATISFACTION": 1800,  # 30 min — réussite dialogue (AXE 8)
}

# ── RÉCEPTEURS : qui CONSOMME chaque hormone ─────────────────────────────────
# Mandat owner 2026-07-26 (bibliographie ApiNATOMY : un signal circule vers des
# cibles NOMMÉES, il ne se diffuse pas dans le vide).
#
# Le défaut réparé ici n'est pas l'absence de topologie — la mesure du 2026-07-26
# montre 6 hormones émises sur 7 avec un lecteur réel. C'est que cette topologie
# n'était DÉCLARÉE nulle part : elle ne se découvrait qu'en grepant `read("X")`.
# Une hormone émise sans récepteur est l'équivalent d'un ligand sans récepteur —
# le signal existe, l'effet est nul, et rien ne le signalait.
#
# `forge_hormones.py` porte déjà le modèle (release(..., receptors=[]),
# receptors_for(role), SSE). Ici on ne le duplique pas : on donne au registre
# endocrinien SQLite la même notion, sous forme déclarative.
#
# Liste = lecteurs MESURÉS le 2026-07-26 (occurrences de read/read_full/
# trigger_hormone). Minimum garanti, pas plafond : `tools/forge_body_regulation_audit.py`
# reste juge de la réalité du câblage.
# Saturation des récepteurs : plafond de la SOMME des sécrétions. Le vivant somme,
# mais il sature — sinon N glandes suffisent à épingler un signal au maximum, et
# `chronic` diagnostiquerait un stress permanent qui n'existe pas.
# Le census classait ce module en « ? non classe » (mesure 2026-07-26 via
# tools/forge_organ_edges.py) alors qu'il porte 30 dependants directs et 265 en
# aval. Un module que personne ne range est un module dont personne ne surveille la
# regulation : on declare donc son organe, comme l'exige RULES_SHARED (« un module
# NEUF declare son organe — le code nourrit le corps »).
__FORGE_COLOR__ = "vegetatif/endocrine"

SATURATION_CEILING = 1.0

RECEPTORS: dict[str, tuple[str, ...]] = {
    "INSULIN_VECTORIZATION": ("app/forge_rag_warmup.py",),
    "TSH_VECTORIZATION": ("app/forge_rag_warmup.py", "app/forge_pluripotent_workers.py"),
    "CORTISOL_QUOTA_CLOUD": ("app/forge_internal_sampling.py", "app/forge_endocrine.py"),
    "LEPTIN_MAILBOX_FULL": ("app/forge_pluripotent_workers.py",),
    "DOPAMINE_SUCCESS": ("app/forge_persona_engine.py", "app/forge_pluripotent_workers.py"),
    "CORTISOL_FRUSTRATION": ("app/forge_novelty_search.py", "app/forge_persona_engine.py"),
    "ADRENALINE_HUB_PRESSURE": (),
    "DIALOGUE_SATISFACTION": (),
}

# Une absence de récepteur ASSUMÉE doit être motivée, sinon on ne distingue pas
# « personne n'écoute, c'est voulu » de « personne n'écoute, on ne l'a pas vu ».
NO_RECEPTOR_REASON: dict[str, str] = {
    "ADRENALINE_HUB_PRESSURE":
        "émise par forge_coagulation_cascade ; aucun consommateur VÉRIFIÉ. "
        "Délibérément non câblée : brancher un effecteur sur un signal dont on n'a "
        "pas mesuré l'effet, c'est fabriquer une régulation qui ne régule rien.",
    "DIALOGUE_SATISFACTION":
        "déclarée dans DEFAULT_HALF_LIVES mais JAMAIS émise (mesure 2026-07-26) — "
        "vocabulaire réservé pour l'AXE 8, conservé volontairement.",
}


def _warn(msg: str, *args) -> None:
    """Avertissement sans supposer de logger module : `forge_endocrine` n'en déclare
    aucun et n'importe pas `logging` (vérifié 2026-07-26). Import local, donc aucun
    coût quand la voie normale est prise."""
    import logging

    logging.getLogger("forge_endocrine").warning(msg, *args)


def receptors(hormone: str) -> tuple[str, ...]:
    """Modules déclarés consommateurs de cette hormone. () = aucun."""
    return RECEPTORS.get(hormone, ())


def orphans() -> list[dict]:
    """Hormones sans récepteur déclaré. `assumed` distingue l'absence MOTIVÉE de
    l'angle mort. Lecture pure : aucun scan de code, aucun coût."""
    out = []
    for h in DEFAULT_HALF_LIVES:
        if receptors(h):
            continue
        out.append({
            "hormone": h,
            "assumed": h in NO_RECEPTOR_REASON,
            "reason": NO_RECEPTOR_REASON.get(h, "AUCUNE justification déclarée — angle mort"),
        })
    return out


@dataclass
class HormoneReading:
    name: str
    level: float  # 0.0 ... 1.0+ (peut > 1.0 si dosage extrême)
    fresh_level: float  # niveau au moment de release (avant decay)
    age_s: int  # secondes depuis release
    ttl_s: int
    half_life_s: int
    source: str
    reason: str
    expired: bool
    # Chronicité (2026-07-16) — un ÉPISODE = suite de release() sans extinction.
    # Défauts tolérants : une row antérieure à la migration se lit comme un
    # épisode d'une seule émission.
    episode_start: str = ""  # ISO du DÉBUT de l'épisode (≠ released_at si renouvelée)
    episode_age_s: int = 0  # durée de l'épisode en cours
    renew_count: int = 0  # nb de ré-émissions depuis episode_start

    @property
    def chronic(self) -> bool:
        """L'épisode résiste à l'effecteur : la perturbation ne se résout pas.

        Deux conditions, et la première n'est PAS optionnelle :
        1. l'hormone est ENCORE HAUTE (`not expired`). Chronique = soutenue ET
           élevée. Sans ce garde, toute ligne morte depuis des semaines passait
           pour chronique — mesuré le 2026-07-16 : `adrenaline` level=0.000
           depuis 50 jours ressortait chronic=True. Ce sont des DÉBRIS que
           purge_expired() n'a jamais ramassés, pas du stress chronique.
           Confondre les deux, c'est diagnostiquer une pathologie sur un cadavre.
        2. l'épisode dure > 4 demi-vies. Seuil DÉRIVÉ de la pharmacocinétique de
           l'hormone, pas arbitraire : après 4 demi-vies un signal non renouvelé
           est retombé sous 6.25%. S'il tient ENCORE le niveau, c'est qu'une
           glande le soutient activement contre un récepteur qui n'y répond pas.

        Un signal chronique accuse le RÉCEPTEUR, jamais l'émetteur.
        """
        return (not self.expired) and self.episode_age_s > self.half_life_s * 4


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Crée la table endocrine_signals si absente."""
    conn.execute("""CREATE TABLE IF NOT EXISTS endocrine_signals (
        hormone       TEXT PRIMARY KEY,
        level         REAL NOT NULL,
        released_at   TEXT NOT NULL,
        ttl_s         INTEGER NOT NULL,
        half_life_s   INTEGER NOT NULL,
        source        TEXT NOT NULL,
        reason        TEXT,
        meta          TEXT,
        episode_start TEXT,
        renew_count   INTEGER NOT NULL DEFAULT 0
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_endocrine_released ON endocrine_signals(released_at)")
    # Migration en place des DB antérieures à la chronicité (2026-07-16). ADD COLUMN
    # est O(1) en SQLite (métadonnées seules) — pas de réécriture des 8 Go de V:.
    # Les rows existantes prennent NULL/0 ; read_full retombe alors sur released_at,
    # soit un épisode d'une seule émission. Aucun appelant existant n'est impacté.
    for ddl in (
        "ALTER TABLE endocrine_signals ADD COLUMN episode_start TEXT",
        "ALTER TABLE endocrine_signals ADD COLUMN renew_count INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # colonne déjà présente
    conn.commit()


def _age_s(released_at: str) -> int:
    """Âge en secondes d'un timestamp SQLite datetime('now') (UTC naïf).

    Phase 19 (2026-05-24) fix : datetime.utcnow() deprecated Py 3.12+. Switch
    vers datetime.now(timezone.utc) puis strip tz pour comparer avec rel_dt naif.
    TODO migration schema : passer released_at REAL (time.time() unix seconds)
    pour unifier avec forge_hormones.py et forge_critical_events.py. Pas fait
    ici pour eviter migration cassante des rows existantes.
    """
    try:
        from datetime import datetime, timezone

        rel_dt = datetime.fromisoformat(released_at.replace(" ", "T"))
        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        return max(0, int((now_utc_naive - rel_dt).total_seconds()))
    except Exception:
        return 0


def release(
    hormone: str,
    level: float,
    *,
    ttl_s: Optional[int] = None,
    source: str = "unknown",
    reason: str = "",
    meta: Optional[dict] = None,
) -> dict:
    """Émet une hormone, en SOMMANT les sécrétions des glandes distinctes.

    Une même `source` qui ré-émet RAFRAÎCHIT sa contribution ; deux sources
    différentes s'AJOUTENT, la somme étant plafonnée à SATURATION_CEILING (cf. le
    bloc « SOMMATION DES SÉCRÉTIONS » plus bas). `release(h, 0.0)` éteint TOUT le
    signal, pas seulement la part de la glande appelante.

    level : 0.0-1.0 typique (mais peut dépasser 1.0 pour dosage extrême)
    ttl_s : durée maximale avant expiry totale (default 4× half_life)
    """
    half = DEFAULT_HALF_LIVES.get(hormone, 1800)
    if ttl_s is None:
        ttl_s = half * 4

    # Ligand sans récepteur : on émet quand même (l'émission n'est pas le lieu où
    # l'on censure un signal), mais on refuse le silence. Une hormone INCONNUE du
    # registre est le cas dangereux : personne n'a déclaré qui doit l'entendre.
    if hormone not in RECEPTORS:
        _warn("hormone %s émise sans entrée RECEPTORS — ligand sans récepteur déclaré "
              "(source=%s) : déclarer son consommateur ou motiver son absence",
              hormone, source)
    elif not RECEPTORS[hormone] and hormone not in NO_RECEPTOR_REASON:
        _warn("hormone %s émise, récepteurs vides et absence NON motivée (source=%s)",
              hormone, source)

    # Un épisode CONTINUE tant que l'hormone précédente n'est pas éteinte : on garde
    # son début et on compte la ré-émission. read_full() porte déjà decay+expiry —
    # on la réutilise plutôt que de redériver le critère d'extinction ici.
    prev = read_full(hormone)
    if prev and not prev.expired:
        episode_start = prev.episode_start
        renew_count = prev.renew_count + 1
    else:
        episode_start = None  # -> COALESCE datetime('now') = NOUVEL épisode
        renew_count = 0

    # ── SOMMATION DES SÉCRÉTIONS (mandat owner 2026-07-26) ────────────────────
    # Défaut corrigé, documenté depuis longtemps en tête de module et MESURÉ ce
    # jour : `hormone` est PRIMARY KEY + INSERT OR REPLACE, donc deux glandes qui
    # émettent la même hormone s'ÉCRASENT au lieu de s'additionner. Ça mord vraiment :
    #   CORTISOL_QUOTA_CLOUD = 4 émetteurs (forge_econome, forge_health_diagnostic,
    #   forge_endocrine, +1) · DOPAMINE_SUCCESS = 2 · CORTISOL_FRUSTRATION = 2.
    # Quand l'économe et le diagnostic signalaient tous deux le coût, l'un effaçait
    # l'autre — et le corps n'entendait qu'une seule voix.
    #
    # Deux garde-fous que la biologie impose, et sans lesquels « sommer » serait pire
    # que le défaut :
    #   1. MÊME GLANDE = RAFRAÎCHISSEMENT, pas double comptage. Une glande qui
    #      re-sécrète maintient son niveau ; deux glandes distinctes s'ajoutent.
    #      D'où une contribution PAR SOURCE, la nouvelle remplaçant la précédente.
    #   2. SATURATION. La somme est plafonnée (SATURATION_CEILING) — mais jamais en
    #      dessous de ce que l'appelant demande, pour ne pas trahir un dosage
    #      extrême explicite.
    #
    # Décroissance exacte SANS horodatage par glande : entre deux écritures, toutes
    # les contributions vieillissent du MÊME temps (prev.age_s). Le facteur commun
    # 0.5^(age/half) leur est donc appliqué en bloc — même loi que read_full().
    _contrib: dict[str, float] = {}
    if prev and not prev.expired:
        _c = _conn()
        try:
            _r = _c.execute(
                "SELECT meta FROM endocrine_signals WHERE hormone = ?", (hormone,)
            ).fetchone()
        finally:
            _c.close()
        try:
            _prev_meta = json.loads((_r[0] if _r else None) or "{}")
            _contrib = {str(k): float(v)
                        for k, v in (_prev_meta.get("_contrib") or {}).items()}
        except Exception:  # noqa: BLE001  — meta illisible : on repart propre
            _contrib = {}
        if _contrib:
            _f = math.pow(0.5, prev.age_s / max(half, 1))
            # On laisse tomber les contributions éteintes (< plancher de read_full)
            _contrib = {k: v * _f for k, v in _contrib.items() if v * _f >= 0.01}

    _new = max(0.0, float(level))
    if _new <= 0.0:
        # Extinction ACTIVE : release(level=0.0) tient lieu de clear() (cf. en-tête).
        # Elle doit éteindre TOUT le signal, pas seulement la part de cette glande.
        _contrib = {}
    else:
        _contrib[source] = _new
    _effective_level = min(max(SATURATION_CEILING, _new), sum(_contrib.values()))
    _meta_out = dict(meta or {})
    _meta_out["_contrib"] = {k: round(v, 4) for k, v in _contrib.items()}

    _sql = (
        "INSERT OR REPLACE INTO endocrine_signals "
        "(hormone, level, released_at, ttl_s, half_life_s, source, reason, meta, "
        "episode_start, renew_count) "
        "VALUES (?, ?, datetime('now'), ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), ?)"
    )
    _args = (
        hormone,
        _effective_level,
        int(ttl_s),
        int(half),
        source,
        reason or "",
        json.dumps(_meta_out, ensure_ascii=False),
        episode_start,
        int(renew_count),
    )

    # MESURÉ 2026-07-26 : cette écriture rendait `database is locked` dès qu'une
    # ingestion écrivait en parallèle — et une écriture SQLite qui rend ce verrou
    # est PERDUE si personne ne la reprend. Conséquence : le système endocrinien
    # lâchait sous charge, c'est-à-dire exactement quand réguler compte. On reprend
    # avec `write_retry` (recul croissant AVEC jitter ; sans jitter N écrivains
    # repartent à la même milliseconde et se rebloquent). Il ne reprend QUE les
    # erreurs de verrou : une contrainte violée remonte tout de suite.
    def _do(conn):
        _ensure_schema(conn)
        conn.execute(_sql, _args)
        return True

    # ÉCRIRE LÀ OÙ L'ON LIT. `write_retry` ouvre sa PROPRE connexion, vers
    # forge_db_path.db_path() — alors que `_conn()`, donc read_full(), suit le global
    # `DB`. Quand `DB` est REDIRIGÉ (tests via monkeypatch, base alternative), les deux
    # divergeaient. Mesuré le 2026-08-21, DB pointé sur un fichier temporaire :
    #   release() rendait {'level': 0.9}  -> succès annoncé
    #   la table du temp restait VIDE     -> read() rendait 0.0
    #   la ligne atterrissait dans V:     -> la base de PRODUCTION
    # L'isolation demandée par tests/conftest.py était donc illusoire dans un sens
    # (les tests polluaient le vivant) et muette dans l'autre (ils ne relisaient rien) :
    # tout test endocrinien passait sans rien mesurer. On n'emprunte le socle — et son
    # retry anti-verrou, précieux sous charge — QUE lorsque les deux chemins coïncident.
    _socle = None
    try:
        from nokido_agent.app import forge_db_path as _dbp

        if str(_dbp.db_path()) == str(DB):
            _socle = _dbp
    except ImportError:  # socle absent : on n'empire pas
        pass

    if _socle is not None:
        _socle.write_retry(_do)
    else:
        conn = _conn()
        try:
            _do(conn)
            conn.commit()
        finally:
            conn.close()
    # APRES l'ecriture : on constate une secretion FAITE, pas une intention. Compter
    # avant fabriquerait un emetteur fantome, et un capteur de couplage qui invente
    # un emetteur est pire qu'un capteur muet -- il ferme l'enquete.
    _constater_emission(hormone)
    return {
        "hormone": hormone,
        "level": level,
        "ttl_s": ttl_s,
        "half_life_s": half,
        "source": source,
        "renew_count": renew_count,
    }


def _constater_emission(hormone: str) -> None:
    """CONSTATE la secretion pour le capteur de couplage (`forge_signal_coupling`).

    Pose au CHOKEPOINT de la glande et non chez chaque appelant : biologiquement
    l'observable est la secretion, pas l'intention de secreter -- et pratiquement,
    une seule pose couvre toutes les hormones, presentes et futures. L'analyse
    statique ne pouvait pas rendre ce service : elle a rate une ecriture passant par
    une clef de configuration (mesure 2026-07-30 sur `llama.wanted`, 14 lectures
    trouvees, 0 ecriture, verdict FAUX).
    """
    try:
        from nokido_agent.app.forge_signal_coupling import emit_signal
        emit_signal(hormone, emitter="forge_endocrine.release")
    except Exception:
        pass  # muet-ok : l'observabilite ne casse JAMAIS la secretion qu'elle observe


def read(hormone: str) -> float:
    """Lit le niveau actuel d'une hormone (avec decay appliqué)."""
    r = read_full(hormone)
    return r.level if r else 0.0


def read_full(hormone: str) -> Optional[HormoneReading]:
    """Lecture détaillée avec metadata."""
    conn = _conn()
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT hormone, level, released_at, ttl_s, half_life_s, source, reason, "
        "episode_start, renew_count "
        "FROM endocrine_signals WHERE hormone = ?",
        (hormone,),
    ).fetchone()
    conn.close()
    if not row:
        return None

    fresh_level = float(row[1])
    released_at = row[2]
    ttl_s = int(row[3])
    half_life_s = int(row[4])
    source = row[5] or ""
    reason = row[6] or ""
    # Row antérieure à la migration chronicité : pas d'épisode connu -> ce release
    # EST l'épisode (age = episode_age, renew = 0). Dégradation honnête, pas de faux.
    episode_start = row[7] or released_at
    renew_count = int(row[8] or 0)

    age_s = _age_s(released_at)
    episode_age_s = _age_s(episode_start)

    # Decay exponentiel : level(t) = fresh_level * 0.5^(age/half_life)
    decay_factor = math.pow(0.5, age_s / max(half_life_s, 1))
    level = fresh_level * decay_factor

    expired = age_s > ttl_s or level < 0.01

    return HormoneReading(
        name=hormone,
        level=level,
        fresh_level=fresh_level,
        age_s=age_s,
        ttl_s=ttl_s,
        half_life_s=half_life_s,
        source=source,
        reason=reason,
        expired=expired,
        episode_start=episode_start,
        episode_age_s=episode_age_s,
        renew_count=renew_count,
    )


def scan() -> list[HormoneReading]:
    """Scan toutes les hormones actives."""
    conn = _conn()
    _ensure_schema(conn)
    rows = conn.execute("SELECT hormone FROM endocrine_signals ORDER BY released_at DESC").fetchall()
    conn.close()
    out = []
    for (h,) in rows:
        r = read_full(h)
        if r:
            out.append(r)
    return out


def purge_expired(dry: bool = False) -> int:
    """Clairance : retire les hormones ÉTEINTES. Retourne le nb de lignes visées.

    Critère = `released_at`, donc le DERNIER pic — JAMAIS `episode_start`. Une
    hormone chronique est RENOUVELÉE, son released_at est frais : elle est donc
    protégée par construction. On ne ramasse que ce que plus aucune glande ne
    soutient. C'est de la clairance, pas de la censure de signal — effacer un
    chronique reviendrait à supprimer le diagnostic (cf HormoneReading.chronic,
    où une stimulante qui ne redescend pas accuse son récepteur).

    Seuil = 8× la plus longue demi-vie (~16 h), très au-delà du TTL le plus long :
    à ce stade la ligne n'est plus un signal, c'est un débris.

    ⚠️ Cette fonction a existé sans JAMAIS être appelée. Mesuré le 2026-07-16 :
    9 des 13 lignes du sang étaient éteintes depuis 2 à 50 JOURS (`adrenaline`
    level=0.000, age 50j), et le gate firehose flaggait la table à chaque commit
    (« CREATE TABLE endocrine_signals non référencée dans forge_log_retention.py
    -> croissance illimitée »). Une fonction de clairance sans éboueur RÉSIDENT
    qui la déclenche est une zone morte. Le déclencheur est désormais
    tools/forge_log_retention.py::_purge_endocrine_signals.
    """
    conn = _conn()
    _ensure_schema(conn)
    cutoff = max(DEFAULT_HALF_LIVES.values()) * 8
    where = "(julianday('now') - julianday(released_at)) * 86400 > ?"
    if dry:
        n = conn.execute("SELECT COUNT(*) FROM endocrine_signals WHERE " + where, (cutoff,)).fetchone()[0]
        conn.close()
        return int(n)
    n = conn.execute("DELETE FROM endocrine_signals WHERE " + where, (cutoff,)).rowcount
    conn.commit()
    conn.close()
    return n


def all_hormones() -> dict:
    """Inventaire complet des hormones canoniques (catalogue)."""
    return {
        h: {
            "default_half_life_s": tt,
            "description": _HORMONE_DESCRIPTIONS.get(h, ""),
        }
        for h, tt in DEFAULT_HALF_LIVES.items()
    }


_HORMONE_DESCRIPTIONS = {
    "INSULIN_VECTORIZATION": "Saturation atteinte côté embedding (>95% chunks vectorisés). "
    "Effet récepteur : reduce batch size embedding (économie GPU).",
    "TSH_VECTORIZATION": "Déficit vectorisation (<80%). Effet récepteur : forge_rag_warmup boost batch + priorité GPU.",
    "CORTISOL_QUOTA_CLOUD": "Stress cloud cost — quota >80% du daily_budget. "
    "Effet récepteur : forge_llm_router force cascade local-first.",
    "ADRENALINE_HUB_PRESSURE": "Pression hub MCP — req/min anormale. Effet récepteur : "
    "biblio_worker / rss_watcher / skill_enricher allongent intervals.",
    "LEPTIN_MAILBOX_FULL": "Mailbox saturée (unread_pct > 50%). Effet récepteur : "
    "purge automatique des messages > 7j ou alert humain.",
    "DOPAMINE_SUCCESS": "Renforcement positif après anchor_solution(quality > 0.85). "
    "Effet récepteur : skill_enricher priorise les domains avec dopamine.",
    "CORTISOL_FRUSTRATION": "Échecs répétés (forge_motivation.punish, dialogue inclus). "
    "Effet récepteur : forge_persona_engine module la voix (prudence/exploration).",
    "DIALOGUE_SATISFACTION": "Réussite d'un échange (AXE 8 forge_dialogue_outcome). "
    "Effet récepteur : persona confiance/concision + exemplars few-shot.",
}


# ============================================================================
# CLI debug / monitoring
# ============================================================================

if __name__ == "__main__":
    import argparse, sys

    ap = argparse.ArgumentParser(description="Nokido endocrine debug CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rel = sub.add_parser("release", help="Émettre une hormone")
    p_rel.add_argument("hormone")
    p_rel.add_argument("--level", type=float, required=True)
    p_rel.add_argument("--source", default="cli")
    p_rel.add_argument("--reason", default="")
    p_rel.add_argument("--ttl", type=int)

    p_read = sub.add_parser("read", help="Lire une hormone")
    p_read.add_argument("hormone")

    sub.add_parser("scan", help="Inventaire des hormones actives")
    sub.add_parser("catalog", help="Inventaire des hormones canoniques")
    sub.add_parser("purge", help="DELETE expired")

    args = ap.parse_args()
    if args.cmd == "release":
        print(
            json.dumps(
                release(args.hormone, args.level, ttl_s=args.ttl, source=args.source, reason=args.reason), indent=2
            )
        )
    elif args.cmd == "read":
        r = read_full(args.hormone)
        print(json.dumps(r.__dict__ if r else None, indent=2, default=str, ensure_ascii=False))
    elif args.cmd == "scan":
        for r in scan():
            # ASCII seul : le daemon print() sur un stdout cp1252 (Windows).
            mark = "  <<< CHRONIQUE, recepteur suspect" if r.chronic else ""
            print(
                f"{r.name:30s} level={r.level:.3f} age={r.age_s}s "
                f"episode={r.episode_age_s}s renew={r.renew_count} "
                f"half={r.half_life_s}s src={r.source} expired={r.expired}{mark}"
            )
    elif args.cmd == "catalog":
        print(json.dumps(all_hormones(), indent=2, ensure_ascii=False))
    elif args.cmd == "purge":
        n = purge_expired()
        print(f"purged {n} expired hormones")
    sys.exit(0)
