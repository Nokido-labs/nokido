# -*- coding: utf-8 -*-
"""Exécute en boucle les étapes des chaînes de veille stockées dans agent_chain_nodes.

Entrées : ChainExecutor (execute_pending, run_node, dispatch_agent, start_loop) ; le
lancement direct du fichier démarre start_loop, déclaré dans services.toml.
Rôles pris en charge : KeywordAgent, VerifyAgent, SearchAgent, RefineAgent,
CrawlAgent, IngestAgent, StoreAgent, via les fonctions de forge_watch_agent,
forge_crawl_tool et forge_embed_router (SearXNG, OpenAlex/arXiv, crawl web, LLM).
Écrit agent_chain_nodes, agent_chain_context et watch_jobs dans la base de db_path(),
avec reprise, budget de chaîne (statut stalled) et heartbeat toutes les 20 s dans
sandbox/chain_executor.heartbeat.
"""
import json, logging, re, sqlite3, time, os, asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Dict, List
import sys

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# stdout/stderr UTF-8 forcé : daemon actif de la veille, ne doit JAMAIS crasher
# sur un caractère non-cp1252 dans un print (cf incident worker '→' 2026-06-02).
#
# JAMAIS sous pytest. Mesuré le 2026-09-04 : `sys.stdout` y est le flux de CAPTURE,
# et le reconfigurer le referme sous les pieds des tests SUIVANTS du même worker
# (« ValueError: I/O operation on closed file » au setup). Le `try/except` ci-dessous
# ne protège de rien pour ce cas : l'appel RÉUSSIT, c'est son effet qui casse.
# 20 des 38 échecs du premier run xdist venaient de là. En séquentiel la CI passe
# `--capture=no`, donc il n'y a pas de capture à casser et le défaut reste invisible :
# il n'apparaît qu'en parallèle, où la capture est obligatoire.
if "pytest" not in sys.modules:
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_chain_executor.py', 42, exc_info=True)

logger = logging.getLogger("Nokido.ChainExecutor")
ROOT = Path(__file__).resolve().parent.parent
from nokido_agent.app.forge_db_path import db_path as _db_path  # realpath symlink C:->V: (writable)

DB = _db_path()

# BUDGETS. Chaque APPEL avait sa borne (timeout HTTP, timeout LLM) ; ni la CHAINE
# ni la boucle de crawl n'en avaient. Un job pouvait donc vieillir indefiniment en
# `retry_pending` sans que rien ne le declare bloque -- et « en cours depuis
# toujours » est indiscernable de « en cours » pour qui regarde la file.
_BUDGET_CHAINE_S = float(os.environ.get("LAFORGE_WATCH_BUDGET_S", "1800"))
_BUDGET_CRAWL_S = float(os.environ.get("LAFORGE_WATCH_CRAWL_BUDGET_S", "600"))


class _Resultats(list):
    """Liste de resultats de recherche portant le MOTIF d'un vide (sinon None)."""
    motif = None


MOTIF_SEARXNG_MUET = "SearXNG muet"
MOTIF_MOTEURS_BLOQUES = "moteurs bloqués"


def _crawl_complet(url: str, crawl, timeout: int = 15) -> dict:
    """arXiv : /abs/ ne porte que le RESUME (1 chunk par source, mesure 27/10). On tente /html/ (texte complet)
    d'abord, repli sur /abs/ si la page HTML est absente ou vide. Regle et seuil REPRIS de
    forge_research_agent (_ARXIV_ABS, _ARXIV_HTML_MIN), pas redefinis."""
    from nokido_agent.app.forge_research_agent import _ARXIV_ABS, _ARXIV_HTML_MIN
    m = _ARXIV_ABS.match(url or "")
    if m:
        html = "https://arxiv.org/html/%s" % m.group(1)
        try:
            det = crawl(html, timeout)
            if len((det or {}).get("text") or "") >= _ARXIV_HTML_MIN:
                det = dict(det)
                det["url_crawlee"] = html
                det["text"], det["habillage_retire"] = _sans_habillage_arxiv(det["text"])
                return det
        except Exception:  # noqa: BLE001 -- HTML indisponible : repli sur le resume, et on le DIT
            logging.getLogger(__name__).info("[crawl] arxiv html indisponible, repli /abs/ : %s", url)
    return crawl(url, timeout)


_ARXIV_PIED = "\nWe gratefully acknowledge support from our"


def _sans_habillage_arxiv(texte: str):
    """Page arxiv.org/html/ : ~6 600 car. de navigation et de table des matieres AVANT le titre (`# `), pied de
    page apres la fin (mesure 27/10, ingere tel quel dans 358 morceaux). On garde du titre H1 au pied ; sans titre
    reconnaissable, rien n'est coupe. Rend (texte, nb de caracteres retires) : la coupe dit COMBIEN."""
    debut = re.search(r"(?m)^# \S", texte or "")
    if not debut:
        return texte, 0
    fin = texte.rfind(_ARXIV_PIED)
    utile = texte[debut.start():fin if fin > debut.start() else len(texte)]
    retire = len(texte) - len(utile)
    if retire:
        logging.getLogger(__name__).info("[crawl] habillage arxiv retire : %d car. sur %d", retire, len(texte))
    return utile, retire


def _cle_url(url: str) -> str:
    """Cle de DEDUP d'une URL : schema, www et / final ignores ; arXiv sans version ni forme (abs/pdf/html).
    Mesure 27/10 : le meme article crawle deux fois sous http:// et https:// (Alive-Infer, SCIP 9.0) -> morceaux
    ingeres en double, l'id d'un morceau dependant de l'URL source."""
    u = re.sub(r"^www\.", "", re.sub(r"^https?://", "", (url or "").strip().lower())).rstrip("/")
    m = re.match(r"(?:export\.)?arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5}|[a-z\-]+/\d{7})(?:v\d+)?", u)
    return "arxiv:" + m.group(1) if m else u


def _ancre_presente(ancre: str, hay: str) -> bool:
    """Mot ENTIER, pas sous-chaine : « mba » trouve dans « Mamba » a fait ingerer de la reconstruction 3D (27/10)."""
    return re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(ancre), hay) is not None


def _plafond_ancrage(final: float, hay: str, anchors: list) -> float:
    """Veto d'ancrage DETERMINISTE. Avant (27/10) : plafond a 5.0 pour un seuil d'ingestion a 4.0 -> le hors-sujet
    passait quand meme (PME nigerianes, ancrees par le seul « stochastic »). Il faut au moins 2 ancres du theme
    quand il en fournit plusieurs ; sinon le score passe SOUS le seuil (visible, jamais ingere)."""
    if not anchors:
        return final
    besoin = 2 if len(anchors) >= 2 else 1
    hay = (hay or "").lower()
    if sum(1 for a in anchors if _ancre_presente(a, hay)) < besoin:
        return min(final, 3.0)
    return final


_DERNIER_MOTIF_VEILLES: dict = {}

# Owner 29/10 : chaines de veille a lancer EN PRIORITE ({"chains": ["wj_..."]}), relu a chaque passe.
import pathlib as _pathlib  # noqa: E402

_FICHIER_VEILLES_PRIORITAIRES = _pathlib.Path(__file__).resolve().parent.parent / "sandbox" / "veilles_prioritaires.json"


def _veilles_prioritaires() -> set:
    """Ensemble des chain_id prioritaires ; fichier absent ou illisible = ensemble vide (ordre d'arrivee seul), DIT."""
    try:
        if not _FICHIER_VEILLES_PRIORITAIRES.is_file():
            return set()
        d = json.loads(_FICHIER_VEILLES_PRIORITAIRES.read_text(encoding="utf-8"))
        return {str(c) for c in (d.get("chains") or []) if str(c).startswith("wj_")}
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).warning("[chain] priorite des veilles illisible (%s) : ordre d'arrivee",
                                            type(e).__name__)
        return set()


def _motif_veilles(log, motif: str) -> None:
    """WARNING une fois par motif (le worker repasse toutes les 30 s : sans ce filtre, le journal deborde)."""
    if _DERNIER_MOTIF_VEILLES.get("m") != motif:
        _DERNIER_MOTIF_VEILLES["m"] = motif
        log.warning("[chain] %s", motif)


def _ram_en_satiete() -> bool:
    """Predicat de satiete existant du corps (seuil _SUPERVISOR_SLEEP_RAM_THRESHOLD),
    SANS eviction. Mesure illisible -> False (fail-open, journalise)."""
    try:
        import psutil
        from nokido_agent.app.forge_resource_manager import _SUPERVISOR_SLEEP_RAM_THRESHOLD
        return float(psutil.virtual_memory().percent) >= _SUPERVISOR_SLEEP_RAM_THRESHOLD
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).debug("satiete RAM illisible", exc_info=True)
        return False


