# -*- coding: utf-8 -*-
"""
forge_token_monitor.py — Token & coût monitor Nokido
======================================================
Calcule les coûts réels, surveille les latences et détecte les dérives.
Branché sur token_usage existant + network_log.

Pricing ($/1M tokens, avril 2026) :
  Groq llama-3.3-70b    : input $0.59  output $0.79
  SambaNova llama-3.3   : input $1.32  output $2.20
  Mistral Large         : input $2.00  output $6.00
  Gemini 2.5 Flash      : input $0.15  output $0.60
  DeepSeek V3           : input $0.27  output $1.10
  Ollama local          : $0.00
  Groq llama-3.1-8b     : input $0.05  output $0.08
"""

from __future__ import annotations
import json, logging, math, os, sqlite3, time, urllib.request
from pathlib import Path
from typing import Iterable

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent

# Ce module n'avait AUCUN journal. Mesure du 2026-09-22 : la premiere version du
# correctif ci-dessous appelait `logger.error` dans un `except` -- donc un
# `NameError` LEVE DEPUIS UN GESTIONNAIRE D'EXCEPTION, qui aurait masque la cause
# qu'il pretendait reveler. Piege deja paye et consigne (`forge_web_fetch` n'avait
# aucun logger : son garde levait un NameError a son PREMIER declenchement,
# invisible a l'AST comme a la relecture). Il a suffi d'executer le module pour
# le voir -- ce qu'aucune lecture n'aurait donne.
logger = logging.getLogger("Nokido.TokenMonitor")


class _CheminJournal(os.PathLike):
    """Chemin d'un journal, resolu a CHAQUE acces, jamais fige a l'import.

    `DB` etait une constante calculee a l'import. Figer un chemin partage par N
    processus interdit toute bascule a chaud, et un site qui bascule seul fait
    ecrire d'un cote et lire de l'autre (regle du depot : un etat partage bascule
    par un interrupteur GLOBAL lu a chaque appel). Les cinq
    `sqlite3.connect(str(DB), ...)` de ce module passent par ici sans changer de
    forme -- et tant que `sandbox/journaux.switch` est absent, `journal_path`
    rend la base HISTORIQUE : la migration ne change donc aucun comportement.

    Motif du chantier (owner 2026-09-19) : « on ne deplace pas des tables, on
    retire des ecrivains du verrou RAG ». token_usage = 4 644 prises du verrou en
    33 h, la plus grosse des trois.
    """

    __slots__ = ("_journal",)

    def __init__(self, journal: str) -> None:
        self._journal = journal

    def _resoudre(self) -> str:
        try:
            from forge_db_path import journal_path
        except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
            return str(ROOT / "RAG" / "embeddings.db")
        return journal_path(self._journal)

    def __fspath__(self) -> str:
        return self._resoudre()

    def __str__(self) -> str:
        return self._resoudre()

    def __repr__(self) -> str:
        return "<journal %s -> %s>" % (self._journal, self._resoudre())


DB = _CheminJournal("token_usage")
SNAPSHOT_PATH = ROOT / "data" / "litellm_snapshot.json"
SNAPSHOT_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"

# Pricing $/1M tokens — fast path pour les modèles canoniques Nokido.
PRICING: dict[str, dict] = {
    "llama-3.3-70b-versatile": {"in": 0.59, "out": 0.79},
    "groq/llama-3.3-70b-versatile": {"in": 0.59, "out": 0.79},
    "llama-3.1-8b-instant": {"in": 0.05, "out": 0.08},
    "sambanova/Meta-Llama-3.3-70B-Instruct": {"in": 1.32, "out": 2.20},
    "mistral-large-latest": {"in": 2.00, "out": 6.00},
    "mistral-small-latest": {"in": 0.20, "out": 0.60},
    "gemini-2.5-flash": {"in": 0.15, "out": 0.60},
    "gemini-2.0-flash": {"in": 0.10, "out": 0.40},
    "deepseek-chat": {"in": 0.27, "out": 1.10},
    "laforge-qwen:latest": {"in": 0.00, "out": 0.00},
    "qwen3:8b": {"in": 0.00, "out": 0.00},
}