# Cout MARGINAL declare d'une veille quand sa dependance Docker est deja payee. L'ordre de grandeur (0,8 Go)
# est le cout d'UNE veille supplementaire, hors runtime WSL/Docker deja charge (mesure owner 29/10 : vmmemWSL
# 2,76 Go inclut le runtime, il ne doit pas etre impute a la veille). Constante nommee, volontairement simple :
# c'est la seule valeur que l'admission marginale compare a la RAM disponible, jamais le seuil global.
_COUT_MARGINAL_VEILLE_GO = 0.8

_FICHIER_CLAIMS_DOCKER = _pathlib.Path(__file__).resolve().parent.parent / "sandbox" / "docker.claims.json"
_FICHIER_HEARTBEAT_DOCKER = _pathlib.Path(__file__).resolve().parent.parent / "sandbox" / "docker_keeper.heartbeat"
# 4 ticks du keeper (30 s) : au-dela, le pouls ne prouve plus l'etat du moment.
_POULS_DOCKER_MAX_AGE_S = 120.0


def _ram_disponible_go() -> Optional[float]:
    """RAM reellement disponible en Go, meme unite que `ram_free_gb` du corps. Illisible -> None (jamais 0)."""
    try:
        import psutil
        return float(psutil.virtual_memory().available) / 1024 ** 3
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).debug("RAM disponible illisible", exc_info=True)
        return None


def _docker_daemon_up() -> bool:
    """Docker est-il joignable MAINTENANT ? Priorite au pouls du keeper (il teste le socket via `docker ps` et
    tourne avec le compte qui a le pipe) ; repli sur le CLI direct si le pouls est absent/perime. Un pouls
    frais qui dit `daemon_up: False` est cru : on ne retombe pas sur une supposition plus optimiste."""
    try:
        d = json.loads(_FICHIER_HEARTBEAT_DOCKER.read_text(encoding="utf-8"))
        age = time.time() - float(d.get("ts") or 0.0)
        if 0.0 <= age <= _POULS_DOCKER_MAX_AGE_S:
            return bool((d.get("stats") or {}).get("daemon_up"))
    except Exception:  # noqa: BLE001 - pouls absent/illisible : repli CLI, dit en debug
        logging.getLogger(__name__).debug("pouls Docker illisible, repli CLI", exc_info=True)
    try:
        from nokido_agent.app.forge_docker_agent import daemon_up
        return bool(daemon_up())
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).debug("daemon Docker illisible", exc_info=True)
        return False


def _docker_deja_leve_pour_veille() -> bool:
    """True SSI le demon Docker est deja leve ET une chaine de veille le reclame (docker.claims.json).

    Les DEUX conditions sont necessaires : un daemon leve sans reclamation de veille ne prouve pas que la
    dependance est payee POUR elle ; une reclamation sans daemon leve signifie que la veille paiera le
    demarrage. Tout illisible ou echec -> False : on n'abaisse jamais la garde sur une supposition."""
    try:
        claims = json.loads(_FICHIER_CLAIMS_DOCKER.read_text(encoding="utf-8"))
        if not isinstance(claims, list) or not any(str(c).startswith("wj_") for c in claims):
            return False
    except Exception:  # noqa: BLE001 - absence/illisible = non prouve, jamais "deja paye"
        return False
    return _docker_daemon_up()


def _admission_marginale_autorisee() -> bool:
    """En satiete : admettre UNE veille si sa dependance Docker est deja payee et que la RAM disponible couvre
    son cout marginal declare. Sans dependance levee, le seuil global reste seul juge (garde inchangee)."""
    if not _docker_deja_leve_pour_veille():
        return False
    dispo = _ram_disponible_go()
    return dispo is not None and dispo >= _COUT_MARGINAL_VEILLE_GO


def _age_s(created_at) -> float | None:
    """Age en secondes d'un horodatage SQLite UTC. None = ILLISIBLE, jamais 0.

    `created_at` est ecrit par `datetime('now','utc')` : on compare donc a un
    maintenant UTC, jamais a une heure locale (piege deja paye ailleurs dans le
    depot). Et un horodatage qu'on ne sait pas lire ne rend pas un age de zero,
    qui ferait passer une chaine ancienne pour toute fraiche.
    """
    if not created_at:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            t = datetime.strptime(str(created_at)[:19], fmt).replace(tzinfo=timezone.utc)
            return (datetime.now(tz=timezone.utc) - t).total_seconds()
        except ValueError:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_chain_executor.py', 73, exc_info=True)
            continue
    return None


class ChainExecutor:
    def __init__(self, db_path: Path = DB):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_chain_nodes (
            id TEXT PRIMARY KEY, chain_id TEXT NOT NULL, step_index INTEGER, step_name TEXT,
            agent_role TEXT, llm_preferred TEXT, llm_fallback TEXT, input_from TEXT,
            output_key TEXT, status TEXT DEFAULT 'pending', retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3, result_json TEXT, error TEXT,
            started_at TEXT, done_at TEXT, created_at TEXT DEFAULT (datetime('now', 'utc'))
        );
        CREATE TABLE IF NOT EXISTS agent_chain_context (
            chain_id TEXT PRIMARY KEY, global_vars TEXT, updated_at TEXT DEFAULT (datetime('now', 'utc'))
        );
        """)
        # Identite du processus qui a pris le noeud (15/10) : sans elle, la reprise ne voit que l'AGE et relance en
        # double un noeud lent mais vivant (forge_durable.recover_chain_nodes). ADD COLUMN = metadonnee, O(1).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_chain_nodes)").fetchall()}
        for col, typ in (("runner_pid", "INTEGER"), ("runner_cree", "REAL")):
            if col not in cols:
                conn.execute("ALTER TABLE agent_chain_nodes ADD COLUMN %s %s" % (col, typ))
        conn.commit()
        conn.close()

    def get_context(self, chain_id: str):
        conn = self._get_conn()
        row = conn.execute("SELECT global_vars FROM agent_chain_context WHERE chain_id=?", (chain_id,)).fetchone()
        conn.close()
        return json.loads(row["global_vars"]) if row and row["global_vars"] else {}

    def update_context(self, chain_id: str, updates: Dict[str, Any]):
        ctx = self.get_context(chain_id)
        ctx.update(updates)
        now = datetime.now(tz=timezone.utc).isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO agent_chain_context (chain_id, global_vars, updated_at) VALUES (?, ?, ?)",
            (chain_id, json.dumps(ctx, ensure_ascii=False), now),
        )
        conn.commit()
        conn.close()

    def _etaler_veilles(self, by_chain: dict) -> dict:
        """Au plus LAFORGE_VEILLES_MAX chaines de veille (wj_) en cours (defaut 2 ; owner 27/10 : « la suite du
        workflow d'ingestion ne doit pas empecher le restant d'avancer » -- une seule a la fois retardait tout).
        Aucune ne part en satiete RAM. Les autres restent 'pending' (jamais echouees). Le MOTIF d'attente est
        journalise en WARNING, une fois par motif : en INFO il etait invisible et le worker paraissait mort."""
        veilles = [c for c in by_chain if str(c).startswith("wj_")]
        if not veilles:
            return by_chain
        log = logging.getLogger(__name__)
        attente = set(veilles)
        try:
            maxi = max(1, int(os.environ.get("LAFORGE_VEILLES_MAX", "2")))
        except ValueError:
            maxi = 2
        try:
            conn = self._get_conn()
            try:
                en_cours = conn.execute(
                    "SELECT DISTINCT chain_id FROM agent_chain_nodes "
                    "WHERE status='running' AND chain_id LIKE 'wj\\_%' ESCAPE '\\'"
                ).fetchall()
            finally:
                conn.close()
            places = maxi - len(en_cours)
            # ORDRE D'ARRIVEE (27/10) : trier par identifiant faisait passer les veilles creees en dernier.
            # PRIORITE (owner 29/10 : « en priorite les veilles sur l'auto-regulation ») : les chaines nommees dans
            # _FICHIER_VEILLES_PRIORITAIRES passent devant, relu a chaque passe (aucun redemarrage) ; fichier absent
            # ou illisible = ordre d'arrivee seul.
            prio = _veilles_prioritaires()

            def _arrivee(c):
                noeuds = by_chain.get(c) or [{}]
                return (0 if c in prio else 1, str((noeuds[0] or {}).get("created_at") or ""), str(c))

            if _ram_en_satiete():
                # COUT MARGINAL (owner 29/10) : en satiete, une veille dont la dependance Docker est deja levee
                # et reclamee ne doit pas payer un demarrage deja paye. Une SEULE est admise par passe ; sans
                # dependance levee, rien ne change (elle paierait le demarrage -> le seuil global seul juge).
                if places > 0 and _admission_marginale_autorisee():
                    attente.discard(sorted(veilles, key=_arrivee)[0])
                    _motif_veilles(log, "admission marginale : dependance deja payee (RAM disponible >= %.1f Go) "
                                        ": 1 veille admise" % _COUT_MARGINAL_VEILLE_GO)
                else:
                    _motif_veilles(log, "RAM en satiete : %d veille(s) attendent (seuil du superviseur)"
                                   % len(veilles))
            elif places <= 0:
                _motif_veilles(log, "%d veille(s) deja en cours (max %d) : %d attendent"
                               % (len(en_cours), maxi, len(veilles)))
            else:
                for c in sorted(veilles, key=_arrivee)[:places]:
                    attente.discard(c)
                _DERNIER_MOTIF_VEILLES.clear()
        except Exception:  # noqa: BLE001
            log.warning("[chain] etalement des veilles en echec : veilles laissees en attente",
                        exc_info=True)
        return {c: n for c, n in by_chain.items() if c not in attente}

    async def execute_pending(self, max_parallel: int = 6):
        """Process pending chains EN PARALLELE (jusqu'a max_parallel chains
        concurrentes). Steps DANS une chain restent sequentiels (deps).
        max_parallel=6 = compromis Groq 30 req/min + Cerebras 50k tok/min."""
        # Crash-resume (forge_durable) : re-queue les nodes laisses 'running' par
        # un crash (sinon execute_pending ne les reprend jamais -> chaine figee).
        try:
            from nokido_agent.app.forge_durable import recover_chain_nodes
            recover_chain_nodes(self._get_conn)
        except Exception:  # noqa: BLE001
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_chain_executor.py', 140, exc_info=True)
        conn = self._get_conn()
        nodes = conn.execute(
            "SELECT * FROM agent_chain_nodes WHERE status IN ('pending','retry_pending') ORDER BY chain_id, step_index"
        ).fetchall()
        conn.close()
        # Group by chain_id
        by_chain: dict = {}
        for n in nodes:
            by_chain.setdefault(n["chain_id"], []).append(dict(n))
        if not by_chain:
            return
        by_chain = self._etaler_veilles(by_chain)
        if not by_chain:
            return
        sem = asyncio.Semaphore(max_parallel)

        async def _process_chain(chain_nodes: list):
            async with sem:
                # DEADLINE GLOBALE de la chaine. `stalled` est un etat TERMINAL et
                # DISTINCT de `failed` : il dit « le budget est epuise », pas « le
                # travail est mauvais ». Sans lui, une chaine dont une dependance
                # ne revient jamais reste `retry_pending` pour toujours et personne
                # ne peut la distinguer d'une chaine qui avance.
                age = self._age_chaine(chain_nodes)
                if age is not None and age > _BUDGET_CHAINE_S:
                    self._marquer_stalled(chain_nodes, age)
                    return
                for node in chain_nodes:
                    if node["step_index"] > 0:
                        conn = self._get_conn()
                        prev = conn.execute(
                            "SELECT status FROM agent_chain_nodes WHERE chain_id=? AND step_index=?",
                            (node["chain_id"], node["step_index"] - 1),
                        ).fetchone()
                        conn.close()
                        # Accept completed/partial_success/degraded as ready-to-proceed
                        # (degraded = empty result mais step termine)
                        if not prev or prev["status"] not in ("completed", "partial_success", "degraded"):
                            return
                    await self.run_node(node)

        await asyncio.gather(*[_process_chain(c) for c in by_chain.values()])

    def _age_chaine(self, chain_nodes: list):
        """Age du budget de chaine, compte depuis le PREMIER DEPART d'une etape (MIN started_at), pas depuis la
        creation. Mesure 27/10 : 4 veilles retenues 30 min par la satiete RAM (`_etaler_veilles`, attente VOULUE)
        ont ete soldees `stalled` des leur sortie d'attente, 7 etapes sur 7 jamais jouees. Une chaine jamais
        lancee n'a pas de budget qui court (None). Base illisible : repli sur la creation (ancien comportement)."""
        cid = (chain_nodes[0] or {}).get("chain_id")
        try:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT MIN(started_at) FROM agent_chain_nodes WHERE chain_id=?",
                                   (cid,)).fetchone()
            finally:
                conn.close()
            return _age_s(row[0]) if row and row[0] else None
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("[chain] depart de %s illisible : budget compte depuis la creation",
                                                cid, exc_info=True)
            return _age_s(chain_nodes[0].get("created_at"))

    def _marquer_stalled(self, chain_nodes: list, age_s: float) -> None:
        """Solde les nodes restants d'une chaine qui a epuise son budget.

        On NOMME le motif dans `error` : un statut sans raison envoie la prochaine
        session chercher un bug la ou il n'y a qu'un budget depasse.
        """
        # UN PALIER DE DUREE NE SOLDE PAS CE QUI TOURNE NI CE QUI EST FAIT.
        # Directive owner 2026-09-07 : « pas de palier de duree si pas fini ».
        #
        # CE QUI A ETE PAYE. Cette fonction marquait TOUS les noeuds. Mesure sur la
        # veille `wj_fc7e31285b` : l'etape `ingest` demarre a 16:05:28, se termine a
        # 16:34:19 et rend 369 chunks -- pendant ce travail le budget expire, le motif
        # est ecrit sur les 7 noeuds, puis l'etape finit et ecrit `completed` en
        # gardant l'`error`. Resultat : une chaine INTEGRALEMENT terminee portait
        # « les etapes restantes n'ont pas ete jouees ». Le marquage n'avait rien
        # arrete -- il avait seulement menti, et cela m'a fait annoncer a l'owner une
        # ingestion partielle qui n'existait pas.
        #
        # Le budget reste une borne d'ORDONNANCEMENT : `_process_chain` renonce a
        # lancer une etape de plus, ce qui est son role. Ce qui suit ne touche donc
        # QUE ce qui attendait son tour.
        #
        # LISTE BLANCHE, jamais noire : on solde ce qui est EXPLICITEMENT en attente.
        # Une valeur inattendue reste intacte -- l'inverse ferait tomber tout etat
        # inconnu du cote « perdu », exactement ce que la constitution interdit.
        # ⚠️ `execute_pending` ne charge QUE `pending`/`retry_pending` : en pratique
        # tous les noeuds recus attendent deja. Ce filtre est une defense en
        # PROFONDEUR pour le jour ou un appelant passerait autre chose -- il ne
        # corrige pas a lui seul le defaut mesure (cf. l'effacement de `error` au
        # succes, dans `run_node`). Un statut ABSENT vaut « en attente », parce que
        # c'est ce que l'appelant reel fournit ; l'inverse desarmerait le solde.
        _EN_ATTENTE = {"pending", "retry_pending", "queued"}
        a_solder = [n for n in chain_nodes
                    if n.get("status") is None
                    or str(n.get("status") or "").lower() in _EN_ATTENTE]

        if not a_solder:
            # Rien n'attendait : la chaine a fini dans les temps ou finit encore.
            # Ne rien ecrire -- ni sur les noeuds, ni sur le verdict metier du job.
            print("[EXE] chaine %s : budget depasse (%.0f s) mais AUCUNE etape en "
                  "attente -- rien a solder, rien n'est modifie"
                  % (chain_nodes[0].get("chain_id"), age_s))
            return

        # Le motif porte son DENOMINATEUR : « 2 etapes sur 7 » ne se lit pas comme
        # « les etapes restantes », qui suggere une perte totale meme quand il n'en
        # reste aucune.
        motif = ("budget de chaine epuise : %.0f s > %.0f s -- %d etape(s) sur %d "
                 "n'ont pas ete jouees (les etapes terminees ou en cours sont "
                 "intactes)" % (age_s, _BUDGET_CHAINE_S, len(a_solder), len(chain_nodes)))
        conn = self._get_conn()
        for n in a_solder:
            conn.execute(
                "UPDATE agent_chain_nodes SET status='stalled', error=? WHERE id=?",
                (motif, n["id"]))
        conn.commit()
        # Une chaine soldee doit AUSSI clore son JOB. Sans cela le verdict metier
        # reste celui de la derniere etape ecrite : une veille morte en route se
        # lit « en cours » pour toujours, et un restart la ferait passer pour un
        # succes sans qu'aucune preuve nouvelle ne soit produite.
        chain_id = chain_nodes[0]["chain_id"]
        try:
            from nokido_agent.app.forge_watch_agent import verdict_chaine  # noqa: PLC0415
            etapes = [(r[0], r[1]) for r in conn.execute(
                "SELECT step_name, status FROM agent_chain_nodes WHERE chain_id=?",
                (chain_id,)).fetchall()]
            row = conn.execute("SELECT n_stored FROM watch_jobs WHERE id=?",
                               (chain_id,)).fetchone()
            n_sto = int(row[0]) if row and row[0] is not None else 0
            conn.execute(
                "UPDATE watch_jobs SET step='done', status=?, error=?, updated_at=? "
                "WHERE id=?",
                (verdict_chaine(etapes, n_sto), motif,
                 datetime.now(tz=timezone.utc).isoformat(), chain_id))
            conn.commit()
        except Exception as exc:  # noqa: BLE001
            print("[EXE] cloture du job %s impossible (%s) : le node est solde, "
                  "le verdict metier ne l'est PAS" % (chain_id, type(exc).__name__))
        conn.close()
        print("[EXE] chaine %s STALLED apres %.0f s : %d node(s) non joues sur %d"
              % (chain_nodes[0].get("chain_id"), age_s, len(a_solder), len(chain_nodes)))

    async def run_node(self, node: Dict[str, Any]):
        node_id, chain_id, role = node["id"], node["chain_id"], node["agent_role"]
        print(f"[EXE] Running {node_id} ({role})")
        try:
            from nokido_agent.app.forge_durable import identite_processus
            pid, cree = identite_processus()
        except Exception:  # noqa: BLE001  # muet-ok : sans identite, la reprise retombe sur l'age (dit dans forge_durable)
            pid, cree = os.getpid(), None
        conn = self._get_conn()
        conn.execute(
            "UPDATE agent_chain_nodes SET status='running', started_at=?, runner_pid=?, runner_cree=? WHERE id=?",
            (datetime.now(tz=timezone.utc).isoformat(), pid, cree, node_id),
        )
        conn.commit()
        conn.close()
        try:
            context = self.get_context(chain_id)
            result = await self.dispatch_agent(node, context)
            print(f"[EXE] Result obtained for {node_id}")
            if node["output_key"]:
                print(f"[EXE] Updating context for {chain_id}")
                self.update_context(chain_id, {node["output_key"]: result})
            # State machine granulaire :
            #   completed     : resultat OK substantiel
            #   partial_success : resultat non vide mais reduit (refine 1-2 items, search peu de results)
            #   degraded      : resultat vide mais step pas en erreur (search 0, refine 0)
            final_status = "completed"
            if isinstance(result, list):
                if len(result) == 0:
                    final_status = "degraded"
                elif len(result) < 3 and role in ("RefineAgent", "SearchAgent"):
                    final_status = "partial_success"
            elif isinstance(result, int) and result == 0 and role in ("IngestAgent", "StoreAgent"):
                final_status = "degraded"
            print(f"[EXE] Marking {node_id} as {final_status}")
            conn = self._get_conn()
            conn.execute(
                # `error=NULL` : UN SUCCES EFFACE LA TRACE DE L'ECHEC PRECEDENT.
                # Mesure 2026-09-07 -- la veille `wj_fc7e31285b` portait sur son
                # etape `ingest` : `status=completed` ET `error="budget de chaine
                # epuise -- les etapes restantes n'ont pas ete jouees"`. Le noeud
                # avait ete solde alors qu'il attendait, puis REPRIS et ABOUTI
                # (369 chunks, 16:05 -> 16:34) -- mais l'ecriture du succes ne
                # touchait pas `error`. Deux affirmations contradictoires sur la
                # meme ligne, et c'est la fausse qui se lit : j'ai annonce a l'owner
                # une ingestion partielle qui n'existait pas.
                "UPDATE agent_chain_nodes SET status=?, result_json=?, done_at=?, "
                "error=NULL WHERE id=?",
                (
                    final_status,
                    json.dumps(result, ensure_ascii=False),
                    datetime.now(tz=timezone.utc).isoformat(),
                    node_id,
                ),
            )
            conn.commit()
            conn.close()
            print(f"[EXE] {node_id} done.")
            if role == "SearchAgent" and isinstance(result, list) and not result:
                self._arreter_chaine(chain_id, getattr(result, "motif", None) or MOTIF_SEARXNG_MUET)
            elif role == "SearchAgent" and isinstance(result, list) and getattr(result, "motif", None):
                # Liste NON vide mais degradee (repli academique seul) : la chaine continue, le job le DIT.
                self._noter_degradation(chain_id, result.motif)
            self._clore_job_si_chaine_terminee(chain_id)
        except Exception as e:
            print(f"[EXE] Failed {node_id}: {e}")
            conn = self._get_conn()
            # Retry policy : si retry_count < max_retries, mark retry_pending (re-pickup next iter)
            row = conn.execute(
                "SELECT retry_count, max_retries FROM agent_chain_nodes WHERE id=?", (node_id,)
            ).fetchone()
            rc = (row["retry_count"] if row else 0) + 1
            maxr = row["max_retries"] if row else 3
            if rc < maxr:
                conn.execute(
                    "UPDATE agent_chain_nodes SET status='retry_pending', retry_count=?, error=? WHERE id=?",
                    (rc, str(e), node_id),
                )
            else:
                conn.execute("UPDATE agent_chain_nodes SET status='failed', error=? WHERE id=?", (str(e), node_id))
            conn.commit()
            conn.close()
            if rc >= maxr and role == "SearchAgent":
                # Transport en panne : rien en aval ne doit fabriquer du contenu.
                self._arreter_chaine(chain_id, MOTIF_SEARXNG_MUET + " : " + str(e)[:160])
            self._clore_job_si_chaine_terminee(chain_id)

    def _noter_degradation(self, chain_id: str, motif: str) -> None:
        """Recherche DEGRADEE (28/10) : des resultats existent, mais sans recherche web (SearXNG muet).
        Le motif rejoint watch_jobs.error a la cloture : un `completed_empty` qui suit ne se lit plus
        « le sujet n'existe pas » quand seule la recherche web n'a pas repondu."""
        self._motifs_arret = getattr(self, "_motifs_arret", {})
        self._motifs_arret[chain_id] = "recherche degradee : %s (repli sans recherche web)" % motif

    def _arreter_chaine(self, chain_id: str, motif: str) -> None:
        """ZERO RESULTAT = VIDE ASSUME : les etapes en aval de search (refine, crawl, ingest, store) ne sont
        JAMAIS jouees -- `skipped`, motif nomme. Aucun chunk sans URL reellement recuperee."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE agent_chain_nodes SET status='skipped', error=? "
                "WHERE chain_id=? AND status IN ('pending','retry_pending','queued')",
                ("non jouee : " + motif, chain_id))
            conn.commit()
            self._motifs_arret = getattr(self, "_motifs_arret", {})
            self._motifs_arret[chain_id] = motif
        finally:
            conn.close()

    def _clore_job_si_chaine_terminee(self, chain_id: str) -> Optional[str]:
        """Recalcule le verdict METIER du job quand sa chaine n'a plus d'etape en attente ni en cours.

        Mesure du 15/10 (lecture de %NOKIDO_DATA%\\embeddings.db) : la veille `wj_fc7e31285b` a ses 7 etapes `completed`,
        mais son job reste `running` depuis le 07/09 -- la ligne a ete ecrite a 16:34:17, deux secondes AVANT la
        fin de l'ingest (369 chunks). `run_node` ne touchait jamais `watch_jobs` : seuls `store` et le solde du
        budget y ecrivent, donc une etape qui finit APRES eux laisse le job fige pour toujours.
        Liste BLANCHE des etats d'attente : la moindre etape non terminale et rien n'est ecrit. Une chaine sans
        job de veille n'est pas touchee. Un succes efface la trace d'echec du job, comme `run_node` le fait pour
        le noeud. Rend le verdict ecrit, ou None."""
        _ATTENTE = {"pending", "retry_pending", "running", "queued"}
        conn = self._get_conn()
        try:
            etapes = [(r[0], r[1]) for r in conn.execute(
                "SELECT step_name, status FROM agent_chain_nodes WHERE chain_id=?", (chain_id,)).fetchall()]
            if not etapes or any(str(st or "").lower() in _ATTENTE for _, st in etapes):
                return None
            row = conn.execute("SELECT n_stored, status FROM watch_jobs WHERE id=?", (chain_id,)).fetchone()
            if row is None:
                return None
            from nokido_agent.app.forge_watch_agent import verdict_chaine  # noqa: PLC0415
            # `completed_dedup` (la base possedait deja tout) n'est connu que de l'etape qui l'a ecrit : le garder,
            # sinon le recalcul le degraderait en `completed_empty`.
            verdict = verdict_chaine(etapes, int(row[0] or 0), dedup=(row[1] == "completed_dedup"))
            if verdict.startswith("completed") and verdict != "completed_partial":
                conn.execute("UPDATE watch_jobs SET step='done', status=?, error=NULL, updated_at=? WHERE id=?",
                             (verdict, datetime.now(tz=timezone.utc).isoformat(), chain_id))
            else:
                conn.execute("UPDATE watch_jobs SET step='done', status=?, updated_at=? WHERE id=?",
                             (verdict, datetime.now(tz=timezone.utc).isoformat(), chain_id))
            motif = getattr(self, "_motifs_arret", {}).get(chain_id)
            if motif:
                conn.execute("UPDATE watch_jobs SET error=? WHERE id=?", (motif, chain_id))
            conn.commit()
            print("[EXE] chaine %s terminee -- verdict du job : %s" % (chain_id, verdict))
            if verdict not in ("en_cours", "indetermine"):
                # FIN = SIGNAL : verdict TERMINAL -> la chaine relache SA reclamation Docker.
                from nokido_agent.app.forge_watch_agent import _relacher_docker  # noqa: PLC0415
                _relacher_docker(chain_id)
            return verdict
        except Exception as exc:  # noqa: BLE001
            print("[EXE] cloture du job %s impossible (%s) : le noeud est ecrit, le verdict "
                  "metier ne l'est PAS" % (chain_id, type(exc).__name__))
            return None
        finally:
            conn.close()

    async def dispatch_agent(self, node, context):
        role = node["agent_role"]
        if role == "KeywordAgent":
            return await self._call_llm_step(node, "keywords", context)
        if role == "VerifyAgent":
            return await self._call_llm_step(node, "verify_kw", context)
        if role == "SearchAgent":
            return await self._call_search(context, node["chain_id"])
        if role == "RefineAgent":
            return await self._call_llm_step(node, "refine", context)
        if role == "CrawlAgent":
            return await self._call_crawl(node, context)
        if role == "IngestAgent":
            return await self._call_ingest(node, context)
        if role == "StoreAgent":
            return await self._call_store(node, context)
        raise ValueError(f"Unknown role: {role}")

    async def _call_llm_step(self, node, step_type, context):
        from nokido_agent.app.forge_watch_agent import _llm_local

        theme = context.get("theme", "No theme")
        if step_type == "keywords":
            prompt = (
                f"Theme: {theme}\n\n"
                "Output EXACTLY 4 search queries, ONE per line. NO preamble, NO numbering, "
                "NO 'Here are' intro. Each query 3-10 words. Direct search terms only.\n\n"
                "Example output:\n"
                "DEAP genetic algorithm tutorial Python\n"
                "NEAT-python neural evolution implementation\n"
                "evolutionary computation neural networks benchmark\n"
                "genetic programming agent learning 2024"
            )
            raw = _llm_local(prompt)
            if raw == "ERR:no_llm":
                raise RuntimeError("LLM unavailable (Ollama+Groq both failed)")
            import re as _re

            blacklist = (
                "here are",
                "based on",
                "below are",
                "following are",
                "these are",
                "i can",
                "i'll",
                "let me",
                "search queries",
                "queries related",
                "queries for",
                "the theme",
            )
            res = []
            for line in raw.splitlines():
                l = line.strip()
                # Strip leading numbering / bullets / dashes
                l = _re.sub(r"^[\s0-9.\-*•:>]+", "", l).strip()
                # Strip trailing colons (intro lines)
                if l.endswith(":"):
                    continue
                if len(l) < 8:
                    continue
                if len(l) > 200:
                    continue
                low = l.lower()
                if any(b in low for b in blacklist):
                    continue
                # Strip quotes
                l = l.strip('"').strip("'").strip()
                if l and l not in res:
                    res.append(l)
                if len(res) >= 4:
                    break
            if not res:
                raise RuntimeError(f"LLM produced no valid keywords for theme: {theme[:80]}")

            # Self-validate cosine sim theme vs keywords (seuil 0.55)
            try:
                import sys as _sys, math

                _sys.path.insert(0, str(ROOT / "app"))
                from nokido_agent.app.forge_embed_router import embed as _emb

                theme_vec = _emb(theme[:1000])
                if theme_vec:

                    def _cos(a, b):
                        if not a or not b or len(a) != len(b):
                            return 0.0
                        dot = sum(x * y for x, y in zip(a, b))
                        na = math.sqrt(sum(x * x for x in a))
                        nb = math.sqrt(sum(x * x for x in b))
                        return dot / (na * nb) if na * nb else 0.0

                    valid = []
                    for kw in res:
                        kv = _emb(kw)
                        if kv:
                            sim = _cos(theme_vec, kv)
                            if sim >= 0.55:
                                valid.append(kw)
                            else:
                                logger.debug(f"keyword reject sim={sim:.2f}: {kw[:60]}")
                    if valid:
                        return valid
                    # Aucun keyword pertinent -> fallback theme tel quel comme query unique
                    logger.warning("all keywords < 0.55 sim, using theme directly")
                    return [theme[:100]]
            except Exception as e:
                logger.debug(f"cosine validate skipped: {e}")
            return res
        if step_type == "verify_kw":
            kws = context.get("keywords", [])
            raw = _llm_local(f"Theme: {theme}\nKws: {kws}\nKeep top 3. Numbers only.")
            if raw == "ERR:no_llm":
                raise RuntimeError("LLM unavailable (Ollama+Groq both failed)")
            import re

            idxs = [int(x) - 1 for x in re.findall(r"\d+", raw) if 0 <= int(x) - 1 < len(kws)]
            # DEDOUBLONNER (2026-10-13). Le LLM a rendu « 1 1 1 » : trois fois la MEME requete, les requetes precises
            # (Executive/Waitlist, tables de phases, alarme 1202) jetees sans un mot -- la veille Hamilton n'a ingere
            # qu'UNE source. On garde l'ordre choisi, sans doublon, et on complete avec les suivantes ; on le DIT.
            garde = list(dict.fromkeys(idxs))[:3]
            for i in range(len(kws)):
                if len(garde) >= min(3, len(kws)):
                    break
                if i not in garde:
                    garde.append(i)
            if len(garde) != len(idxs[:3]) or len(set(idxs[:3])) < len(idxs[:3]):
                logger.warning("verify_kw : sortie LLM %r corrigee (doublons/manques) -> %r", raw[:80],
                               [kws[i] for i in garde])
            return [kws[i] for i in garde]
        if step_type == "refine":
            results = context.get("search_results", [])
            if not results:
                return []

            # Heuristique relevance OFFLINE 3-axes (mots-cles overlap + freshness
            # + source trust). Calcule TOUJOURS un score offline + LLM si dispo,
            # garde MAX(llm, offline). Skip LLM single-criterion fail.
            import re as _re, datetime as _dt

            TRUSTED_ACADEMIC = (
                "doi.org/",
                "arxiv.org/",
                "openalex.org/",
                "semanticscholar.org/",
                "ncbi.nlm.nih.gov/",
                "pubmed.gov",
                "biorxiv.org/",
                "medrxiv.org/",
                "openreview.net/",
                "papers.nips.cc/",
                "aclanthology.org/",
                "proceedings.mlr.press/",
                "github.com/",
                "researchgate.net/",
                "jmlr.org/",
                "ieee.org/",
                "acm.org/",
            )
            # Trust per-theme adaptive : detect theme profile -> boost relevant sources
            theme_low = theme.lower()
            is_code_theme = any(
                t in theme_low
                for t in (
                    "python",
                    "library",
                    "framework",
                    "implementation",
                    "code",
                    "tutorial",
                    "github",
                    "docker",
                    "wasm",
                    "rust",
                    "deno",
                    "javascript",
                    "api",
                    "sdk",
                    "tool",
                )
            )
            is_academic_theme = any(
                t in theme_low
                for t in (
                    "paper",
                    "theory",
                    "research",
                    "neuro",
                    "cognitive",
                    "model",
                    "algorithm",
                    "hippocampus",
                    "agent",
                    "principle",
                    "ai",
                    "machine learning",
                    "lstm",
                    "transformer",
                    "rag",
                    "embedding",
                )
            )

            # ORDRE SIGNIFICATIF : `_source_trust` fait `return` au PREMIER needle
            # trouve dans l'URL. Les aiguilles SPECIFIQUES doivent donc preceder les
            # generiques, sinon elles ne sont jamais atteintes.
            #
            # Un DOI n'est PAS une preuve de relecture par les pairs : c'est un
            # identifiant que tout editeur qui paie l'enregistrement obtient. Les
            # journaux predateurs en frappent par design -- c'est leur modele
            # d'affaires -- et Zenodo en delivre pour de l'auto-publie non relu. Les
            # veilles du 2026-07-16 ont ingere IJISRT / IJAIDSML / SJCS et des
            # whitepapers Zenodo a +2.5 de confiance : le seul prefixe "doi.org/"
            # leur faisait franchir le seuil de 4.0. La confiance vient de la VENUE
            # (arxiv, openreview, NeurIPS, ACL... listees plus bas), pas du registrar.
            SOURCE_TRUST = {  # max +2 boost
                # -- Registrars et depots ouverts, AVANT le generique "doi.org/" --
                "doi.org/10.5281/": 0.0,  # Zenodo : depot ouvert, auto-publie, non relu
                "zenodo.org/": 0.0,
                "doi.org/10.38124/": -2.0,  # IJISRT   (predateur, observe 2026-07-16)
                "doi.org/10.63282/": -2.0,  # IJAIDSML (predateur, observe 2026-07-16)
                "doi.org/10.64539/": -2.0,  # SJCS     (predateur, observe 2026-07-16)
                "ijisrt.com": -2.0,
                "ijircst.org": -2.0,
                "jisem-journal.com": -2.0,
                # -- Venues reelles --
                "arxiv.org/": 2.0,
                "openalex.org/": 2.0,
                "semanticscholar.org/": 2.0,
                "biorxiv.org/": 2.0,
                "medrxiv.org/": 1.8,
                "openreview.net/": 1.8,
                "papers.nips.cc/": 1.8,
                "github.com/": 1.5,
                "researchgate.net/": 1.5,
                # -- Generique : un DOI seul ne dit rien de la qualite --
                "doi.org/": 0.5,
                "reddit.com/": -1.0,
                "medium.com/": -0.5,
                "linkedin.com/": -0.5,
                "google.com/": -2.0,
                "youtube.com/": -1.0,
            }
            # Boost per theme profile
            if is_code_theme:
                SOURCE_TRUST["github.com/"] = 2.5  # github prio si code
                SOURCE_TRUST["stackoverflow.com/"] = 1.5
                SOURCE_TRUST["pypi.org/"] = 1.8
                SOURCE_TRUST["readthedocs.io/"] = 1.5
            if is_academic_theme:
                # Pas de boost sur "doi.org/" : le registrar ne dit rien de la
                # qualite. On ne boost que les VENUES.
                SOURCE_TRUST["arxiv.org/"] = 2.5
                SOURCE_TRUST["openalex.org/"] = 2.5
            theme_tokens = set(t.lower() for t in _re.findall(r"\b[A-Za-z][A-Za-z0-9\-]{3,}\b", theme))
            now_year = _dt.datetime.now().year

            def _source_trust(url: str) -> float:
                """Confiance de la source. ORDRE SIGNIFICATIF : premier needle gagne."""
                url = (url or "").lower()
                for needle, w in SOURCE_TRUST.items():
                    if needle in url:
                        return w
                return 0.0

            def _offline_score(r):
                title = (r.get("title") or "").lower()
                content = (r.get("content") or "")[:500].lower()
                full = title + " " + content
                # Axis 1 : overlap mots-cles (3 max points)
                full_tokens = set(_re.findall(r"\b[a-z][a-z0-9\-]{3,}\b", full))
                overlap = len(theme_tokens & full_tokens)
                axis1 = min(3.0, overlap * 0.5)
                # Axis 2 : freshness (1 max point)
                yr_match = _re.search(r"\b(20\d{2})\b", full)
                axis2 = 0.0
                if yr_match:
                    yr = int(yr_match.group(1))
                    if yr <= now_year:
                        age = now_year - yr
                        axis2 = max(0.0, 1.0 - age * 0.1)  # 0 si age >10
                # Axis 3 : source trust (-2 to +2)
                axis3 = _source_trust(r.get("url"))
                # Axis 4 : CIBLE DONNEE dans le theme (2026-10-13). Nommee explicitement par qui lance la veille, elle
                # vaut au moins une venue reconnue (+2, comme arxiv) : sans cet axe, les cinq fichiers du code AGC
                # (raw.githubusercontent.com, confiance 0) ont ete evinces des 5 places par des articles arxiv que le
                # crawl a ensuite rejetes. Le veto de source et le veto d'ancrage s'appliquent toujours.
                axis4 = 2.0 if r.get("engine") == "theme_url" else 0.0
                return axis1 + axis2 + axis3 + axis4  # range ~[-2, 8]

            # Compute offline scores + sort. Les CIBLES DONNEES passent d'abord (2026-10-13) : un bonus de score ne
            # suffisait pas -- sur un theme juge « academique », arxiv vaut +2.5 de confiance plus la fraicheur et
            # repassait devant. Elles restent soumises aux vetos et au seuil ci-dessous, puis a l'affinage du crawl et
            # de l'ingestion.
            scored = [(r, _offline_score(r)) for r in results]
            scored.sort(key=lambda x: (x[0].get("engine") == "theme_url", x[1]), reverse=True)

            # LLM scoring best-effort (NON bloquant)
            llm_scores = {}
            try:
                titles = [f"{i + 1}. {r.get('title', '')[:120]}" for i, r in enumerate(results[:10])]
                short_theme = theme[:500]
                raw = _llm_local(
                    f"Theme: {short_theme}\nTitles:\n" + "\n".join(titles) + "\nRate top 5. Format num:score."
                )
                if raw and raw != "ERR:no_llm":
                    pairs = _re.findall(r"(\d+):(\d+)", raw)
                    for n_s, s_s in pairs[:10]:
                        idx = int(n_s) - 1
                        if 0 <= idx < len(results):
                            llm_scores[idx] = int(s_s)
            except Exception as e:
                logger.debug(f"refine LLM skipped: {e}")

            # Ancres du theme : les termes SANS lesquels un resultat ne peut pas
            # appartenir au sujet. Meme notion qu'a la generation des requetes
            # (forge_watch_agent._anchor_terms) — on ancre en amont ET on verifie
            # en aval, sinon le filtre et la requete parlent de deux choses.
            _anchors: list = []
            try:
                import sys as _sys
                from pathlib import Path as _P

                _app = str(_P(__file__).resolve().parent)
                if _app not in _sys.path:
                    _sys.path.insert(0, _app)
                from nokido_agent.app.forge_watch_agent import _anchor_terms

                _theme = (context or {}).get("theme") or ""
                if _theme:
                    _anchors = [a.lower() for a in _anchor_terms(_theme)][:6]
            except Exception as _e:  # noqa: BLE001
                logger.debug(f"refine: ancres indisponibles ({_e}) -> veto desactive")

            # Combiner offline + LLM, keep top 5 si score >= seuil
            refined = []
            _qualifies: list = []
            for r, off in scored:
                idx = results.index(r)
                # Veto DUR : une source connue predatrice ne se rattrape pas au score.
                # `final = max(off_norm, llm)` ignore par construction le signal de
                # confiance : un journal predateur au titre parfaitement dans le sujet
                # obtient 8/10 du LLM (qui ne voit QUE le titre) et ecrase le -2.0 de
                # la source. Sans veto, l'axe trust n'est jamais opposable.
                if _source_trust(r.get("url")) <= -1.5:
                    logger.info(f"[refine] veto source non fiable: {r.get('url')}")
                    continue
                llm = llm_scores.get(idx, 0)
                # Normalize offline [-2,6] -> [0,10], LLM [0,10] direct
                off_norm = max(0.0, min(10.0, (off + 2) * 1.25))
                final = max(off_norm, llm * 1.0)

                # VETO D'ANCRAGE — `max()` fait gagner le plus OPTIMISTE des deux, or
                # le LLM ne voit que ~80 caracteres de titre : il note la plausibilite
                # d'une phrase, pas son appartenance au sujet. Mesure 2026-07-25 :
                # theme « Viable System Model … homeostasis », resultat « NRF2 controls
                # iron homeostasis and ferroptosis » (cancer ovarien) -> offline 3.8
                # (juste), LLM 7 (faux), final 7 -> ingere. L'offline avait raison et
                # son signal a ete ecrase.
                #
                # Regle : un resultat qui ne contient AUCUN terme du theme, ni dans le
                # titre ni dans le contenu, est hors-sujet quoi qu'en dise le LLM. On
                # PLAFONNE au lieu de jeter (il reste visible, il ne sera juste pas
                # ingere) — et on trace, car un rejet muet est indiagnosticable.
                if _anchors and final >= 4.0:
                    hay = ((r.get("title") or "") + " " + (r.get("content") or "")).lower()
                    _avant = final
                    final = _plafond_ancrage(final, hay, _anchors)
                    if final < _avant:
                        logger.info(
                            f"[refine] hors-sujet (ancres {_anchors[:3]} insuffisantes) "
                            f"off={off_norm:.1f} llm={llm} -> plafonne sous le seuil : "
                            f"{(r.get('title') or '')[:70]}")

                if final >= 4.0:
                    r2 = dict(r)
                    r2["relevance"] = round(final)
                    r2["score_offline"] = round(off_norm, 1)
                    r2["score_llm"] = llm
                    _qualifies.append(r2)

            # BORNE DITE (2026-10-24). Avant : seuls les 8 premiers par score OFFLINE etaient examines et on
            # coupait a 5 dans cet ordre, en silence -- un candidat note 9 par le LLM mais classe 9e hors ligne
            # n'etait jamais lu. On examine tout, on classe sur la note FINALE (tri stable : cibles donnees puis
            # offline en cas d'egalite), on garde 5, le reste est journalise et expose (`refine_ecartes`).
            # 24/10 (bug_veille_candidats_cles_non_ingeres) : la cle de tri etait la SEULE note -- elle ecrasait la
            # priorite des cibles donnees (l.761) et des articles mieux cotes evincaient les fichiers NOMMES par le
            # theme. Cibles d'abord, puis la note. NR test_veille_vue_reparee_nr (refine garde les cibles).
            _qualifies.sort(key=lambda x: (x.get("engine") == "theme_url", x["relevance"]), reverse=True)
            refined = _qualifies[:5]
            _ecartes_borne = _qualifies[5:]
            if _ecartes_borne:
                logger.warning(
                    "[refine] %d candidats >= seuil -> %d retenus ; %d NON ingeres (borne 5) : %s",
                    len(_qualifies), len(refined), len(_ecartes_borne),
                    [(e.get("url"), e["relevance"]) for e in _ecartes_borne][:20])
                try:
                    self.update_context(node["chain_id"], {"refine_ecartes": [
                        {"url": e.get("url"), "title": (e.get("title") or "")[:120],
                         "relevance": e["relevance"]} for e in _ecartes_borne]})
                except Exception as _e:  # noqa: BLE001
                    logger.warning("[refine] ecartes non persistes (%s)", _e)

            # Si rien ne passe seuil 4 -> trust academic minimal
            if not refined:
                for r in results[:5]:
                    url = (r.get("url") or "").lower()
                    if any(t in url for t in TRUSTED_ACADEMIC):
                        r2 = dict(r)
                        r2["relevance"] = 4
                        refined.append(r2)
            return refined

    async def _call_search(self, context, chain_id=None):
        import asyncio

        from nokido_agent.app.forge_watch_agent import _academic_search, _ensure_searxng, _github_search, _searxng

        # Réveil central on-demand de SearXNG (seam superviseur) + attente
        # readiness AVANT les requêtes, sinon la 1re veille dégrade en academic
        # faute de conteneur up. Offloadé en thread (sleeps bloquants).
        searxng_ok = False
        try:
            searxng_ok = bool(await asyncio.to_thread(_ensure_searxng, None, chain_id))
        except Exception as e:
            print(f"[SEARCH] ensure searxng KO (continue): {e}")
        if not searxng_ok:
            # Dégradation BRUYANTE (fin du silence) : SearXNG = moteur PRIMAIRE ; son
            # absence (Docker/conteneur down) bascule sur l'academic OpenAlex/arXiv
            # (sans Docker), couverture réduite. Signal pour RÉPARER SearXNG, pas masquer.
            print(
                "[SEARCH][DEGRADE] SearXNG indisponible (Docker/conteneur down) "
                "-> fallback academic OpenAlex/arXiv. Reparer SearXNG pour couverture complete."
            )

        kws = context.get("keywords_verified", context.get("keywords", []))
        all_res = []
        seen_urls = set()
        # DENOMINATEUR de la recherche. Sans lui, `all_res == []` confond deux
        # situations qui n'ont rien a voir : les sources ont REPONDU et il n'y
        # avait rien, ou AUCUNE n'a pu etre interrogee. Les deux donnaient
        # `degraded`, donc la chaine continuait jusqu'a StoreAgent et le job se
        # lisait « termine » alors que la veille n'avait pas ouvert les yeux.
        # C'est la doctrine de la maison appliquee a son propre organe de veille :
        # une absence de mesure n'est jamais un resultat.
        tentatives = 0
        echecs = 0

        # URLS DONNEES DANS LE THEME (2026-10-13) : des cibles CONNUES, injectees en tete comme candidats ; refine
        # les note et l'affinage decide, rien n'est force. `forge_watch_agent._step_search` le faisait depuis le
        # 2026-07-22 (cas ExploitGym), mais ce chemin-ci -- le SEUL qu'execute la chaine -- ne l'avait jamais recu :
        # deux versions de la meme etape avaient diverge. Le contenu provisoire ne sert qu'a la notation ; si le
        # crawl ne ramene pas la page, `_call_crawl` le vide (jamais ingere a la place de la page).
        import re as _re

        _theme = context.get("theme") or ""
        for _u in _re.findall(r"https?://[^\s\"'\)\]]+", _theme):
            if _cle_url(_u) in seen_urls:
                continue
            seen_urls.add(_cle_url(_u))
            all_res.append({"title": _u[:120], "url": _u,
                            "content": ("cible donnee dans le theme: " + _theme)[:400],
                            "keyword": "theme-url", "engine": "theme_url"})

        def _docs(k, m):
            # DOCS OFFICIELLES en tete pour les sujets-OUTILS : passe SearXNG orientee
            # documentation, prime au dedup avant l'academique -- sinon l'API academique
            # (OpenAlex/arXiv) noyait les docs jj/aider/bazel sous des papiers hors-sujet
            # (mesure 2026-08-28 : jujutsu -> -Execution Envelopes-, aider -> -Vibe Coding-).
            return _searxng(k + " official documentation guide", m)

        def _github(k, m):
            # API injoignable = ECHEC compte (non-mesure), jamais une source qui a repondu « rien ».
            return _github_search(k, m, leve=True)

        for kw in kws:
            # L'academique est une SOURCE A PART ENTIERE, pas un repli. `_searxng`
            # ne bascule sur `_academic_search` que lorsqu'il ECHOUE (CB ouvert, 0
            # hit, exception) : SearXNG debout, la veille ne voyait donc QUE du web
            # generaliste -> moisson de journaux predateurs et snippets de 400 chars
            # (veilles du 2026-07-16). L'API academique rend l'ABSTRACT directement :
            # ni crawl, ni chrome de nav, ni PDF a extraire. Academique en PREMIER :
            # a URL egale, son abstract prime au dedup.
            # GitHub par API (README entier, aucun CAPTCHA) : `_step_search` l'interrogeait, ce chemin jamais.
            for src, n in ((_docs, 4), (_academic_search, 3), (_github, 3), (_searxng, 6)):
                tentatives += 1
                try:
                    hits = src(kw, n)
                except Exception as e:
                    echecs += 1
                    print(f"[SEARCH] {src.__name__} degraded for '{kw}': {e}")
                    continue
                for r in hits:
                    url = r.get("url", "")
                    # Dedup absent jusqu'ici : deux mots-cles proches ramenaient la
                    # meme URL deux fois, et le doublon occupait un des 5 slots de
                    # `refine`.
                    if not url or _cle_url(url) in seen_urls:  # 27/10 : http/https, versions arXiv
                        continue
                    seen_urls.add(_cle_url(url))
                    all_res.append(
                        {
                            "title": r.get("title", ""),
                            "url": url,
                            "content": r.get("content", ""),
                            "keyword": kw,
                            "engine": r.get("engine", "searxng"),
                        }
                    )
        # Observabilité : breakdown sources (academic > 0 = preuve que SearXNG a échoué).
        eng: dict = {}
        for r in all_res:
            tag = ("academic" if r.get("engine") in ("openalex", "arxiv_direct")
                   else r.get("engine") if r.get("engine") in ("github_api", "theme_url") else "searxng")
            eng[tag] = eng.get(tag, 0) + 1
        # Priorite DOMAINE (2026-08-28 v2) : les docs officielles priment sur
        # l'academique pour les sujets-outils -- le refine prend les premiers,
        # on lui donne donc les docs EN TETE (le hint de query seul ne suffisait pas).
        def _score_dom(u):
            u = (u or "").lower()
            if any(k in u for k in ("readthedocs", "/docs/", "docs.", "github.io",
                                    ".dev/", "/manual", "/guide", "/reference")):
                return 2
            if any(k in u for k in ("arxiv.org", "doi.org", "semanticscholar",
                                    "/abs/", "researchgate")):
                return -1
            return 0
        # Les cibles DONNEES restent en tete : refine ne montre au LLM que les 10 premiers titres.
        all_res.sort(key=lambda r: -(3 if r.get("engine") == "theme_url" else _score_dom(r.get("url", ""))))
        print(f"[SEARCH] n={len(all_res)} searxng_ensured={searxng_ok} sources={eng} "
              f"tentatives={tentatives} echecs={echecs}")
        # TROIS etats, jamais deux. Aucun resultat ET aucune source joignable n'est
        # pas un resultat vide : c'est une NON-MESURE. On leve, ce qui remet le node
        # en `retry_pending` puis `failed` par la politique de retry deja en place --
        # plutot que d'inventer un statut de plus. Un vide LEGITIME (au moins une
        # source a repondu) reste `degraded` et la chaine continue, ce qui est le
        # comportement voulu : SearXNG a terre, l'academique OpenAlex/arXiv travaille
        # encore, et bloquer la veille la priverait de la couverture qui lui reste.
        if not all_res and tentatives and echecs == tentatives:
            raise RuntimeError(
                "recherche NON MESUREE : %d/%d interrogations de sources ont echoue, "
                "aucune n'a repondu -- 0 resultat ne dit rien du sujet, seulement que "
                "la veille n'a pas pu regarder" % (echecs, tentatives))
        sortie = _Resultats(all_res)
        if not all_res:
            # VIDE ASSUME, jamais comble : motif nomme, la chaine s'arretera (run_node).
            sortie.motif = MOTIF_MOTEURS_BLOQUES if searxng_ok else MOTIF_SEARXNG_MUET
        elif not searxng_ok:
            # Resultats academiques seuls, SearXNG muet : etat DEGRADE, lu par run_node (_noter_degradation).
            sortie.motif = MOTIF_SEARXNG_MUET
        return sortie  # vide APRES reponse d'au moins une source = vide assume

    async def _call_crawl(self, node, context):
        from nokido_agent.app.forge_crawl_tool import crawl_url_detail
        from nokido_agent.app.forge_watch_agent import _is_binary_payload, _is_boilerplate

        refined = context.get("refined", [])
        loop = asyncio.get_running_loop()
        # REPRISE PAR URL. Le resultat du node n'etait persiste qu'a la FIN de la
        # boucle : un crash a la 6e URL sur 8 faisait TOUT recrawler au redemarrage.
        # Face a un crawler intermittent, c'est le pire niveau de reprise possible --
        # celui qui refait le travail deja reussi. On solde donc CHAQUE url dans le
        # contexte de chaine, et on saute celles qui portent deja un verdict.
        deja = dict(context.get("crawl_fait") or {})
        _CHAMPS = ("content", "crawled", "crawl_backend", "crawl_quality",
                   "crawl_variante")
        t0 = time.time()

        def _solder(cle: str, res: dict) -> None:
            deja[cle] = {k: res[k] for k in _CHAMPS if k in res}
            self.update_context(node["chain_id"], {"crawl_fait": deja})

        for r in refined:
            url = r.get("url")
            if url in deja:
                r.update(deja[url])
                continue
            # BUDGET de la boucle. Vingt URL lentes, plus les attentes imposees par
            # les retry HTTP 429, pouvaient l'etirer sans limite. On s'arrete, et on
            # le DIT sur chaque resultat non traite : un crawl qu'on n'a pas fait
            # n'est pas un crawl sans resultat.
            if time.time() - t0 > _BUDGET_CRAWL_S:
                r["crawl_quality"] = "budget_epuise"
                _solder(url, r)
                continue
            try:
                det = await loop.run_in_executor(None, _crawl_complet, url, crawl_url_detail, 15)
            except Exception as e:
                logger.debug(f"[chain] crawl KO {url}: {e}")
                r["crawl_backend"], r["crawl_quality"] = "aucun", "erreur"
                _solder(url, r)
                continue
            md = det["text"]
            # LA PROFONDEUR EST UN ETAT MESURE, PAS UN BOOLEEN. `crawled = True`
            # disait seulement qu'un texte etait arrive -- jamais par quel chemin.
            # Un repli urllib sur une page JavaScript rend son chrome et se lisait
            # comme un crawl profond reussi. On inscrit donc le backend REEL et la
            # qualite a cote du contenu : la veille peut enfin dire ce qu'elle a vu.
            r["crawl_backend"] = det["backend"]
            r["crawl_quality"] = det["qualite"]
            r["crawl_variante"] = det.get("variante")
            # Le crawl n'ECRASE le contenu deja en place que s'il fait MIEUX.
            # Avant, tout md >500 chars gagnait : un abstract academique propre
            # se faisait remplacer par le menu de nav de la page (GitHub/PKP) ou
            # par les octets d'un PDF. Le champ `content` d'origine (abstract
            # OpenAlex/arxiv ou snippet SearXNG) est une meilleure repli.
            if not md or len(md) <= 500:
                r["crawl_quality"] = "trop_court"
                _solder(url, r)
                continue
            if md.startswith("ERR:") or _is_binary_payload(md) or _is_boilerplate(md):
                logger.debug(f"[chain] crawl rejete (chrome/binaire) {url}")
                # REJETE n'est pas DEGRADED : le filtre a fait son travail et le
                # snippet d'origine est conserve. Le distinguer evite de lire un
                # garde qui protege comme une panne du crawler.
                r["crawl_quality"] = "rejete"
                _solder(url, r)
                continue
            r["content"], r["crawled"] = md, True
            _solder(url, r)
        # Une cible DONNEE dans le theme que le crawl n'a pas ramenee n'a pour contenu que le texte provisoire
        # de notation : on le VIDE, l'ingestion la rejette alors comme « sans corps » au lieu d'ingerer le theme
        # a la place de la page (2026-10-13).
        for r in refined:
            if r.get("engine") == "theme_url" and not r.get("crawled"):
                r["content"] = ""
        # Profondeur AGREGEE du node : sans elle, il faudrait relire chaque
        # resultat pour savoir si la veille a vraiment ouvert les yeux.
        profil: dict = {}
        for r in refined:
            cle = "%s/%s" % (r.get("crawl_backend") or "?", r.get("crawl_quality") or "?")
            profil[cle] = profil.get(cle, 0) + 1
        profond = sum(1 for r in refined
                      if r.get("crawled") and r.get("crawl_quality") == "full")
        print("[CRAWL] profondeur reelle %d/%d (navigateur ou PDF) — detail %s"
              % (profond, len(refined), profil))
        return refined

    async def _call_ingest(self, node, context):
        from nokido_agent.app.forge_watch_agent import _step_ingest, _audit_chunks_quality, _get_conn

        conn = _get_conn()
        theme = context.get("theme")
        n = _step_ingest(conn, node["chain_id"], theme, context.get("crawled_results", context.get("refined", [])))
        # Audit post-ingest : drop chunks low quality (cosine theme + trust source)
        try:
            audit = _audit_chunks_quality(conn, theme, threshold=0.55)
            if audit.get("dropped", 0) > 0:
                print(
                    f"[AUDIT] {theme[:40]}: dropped={audit['dropped']}/{audit['checked']} kept={audit['kept']} avg={audit.get('avg_quality')}"
                )
        except Exception as e:
            print(f"[AUDIT] skipped: {e}")
        conn.close()
        return n

    async def _call_store(self, node, context):
        from nokido_agent.app.forge_watch_agent import _step_store, _get_conn

        conn = _get_conn()
        n = _step_store(
            conn,
            node["chain_id"],
            context.get("theme"),
            context.get("crawled_results", context.get("refined", [])),
            context.get("idea_id", "v"),
        )
        conn.close()
        return n

    async def start_loop(self):
        print("Loop started.")
        sandbox = ROOT / "sandbox"
        hb = sandbox / "chain_executor.heartbeat"
        sandbox.mkdir(exist_ok=True)

        async def _hb_ticker():
            # Heartbeat CONCURRENT (20s) : prouve que l'event loop vit même pendant
            # une chain longue (crawl + LLM). Le superviseur restart si le fichier
            # se fige (services.toml: heartbeat=sandbox/chain_executor.heartbeat).
            # Incident 2026-06-03 : ChainExecutor mort -> chains stuck pending sans alerte.
            while True:
                try:
                    by_status: dict = {}
                    try:
                        conn = self._get_conn()
                        rows = conn.execute(
                            "SELECT status, COUNT(*) FROM agent_chain_nodes GROUP BY status"
                        ).fetchall()
                        by_status = {r[0]: r[1] for r in rows}
                        conn.close()
                    except Exception:
                        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_chain_executor.py', 1047, exc_info=True)
                    hb.write_text(
                        json.dumps(
                            {
                                "ts": datetime.now(tz=timezone.utc).isoformat(),
                                "pid": os.getpid(),
                                "by_status": by_status,
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                except Exception:
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_chain_executor.py', 1060, exc_info=True)
                await asyncio.sleep(20)

        asyncio.ensure_future(_hb_ticker())
        while True:
            try:
                await self.execute_pending()
            except Exception as e:
                # Une itération KO ne tue pas le daemon (sinon chains stuck pending).
                print(f"[LOOP] execute_pending KO (continue): {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    executor = ChainExecutor()
    asyncio.run(executor.start_loop())