# Seuils d'alerte
ALERT_COST_PER_CALL_USD = 0.05  # > 5 cents/appel → WARN
ALERT_LATENCY_MS = 15000  # > 15s → WARN
ALERT_DAILY_BUDGET_USD = 1.00  # > $1/jour → ERR
ALERT_TOKEN_PER_CALL = 8000  # > 8K tokens/appel → WARN


# ---- Snapshot LiteLLM (lazy, in-memory) ---------------------------------
_SNAPSHOT_CACHE: dict | None = None


def _load_snapshot() -> dict:
    """Lit le snapshot LiteLLM bundlé localement. Vide si absent (fallback PRICING)."""
    global _SNAPSHOT_CACHE
    if _SNAPSHOT_CACHE is not None:
        return _SNAPSHOT_CACHE
    try:
        payload = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        _SNAPSHOT_CACHE = payload.get("models") or payload  # tolère format brut
    except Exception:
        _SNAPSHOT_CACHE = {}
    return _SNAPSHOT_CACHE


def refresh_pricing(timeout: float = 30.0) -> dict:
    """Re-télécharge le snapshot LiteLLM depuis GitHub. Renvoie un résumé."""
    global _SNAPSHOT_CACHE
    req = urllib.request.Request(SNAPSHOT_URL, headers={"User-Agent": "Nokido-local/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    data = json.loads(raw)
    data.pop("sample_spec", None)
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {
            "source": SNAPSHOT_URL,
            "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model_count": len(data),
        },
        "models": data,
    }
    SNAPSHOT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    _SNAPSHOT_CACHE = data
    return {"model_count": len(data), "path": str(SNAPSHOT_PATH)}


# Gratuite PROUVEE : ces providers s'executent en local, aucune facturation
# tierce n'existe. C'est une preuve, pas une absence de tarif -- et c'est
# exactement la nuance qui manquait.
PROVIDERS_GRATUITS = {"ollama", "llamacpp", "router_local", "local", "lmstudio"}


def _pricing_lookup(model: str):
    """Renvoie (input_per_1M, output_per_1M) en USD. 0 si modèle inconnu (=local/free)."""
    # CORRECTION 2026-09-12 -- la docstring ci-dessus dit << 0 si modele
    # inconnu (=local/free) >> : cette equivalence est FAUSSE, et son cout a
    # ete mesure. `cost_usd = 0.0` sur 4663 lignes sur 7859, ZERO NULL, ollama
    # (gratuit) et groq (tarife mais hors table) portant la meme valeur. Un
    # tarif absent n'est pas un tarif nul : on rend None, et la gratuite se
    # PROUVE par le provider, jamais par l'absence d'une entree.
    if not model:
        return None
    if model in PRICING:
        p = PRICING[model]
        return float(p["in"]), float(p["out"])
    snap = _load_snapshot()
    spec = snap.get(model)
    if spec is None and "/" in model:  # tolère "groq/llama-..." vs "llama-..."
        spec = snap.get(model.split("/", 1)[1])
    if not spec:
        return None
    # LiteLLM stocke en USD/token → convertir en USD/1M
    in_pt = float(spec.get("input_cost_per_token") or 0.0) * 1_000_000
    out_pt = float(spec.get("output_cost_per_token") or 0.0) * 1_000_000
    return in_pt, out_pt


def _price(model: str, prompt_tok: int, comp_tok: int):
    """Calcule le coût en USD pour un appel (PRICING fast-path → snapshot LiteLLM)."""
    # Rend None quand le modele n'est pas tarife. None se propage jusqu'a la
    # colonne : un appelant qui somme ce retour doit le tester, plutot que
    # d'additionner un zero invente.
    tarif = _pricing_lookup(model)
    if tarif is None:
        return None
    in_per_m, out_per_m = tarif
    return (prompt_tok * in_per_m + comp_tok * out_per_m) / 1_000_000


# ---- Comptage de tokens texte / image -----------------------------------
def count_text_tokens(text: str, model: str = "gpt-4o", provider: str | None = None, online: bool = False) -> int:
    """Compte les tokens via forge_tokenizer (dispatch par provider).

    Backward-compat : signature (text, model) preservee. Sans `provider`,
    fallback openai/tiktoken (= comportement historique).

    Args:
        text: texte a tokeniser
        model: model_id (ex "gpt-4o", "claude-3-5-sonnet-...", "mistral-large-latest")
        provider: provider explicite (anthropic, google, mistral, cohere, ...).
                  Si None : derive du prefixe model (`anthropic/...`,
                  `google/...`) sinon "openai".
        online: autorise count_tokens distant (anthropic/google/cohere SDK).
    """
    if not text:
        return 0
    if provider is None:
        # Derive du prefixe model_id (style OpenRouter / Nokido)
        if model and "/" in model:
            provider = model.split("/", 1)[0]
        else:
            provider = "openai"
    try:
        from nokido_agent.app.forge_tokenizer import count_tokens as _ct

        return _ct(text, provider=provider, model=model, online=online)
    except Exception:
        # Ultime fallback (forge_tokenizer absent en dev exotique)
        try:
            import tiktoken  # type: ignore

            try:
                enc = tiktoken.encoding_for_model(model)
            except Exception:
                enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            return max(1, len(text) // 4)


def count_image_tokens(provider: str, width: int, height: int, model: str = "") -> int:
    """Tokens images selon les formules officielles par provider.

    OpenAI tile (gpt-4o, gpt-4.1, o-series) : scale long side <=2048, short side <=768,
        puis tiles 512px × 170 + 85 base.
    Anthropic : ceil(w*h/750).
    Gemini : <=384px sur les 2 dims → 258 ; sinon ceil(w/768)*ceil(h/768)*258.
    """
    p = (provider or "").lower()
    if width <= 0 or height <= 0:
        return 0
    if p.startswith("anthropic") or p.startswith("claude"):
        return int(math.ceil((width * height) / 750))
    if p.startswith("gemini") or p.startswith("google") or p.startswith("vertex"):
        if width <= 384 and height <= 384:
            return 258
        return int(math.ceil(width / 768) * math.ceil(height / 768) * 258)
    # OpenAI / défaut tile-based
    long_side, short_side = max(width, height), min(width, height)
    if long_side > 2048:
        scale = 2048 / long_side
        long_side, short_side = 2048, int(short_side * scale)
    if short_side > 768:
        scale = 768 / short_side
        short_side, long_side = 768, int(long_side * scale)
    tiles = math.ceil(long_side / 512) * math.ceil(short_side / 512)
    return tiles * 170 + 85


def estimate_precall(
    model: str,
    prompt_text: str = "",
    max_output_tokens: int = 0,
    images: Iterable[tuple[int, int]] | None = None,
    provider: str | None = None,
) -> dict:
    """Estimation **avant** l'appel : retourne breakdown + coût max anticipé.

    `images` = itérable de (width, height) en pixels.
    `provider` = override sinon dérivé du préfixe modèle.
    """
    prov = provider or (model.split("/", 1)[0] if "/" in model else "openai")
    text_tok = count_text_tokens(prompt_text or "", model)
    img_tok = sum(count_image_tokens(prov, w, h, model) for (w, h) in (images or []))
    in_per_m, out_per_m = _pricing_lookup(model)
    prompt_tok = text_tok + img_tok
    cost_in = (prompt_tok * in_per_m) / 1_000_000
    cost_out_max = (max_output_tokens * out_per_m) / 1_000_000
    return {
        "model": model,
        "provider": prov,
        "text_tokens": text_tok,
        "image_tokens": img_tok,
        "prompt_tokens": prompt_tok,
        "max_output_tokens": int(max_output_tokens),
        "input_per_1M_usd": round(in_per_m, 6),
        "output_per_1M_usd": round(out_per_m, 6),
        "estimated_cost_usd": round(cost_in + cost_out_max, 8),
        "input_cost_usd": round(cost_in, 8),
        "max_output_cost_usd": round(cost_out_max, 8),
        "is_local_or_unknown": (in_per_m == 0.0 and out_per_m == 0.0),
    }


# ---- Budget context manager ---------------------------------------------
class BudgetExceeded(RuntimeError):
    """Levé en mode strict quand l'estimation pré-call dépasse le budget restant."""


class Budget:
    """Garde-fou de coût session.

    >>> with Budget(max_cost_usd=0.10, strict=False) as b:
    ...     est = estimate_precall("gpt-4o", "hello", max_output_tokens=64)
    ...     b.check(est["estimated_cost_usd"])  # warn ou raise
    ...     b.charge(actual_cost_usd=0.0001)
    """

    def __init__(self, max_cost_usd: float, *, strict: bool = False, label: str = ""):
        self.max = float(max_cost_usd)
        self.strict = bool(strict)
        self.label = label or "default"
        self.spent = 0.0
        self.warnings: list[str] = []

    @property
    def remaining(self) -> float:
        return max(0.0, self.max - self.spent)

    def check(self, est_cost_usd: float) -> bool:
        """Pré-call : vérifie que l'estimation tient dans le budget restant."""
        if est_cost_usd <= self.remaining:
            return True
        msg = f"[Budget {self.label}] est {est_cost_usd:.6f}$ > remaining {self.remaining:.6f}$"
        self.warnings.append(msg)
        if self.strict:
            raise BudgetExceeded(msg)
        return False

    def charge(self, actual_cost_usd: float) -> float:
        """Post-call : déduit le coût réel."""
        self.spent += float(actual_cost_usd)
        return self.remaining

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False  # ne masque pas l'exception


def backfill_costs():
    """Recalcule cost_usd pour les entrées sans coût."""
    conn = sqlite3.connect(str(DB), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    rows = conn.execute(
        "SELECT id, model, prompt_tokens, completion_tokens FROM token_usage "
        "WHERE cost_usd=0 AND (prompt_tokens>0 OR completion_tokens>0)"
    ).fetchall()
    updated = 0
    for row_id, model, pt, ct in rows:
        cost = _price(model or "", pt or 0, ct or 0)
        if cost > 0:
            conn.execute("UPDATE token_usage SET cost_usd=? WHERE id=?", (cost, row_id))
            updated += 1
    conn.commit()
    conn.close()
    return updated


def migrer(conn) -> list:
    """Ajoute les colonnes manquantes a `token_usage`. Idempotent.

    DEMENAGE ici depuis `forge_llm_usage_adapters` le 2026-09-12 : un ADAPTER
    de formats fournisseurs n'a aucune raison de toucher la base. Le DDL suit
    le DML chez le proprietaire unique de la table.

    ALTER TABLE ADD COLUMN, jamais de recreation : les lignes anterieures
    gardent NULL, qui se lit << non mesure >> et surtout pas << zero >>. C'est
    la seule facon honnete de faire cohabiter l'ancien et le neuf dans la meme
    table -- et le corps ne supprime rien, il marque.
    """
    from forge_llm_usage_adapters import COLONNES_AJOUTEES  # type: ignore

    # CREATION AVANT ALTERATION. Mesure du 2026-09-22, dans la validation qui a
    # PRECEDE la bascule de `sandbox/journaux.switch` : sur une base NEUVE, cette
    # fonction faisait `ALTER TABLE token_usage` sur une table inexistante, donc
    # levait `no such table` -- et son appelant avalait l'exception. Les 6 720
    # ecritures de ce journal seraient parties dans le vide SANS BRUIT.
    #
    #     UNE ECRITURE AVALEE RESSEMBLE A UN SYSTEME CALME. UN CRASH SE VOIT.
    #
    # Le DDL ci-dessous est RELU depuis la base de production (sqlite_master),
    # jamais reconstitue de memoire : les treize colonnes historiques exactement,
    # les treize autres etant posees par les ALTER qui suivent. Inventer un
    # schema proche aurait produit une base qui accepte les INSERT et range les
    # valeurs ailleurs.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS token_usage ("
        " id TEXT PRIMARY KEY,"
        " ts TEXT DEFAULT (datetime('now')),"
        " agent_id TEXT,"
        " provider TEXT,"
        " model TEXT,"
        " prompt_tokens INTEGER DEFAULT 0,"
        " completion_tokens INTEGER DEFAULT 0,"
        " total_tokens INTEGER DEFAULT 0,"
        " cost_usd REAL DEFAULT 0.0,"
        " latency_ms REAL DEFAULT 0.0,"
        " source TEXT DEFAULT 'broker',"
        " session_id TEXT DEFAULT '',"
        " meta TEXT DEFAULT '{}'"
        ")"
    )
    presentes = {r[1] for r in conn.execute("PRAGMA table_info(token_usage)")}
    ajoutees = []
    for col, typ in sorted(COLONNES_AJOUTEES.items()):
        if col not in presentes:
            # Le TYPE DECLARE compte : SQLite rangerait une chaine dans une
            # colonne INTEGER sans protester (affinite de type), et le defaut
            # ne se verrait qu'au tri ou a la comparaison.
            conn.execute("ALTER TABLE token_usage ADD COLUMN %s %s" % (col, typ))
            ajoutees.append(col)
    conn.commit()
    return ajoutees


def log_call(
    agent_id: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    source: str = "broker",
    session_id: str = "",
    meta: dict = None,
    cost_usd: float = None,
    alerter: bool = True,
    cache_read_tokens: int = None,
    cache_write_tokens: int = None,
    reasoning_tokens: int = None,
    provenance: str = None,
    execution_mode: str = None,
    transport: str = None,
    execution_id: str = None,
    parent_execution_id: str = None,
    measurement_kind: str = None,
    measurement_source: str = None,
    cost_source: str = None,
) -> float:
    """Enregistre un appel LLM dans token_usage. RECORDER CANONIQUE.

    `UNIQUE_WRITER(token_usage) = ce module` (owner, 2026-09-12) : tout DDL et
    tout DML de cette table passent ici. Cliquet :
    `tests/nr/test_token_usage_unique_writer_nr.py`.

    `cost_usd` fourni est conserve TEL QUEL. Le raccordement des anciens
    writers (A3) devait etre strictement neutre : chacun portait sa propre
    table de prix, et recalculer aurait modifie des valeurs COMPTABLES sous
    couvert de plomberie. Unifier les baremes est une decision separee, datee,
    avec son propre NR.

    Compteurs a None = NON MESURE : `total_tokens` et `cost_usd` restent NULL
    au lieu de valoir 0. Un zero se somme en silence et fabrique une
    consommation nulle ; un NULL se voit et se compte comme non mesure. Le
    retour vaut donc None quand rien n'a ete mesure -- un appelant qui somme
    ce retour doit le tester.
    """
    import uuid

    mesure = prompt_tokens is not None and completion_tokens is not None
    total = (prompt_tokens + completion_tokens) if mesure else None

    # COUT a trois etats. Le defaut est UNKNOWN_PRICING : ne jamais retomber
    # sur la gratuite, car c'est ainsi qu'un tarif inconnu devient un zero
    # credible, puis une somme faussement precise.
    if cost_usd is not None:
        cost, cost_kind = cost_usd, "KNOWN"
        cost_source = cost_source or "caller"
    elif (provider or "").lower() in PROVIDERS_GRATUITS:
        cost, cost_kind = 0.0, "FREE"
        cost_source = cost_source or "local_provider"
    else:
        tarife = _price(model, prompt_tokens, completion_tokens) if mesure else None
        if tarife is None:
            cost, cost_kind, cost_source = None, "UNKNOWN_PRICING", None
        else:
            cost, cost_kind = tarife, "KNOWN"
            cost_source = cost_source or "price_table"

    # PROVENANCE : le recorder n'en DEDUIT aucune. Ni depuis `agent_id`, ni
    # depuis un nom de module, de processus ou une cmdline. Non transportee =
    # UNKNOWN, qui est un aveu et non une invention. C'est ce qui empeche
    # `forge_agent_proxy` de redevenir l'identite de 97,9 % des lignes.
    provenance = provenance or "UNKNOWN"
    execution_mode = execution_mode or "UNKNOWN"
    transport = transport or "UNKNOWN"
    measurement_kind = measurement_kind or ("REPORTED" if mesure else "UNKNOWN")

    conn = sqlite3.connect(str(DB), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    # Le proprietaire de la table garantit son schema avant d'y ecrire :
    # sans cela, un appelant qui transmet les compteurs de cache echouerait
    # sur une base ou les colonnes n'ont jamais ete ajoutees.
    try:
        migrer(conn)
    except Exception as _exc:  # noqa: BLE001
        # PLUS MUET. Un echec de schema precede TOUJOURS un echec d'ecriture, et
        # le `pass` d'origine faisait disparaitre la cause : l'appelant recevait
        # ensuite un `no such table` sans savoir POURQUOI la table manquait.
        # L'INSERT qui suit n'est pas protege : il levera, et c'est voulu --
        # l'echec du journal ne doit pas pouvoir etre pris pour une ecriture
        # reussie. Ce que cette ligne ajoute, c'est la CAUSE, pas le refus.
        logger.error(
            "[token_monitor] schema de token_usage NON GARANTI sur %s: %r — "
            "l'ecriture qui suit echouera, et ce message en est la cause",
            DB, _exc,
        )
    conn.execute(
        "INSERT OR IGNORE INTO token_usage "
        "(id,agent_id,provider,model,prompt_tokens,completion_tokens,"
        "total_tokens,cost_usd,latency_ms,source,session_id,meta,"
        "cache_read_tokens,cache_write_tokens,reasoning_tokens,"
        "provenance,execution_mode,transport,execution_id,"
        "parent_execution_id,measurement_kind,measurement_source,"
        "cost_kind,cost_source,writer_component) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            agent_id,
            provider,
            model,
            prompt_tokens,
            completion_tokens,
            total,
            cost,
            latency_ms,
            source,
            session_id,
            json.dumps(meta or {}),
            cache_read_tokens,
            cache_write_tokens,
            reasoning_tokens,
            provenance,
            execution_mode,
            transport,
            execution_id,
            parent_execution_id,
            measurement_kind,
            measurement_source,
            cost_kind,
            cost_source,
            agent_id,
        ),
    )
    # Alertes dans network_log.
    # ⚠️ PORTEE : cette ligne n'est ecrite QUE si un seuil est franchi (cout,
    # latence ou tokens). Le canal TOKENS ne temoigne donc pas des appels LLM,
    # seulement des appels ALERTANTS — 184 lignes sur 228 955 au 2026-08-12. Ne
    # pas le lire comme une couverture du trafic cloud.
    # `provider`, `model` et `session_id` sont deja sous la main (ils partent
    # dans la table d'usage juste au-dessus) : les omettre ici privait
    # network_log de la seule info qui dit CHEZ QUI part un appel, et laissait
    # `provider` renseigne 30 fois sur 228 955.
    # Un seuil ne se compare pas a None : un compteur NON MESURE ne doit ni
    # declencher l'alerte, ni la faire lever.
    alertant = (
        (cost is not None and cost > ALERT_COST_PER_CALL_USD)
        or (latency_ms is not None and latency_ms > ALERT_LATENCY_MS)
        or (total is not None and total > ALERT_TOKEN_PER_CALL)
    )
    # `alerter=False` : l'appelant porte DEJA sa propre alerte, avec ses
    # propres seuils. Laisser jouer les deux aurait ajoute des lignes a
    # network_log -- un effet de bord, donc un raccordement non neutre.
    # L'USAGE D'ABORD. MESURE 2026-09-25 : l'alerte ci-dessous visait `network_log`, table ABSENTE
    # de la base de journal depuis la bascule du 2026-09-22 ; l'exception tombait AVANT le commit
    # et emportait l'usage -- les appels les plus gros ou les plus lents n'etaient JAMAIS comptes.
    conn.commit()
    if alerter and alertant:
        status = "WARN"
        detail = "cost=%s$ lat=%sms tok=%s" % (
            "?" if cost is None else format(cost, ".4f"),
            "?" if latency_ms is None else format(latency_ms, ".0f"),
            "?" if total is None else total,
        )
        try:
            conn.execute(
                "INSERT INTO network_log "
                "(ts,direction,method,tool,agent,status,channel,meta,provider,model,"
                " latency_ms,session_id) "
                "VALUES (datetime('now'),'OUT','llm.call',?,?,?,?,?,?,?,?,?)",
                (model, agent_id, status, "TOKENS", detail[:200],
                 provider, model, latency_ms, session_id or ""),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:
            # L'alerte manque, l'usage est deja ecrit : on le DIT, sans l'emporter.
            logger.warning("[token_monitor] alerte TOKENS NON ecrite (%s) dans %s -- usage "
                           "compte quand meme (%s %s %s)", exc, DB, agent_id, model, detail)
    conn.close()
    return cost


def daily_report() -> dict:
    """Rapport coût + tokens du jour."""
    conn = sqlite3.connect(str(DB), timeout=5)
    rows = conn.execute("""
        SELECT
            provider, model,
            COUNT(*) as calls,
            SUM(prompt_tokens) as prompt_tok,
            SUM(completion_tokens) as comp_tok,
            SUM(total_tokens) as total_tok,
            SUM(cost_usd) as cost_usd,
            AVG(latency_ms) as avg_ms,
            MAX(latency_ms) as max_ms
        FROM token_usage
        WHERE ts >= date('now')
        GROUP BY provider, model
        ORDER BY cost_usd DESC
    """).fetchall()
    daily_cost = sum(r[6] for r in rows)
    conn.close()

    report = {
        "date": time.strftime("%Y-%m-%d"),
        "daily_cost_usd": round(daily_cost, 6),
        "alert": daily_cost > ALERT_DAILY_BUDGET_USD,
        "breakdown": [
            {
                "provider": r[0],
                "model": r[1],
                "calls": r[2],
                "prompt_tok": r[3],
                "comp_tok": r[4],
                "total_tok": r[5],
                "cost_usd": round(r[6], 6),
                "avg_ms": round(r[7] or 0, 0),
                "max_ms": round(r[8] or 0, 0),
            }
            for r in rows
        ],
    }
    return report


def session_report(session_id: str) -> dict:
    """Coût d'une session spécifique."""
    conn = sqlite3.connect(str(DB), timeout=5)
    rows = conn.execute(
        "SELECT SUM(total_tokens), SUM(cost_usd), COUNT(*), AVG(latency_ms) FROM token_usage WHERE session_id=?",
        (session_id,),
    ).fetchone()
    conn.close()
    return {
        "session_id": session_id,
        "total_tokens": rows[0] or 0,
        "cost_usd": round(rows[1] or 0, 6),
        "calls": rows[2] or 0,
        "avg_latency_ms": round(rows[3] or 0, 1),
    }


def top_expensive(n: int = 5) -> list:
    """Top N appels les plus coûteux."""
    conn = sqlite3.connect(str(DB), timeout=5)
    rows = conn.execute(
        "SELECT ts, agent_id, model, total_tokens, cost_usd, latency_ms "
        "FROM token_usage ORDER BY cost_usd DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()
    return [
        {"ts": r[0], "agent": r[1], "model": r[2], "tokens": r[3], "cost_usd": round(r[4], 6), "latency_ms": r[5]}
        for r in rows
    ]


if __name__ == "__main__":
    print("=== Backfill costs ===")
    n = backfill_costs()
    print(f"Mis à jour: {n} entrées")

    print("\n=== Rapport journalier ===")
    r = daily_report()
    print(json.dumps(r, indent=2, ensure_ascii=False))

    print("\n=== Top 5 coûteux ===")
    for e in top_expensive(5):
        print(f"  {e}")
