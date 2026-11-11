"""
forge_sovereign_membrane.py — Nokido Engrid v3
================================================
La Membrane Souveraine : couche bidirectionnelle entre le monde interne
(Ryzen — données réelles) et le monde externe (Cloud — données anonymisées).

Tout signal qui traverse la frontière passe par ici, dans les deux sens.

Architecture :
    INTÉRIEUR (réel)  →  wrap()    →  EXTÉRIEUR (alias + bruit metadata)
    EXTÉRIEUR (alias) →  unwrap()  →  INTÉRIEUR (données réelles restituées)

Propriétés garanties :
    - Le Cloud ne voit jamais les IPs, MACs, hostnames, chemins réels
    - Les decoys sont metadata uniquement — jamais dans le prompt
    - Les alias sont persistants par mission (SQLite WAL chiffré)
    - Les tool_calls sont résolus avant exécution
    - Audit trail complet sans jamais stocker le contenu sensible

Intégration Engrid :
    MetaCognitionGate → SovereignMembrane → ModelBackend (cloud)
                                          ↑
                                     NoiseGuardian (réutilisé)
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time

# DEAD_IMPORT removed: import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger(__name__)


# ── Lazy import NoiseGuardian (évite import circulaire) ───────────────────────
# --- Sujets prives (choix owner du 6/11 : classer la tache, pas le modele) --------------------------------------------
# Une seule definition du prive : `forge_git_egress.sujets_prives`, qui ne protegeait que la publication. Mesure du 6/11 :
# 86 appels d'agents OpenCode et Vibe touchaient un mot ou un chemin prive en octobre. `caviarder` n'en fait pas partie :
# c'est une liste de documents publics a nettoyer, pas un sujet.
MASQUE_SUJET = "[SUJET_PRIVE]"
# Liste blanche : tout client LLM hors d'ici est expose. Un demon interne n'envoie rien a un modele et reste hors du filtre.
_AGENTS_SANS_FILTRE = frozenset({"CLAUDE", "CLAUDE_HEADLESS", "CLAUDE_API", "ANTIGRAVITY", "AGY", "GEMINI"})
_CLIENTS_OAUTH_SANS_FILTRE = frozenset({"Claude Code (nokido-oauth)", "Google Antigravity"})
_PREFIXES_EXPOSES = ("OPENCODE", "VIBE", "MISTRAL", "CODEX", "CLINE", "COPILOT", "MAMMOUTH", "BRIDGE")
_CACHE_SUJETS: dict = {"cle": None, "valeur": None}
_CACHE_CLIENTS: dict = {"cle": None, "valeur": {}}
_CACHE_IDENTITES: dict = {"cle": None, "valeur": set()}


# Choix owner 6/11 : le cloud ne recoit un texte du RAG que si sa PROVENANCE est publique. Liste blanche : conversations,
# memoires, sessions, documents internes et domaine inconnu ne sortent pas. Un motif ne reconnait pas une conversation privee.
DOMAINES_PUBLICS = frozenset({"sdk_gitingest", "ext_repo", "veille_code", "watch_veille", "claude_docs"})


def preparer_pour_cloud(requete, docs, textes, mission="rerank_cloud"):
    """(requete, textes) sous membrane si TOUS les `docs` sont de provenance publique ; None sinon. Panne : None, rien ne sort."""
    try:
        if not docs or any(str((d or {}).get("domain")) not in DOMAINES_PUBLICS for d in docs):
            return None
        m = SovereignMembrane.for_mission(mission)
        return m.wrap_objet(str(requete or "")), m.wrap_objet(list(textes))
    except Exception as exc:  # noqa: BLE001 - voir la docstring
        logger.warning("[membrane] preparation cloud impossible (%s) : rien n'est envoye", type(exc).__name__)
        return None


def _motifs_secrets() -> list:
    """Cles et mots de passe : la definition de `forge_secret_guard`, sans son heuristique de forme (un sha n'est pas un secret)."""
    from nokido_agent.app.forge_secret_guard import _OUTBOUND_PATTERNS
    return [(p, "SECRET") for p, nom in _OUTBOUND_PATTERNS if not str(nom).startswith("Hex-64")]


def _lire_sujets() -> dict:
    from nokido_agent.app.forge_git_egress import sujets_prives
    return sujets_prives()


def _cle_sujets():
    from nokido_agent.app.forge_git_egress import SUJETS_PRIVES
    try:
        return Path(SUJETS_PRIVES).stat().st_mtime_ns
    except OSError:  # muet-ok : liste absente (distribution publique) : rien a proteger, le lecteur rend du vide
        return 0


def _sujets_compiles() -> dict:
    """{'mots': motifs refuses dans une consigne, 'masques': mots + retirer, 'chemins': globs}. Relu si la liste change."""
    cle = _cle_sujets()
    if _CACHE_SUJETS["valeur"] is not None and _CACHE_SUJETS["cle"] == cle:
        return _CACHE_SUJETS["valeur"]
    brut = _lire_sujets()
    mots = [re.compile(m, re.I) for m in brut.get("mots", [])]
    retirer = [re.compile(m, re.I) for m in brut.get("retirer", [])]
    valeur = {"mots": mots, "masques": mots + retirer, "chemins": [str(g).replace("\\", "/") for g in brut.get("chemins", [])]}
    _CACHE_SUJETS.update(cle=cle, valeur=valeur)
    return valeur


def _nom_client_oauth(client_id: str) -> str | None:
    """Nom inscrit d'un client OAuth (`clients.json`), ou None : un client inconnu reste expose."""
    try:
        from nokido_agent.app.forge_oauth_clients import dossier_defaut
        p = Path(dossier_defaut()) / "clients.json"
        cle = p.stat().st_mtime_ns
        if _CACHE_CLIENTS["cle"] != cle:
            d = json.loads(p.read_text(encoding="utf-8"))
            _CACHE_CLIENTS.update(cle=cle, valeur={str(k).casefold(): str((v or {}).get("client_name") or "") for k, v in d.items()})
        return _CACHE_CLIENTS["valeur"].get(str(client_id).casefold())
    except Exception as exc:  # noqa: BLE001 - None = expose : le filtre se ferme, et on le dit
        logger.warning("[membrane] clients OAuth illisibles (%s) : client traite comme expose", type(exc).__name__)
        return None


def _est_interne(nom: str) -> bool:
    """Vrai si le registre declare cette identite comme interne (service, hook). Absente ou illisible : non, elle reste exposee."""
    try:
        p = Path(__file__).resolve().parent.parent / "config" / "agent_identities.json"
        cle = p.stat().st_mtime_ns
        if _CACHE_IDENTITES["cle"] != cle:
            d = json.loads(p.read_text(encoding="utf-8")).get("agents") or {}
            internes = set()
            for k, v in d.items():
                if isinstance(v, dict) and (str(v.get("kind")) in ("service", "hook", "daemon") or str(v.get("surface")) == "internal"):
                    internes.update(str(x).upper() for x in [k, *(v.get("aliases") or [])])
            _CACHE_IDENTITES.update(cle=cle, valeur=internes)
        return str(nom).upper() in _CACHE_IDENTITES["valeur"]
    except Exception as exc:  # noqa: BLE001 - registre illisible : le filtre se ferme, et on le dit
        logger.warning("[membrane] registre des identites illisible (%s) : identite traitee comme exposee", type(exc).__name__)
        return False


def agent_expose(agent, ring=None) -> bool:
    """Vrai si les sujets prives doivent etre retenus pour cet agent. Mesure du 6/11 : `read` et `rag` s'ouvrent aux rings 3 et 4 ;
    une identite inconnue de ces rings est donc exposee, sauf service declare au registre (liste blanche)."""
    a = str(agent or "").strip()
    if a.casefold().startswith("agt_"):
        a = a[4:]
    if a.casefold().startswith("oauth_"):
        return _nom_client_oauth(a[6:]) not in _CLIENTS_OAUTH_SANS_FILTRE
    a = a.upper()
    if a in _AGENTS_SANS_FILTRE:
        return False
    if a.startswith(_PREFIXES_EXPOSES):
        return True
    return bool(a) and isinstance(ring, int) and ring >= 3 and not _est_interne(a)


def _chemin_prive(valeur, globs) -> bool:
    v = str(valeur or "").replace("\\", "/")
    candidats = {v, v.split("/Nokido/")[-1], v.lstrip("./")}
    return any(fnmatch.fnmatch(c, g) for c in candidats for g in globs)


def fichiers_prives(fichiers) -> list:
    """Ceux de `fichiers` (chemins relatifs au depot) que `sujets_prives` declare prives."""
    globs = _sujets_compiles()["chemins"]
    return [f for f in fichiers if _chemin_prive(f, globs)]


def _caviarder_objet(obj, motifs):
    if isinstance(obj, str):
        for motif in motifs:
            obj = motif.sub(MASQUE_SUJET, obj)
        return obj
    if isinstance(obj, dict):
        return {k: _caviarder_objet(v, motifs) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_caviarder_objet(v, motifs) for v in obj]
    return obj


def filtrer_sortie_agent(result, agent, args=None, ring=None):
    """Point d'envoi du hub : retient le prive pour un agent expose. Pas d'alias : ces agents n'ont pas d'`unwrap`.
    Un filtre en panne se ferme pour eux : retenir une sortie se rattrape, une fuite non."""
    if not agent_expose(agent, ring):
        return result
    try:
        s = _sujets_compiles()
        args = args if isinstance(args, dict) else {}
        if any(_chemin_prive(args.get(c), s["chemins"]) for c in ("path", "file_path", "script") if args.get(c)):
            return "[SUJET PRIVE] fichier prive retenu pour cet agent : tache a confier a un modele sans retention ou local."
        return _caviarder_objet(result, s["masques"])
    except Exception as exc:  # noqa: BLE001 - voir la docstring
        logger.warning("[membrane] filtre des sujets prives en panne (%s) : sortie retenue pour %s", type(exc).__name__, agent)
        return "[SUJET PRIVE] filtre indisponible (%s) : sortie retenue pour cet agent." % type(exc).__name__


def refus_sujet_prive(description, agent) -> str | None:
    """Motif de refus si une consigne touche un sujet prive et que l'agent est expose. Ne cite jamais le sujet."""
    if not agent_expose(agent):
        return None
    try:
        s = _sujets_compiles()
        texte = str(description or "")
        jetons = re.findall(r"[\w./\\:\-]+", texte)
        if any(m.search(texte) for m in s["mots"]) or any(_chemin_prive(j, s["chemins"]) for j in jetons):
            return ("[SUJET PRIVE] consigne touchant un sujet prive refusee pour %s : a confier a un modele sans retention "
                    "ou local (choix owner du 6/11)." % agent)
        return None
    except Exception as exc:  # noqa: BLE001 - liste illisible : on n'envoie pas, et on le dit
        return "[SUJET PRIVE] filtre indisponible (%s) : consigne non envoyee a %s." % (type(exc).__name__, agent)


def _get_guardian():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from nokido_agent.app.forge_silo_fragmenter import NoiseGuardian

    return NoiseGuardian()


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class TraversalRecord:
    """Trace d'un signal traversant la membrane — sans contenu sensible."""

    ts: str
    direction: str  # "out" (local→cloud) | "in" (cloud→local)
    mission_id: str
    model: str
    alias_count: int  # nb d'alias substitués
    content_hash: str  # SHA-256 du contenu original (non stocké)
    tool_calls: int  # nb de tool_calls résolus
    elapsed_ms: float


@dataclass
class MembraneResult:
    """Résultat d'un wrap ou unwrap."""

    content: str
    alias_map: dict[str, str]  # original → alias
    decoy_meta: list[str]  # decoys injectés (metadata, pas dans content)
    content_hash: str
    alias_count: int


# ══════════════════════════════════════════════════════════════════════════════
# SOVEREIGN MEMBRANE
# ══════════════════════════════════════════════════════════════════════════════


class SovereignMembrane:
    """
    Membrane bidirectionnelle entre le monde interne et le monde externe.

    Usage:
        membrane = SovereignMembrane(mission_id="recon_20260328")
        wrapped  = membrane.wrap(raw_prompt)
        payload  = membrane.build_payload(model, wrapped.content, tools)
        result   = call_cloud_api(payload)
        clean    = membrane.unwrap(result, tool_calls=result.get("tool_calls"))
    """

    # Patterns étendus à anonymiser (complète NoiseGuardian)
    _EXTRA_PATTERNS: list[tuple[re.Pattern, str]] = [
        # Hostnames locaux (*.local, *.lan, *.internal)
        (re.compile(r"\b[\w-]+\.(?:local|lan|internal|corp|home)\b", re.I), "HOST"),
        # Chemins Windows
        (re.compile(r'[A-Z]:\\(?:Users|Program Files|Windows)\\[^\s"\']+', re.I), "WINPATH"),
        # Chemins Linux sensibles
        (re.compile(r"/(?:home|root|etc|var/log)/[\w/.-]+", re.I), "NIXPATH"),
        # Noms d'utilisateurs Windows (DOMAIN\user ou .\user)
        (re.compile(r"\b(?:[A-Z]{2,15}\\|\.\\)[\w-]{2,32}\b"), "WINUSER"),
        # Noms de containers Docker (exegol-*)
        (re.compile(r"\bexegol-[\w-]+\b", re.I), "CONTAINER"),
        # UUIDs / GUIDs
        (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "UUID"),
        # Tokens / clés (heuristique : 32+ chars hex ou base64)
        (re.compile(r"\b(?:[0-9a-zA-Z+/]{32,}={0,2})\b"), "SECRET"),
        # Noms de domaines internes (*.duckdns, *.ddns)
        (re.compile(r"\b[\w-]+\.(?:duckdns|ddns|ngrok|tailscale)\.[\w.]+\b", re.I), "EXTDNS"),
    ]

    _DECOY_POOL: list[str] = [
        "[*] Analyse du module auxiliaire 'legacy_auth_v1'...",
        "[!] Alerte : Certificat auto-signé détecté sur NODE_DUMMY.",
        "DEBUG: Initialisation de la couche de compatibilité 0xCC.",
        "[*] Session token refresh sur SRV_MGMT_PLACEHOLDER.",
        "[!] Timeout détecté sur INTERFACE_LEGACY_ETH0.",
        "DEBUG: GC cycle — freed 847KB, pool_id=SHARD_NULL.",
        "[*] Watchdog heartbeat seq=1847 — PROC_SENTINEL_NOP.",
        "[!] Rotation de clé planifiée pour VAULT_NULL_INSTANCE.",
    ]

    def __init__(
        self,
        mission_id: str = "default",
        db_path: str = "",
        audit_cb: Callable[[TraversalRecord], None] | None = None,
        hmac_secret: bytes = b"",
    ):
        self.mission_id = mission_id
        self.audit_cb = audit_cb
        self._guardian = None  # lazy

        # DB SQLite WAL pour persistance des alias par mission
        _root = Path(__file__).resolve().parent.parent
        self._db = db_path or str(_root / "recon_silo" / "recon_data" / "membrane.db")
        Path(self._db).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

        # Derivation HMAC key par mission a partir d'un master persistant.
        # Garantit que "meme original = meme alias par mission" tient au
        # travers des restarts ET des process simultanes (sinon divergence
        # alias_A vs alias_B sur 2 process meme mission).
        if hmac_secret:
            self._hmac_key = hmac_secret
        else:
            master = self._load_or_create_master()
            self._hmac_key = hmac.new(master, mission_id.encode(), hashlib.sha256).digest()

        # Cache en RAM pour la session courante
        self._alias_cache: dict[str, str] = {}  # original  → alias
        self._reverse_cache: dict[str, str] = {}  # alias     → original
        self.migrate_to_encryption()  # Assure que les originaux legacy sont chiffrés
        self._load_aliases()

    # ── Master secret (persistant pour determinisme HMAC) ────────────────────

    def migrate_to_encryption(self) -> int:
        """
        Migre les originaux en clair vers la version chiffrée DPAPI (at-rest).
        Audit 2026-06-15 : purge du clair de la base SQLite et du cache.
        """
        count = 0
        try:
            with closing(sqlite3.connect(self._db)) as conn:
                rows = conn.execute(
                    "SELECT original, alias FROM alias_map WHERE original NOT LIKE 'ENC:%'"
                ).fetchall()
                for orig, alias in rows:
                    new_val = self._enc_original(orig)
                    conn.execute(
                        "UPDATE alias_map SET original=? WHERE alias=?", (new_val, alias)
                    )
                    count += 1
                if count > 0:
                    conn.commit()
                    logger.info(f"[membrane] {count} originaux migrés vers chiffrement (at-rest)")
        except Exception as e:
            logger.debug(f"[membrane] échec migration: {e}")
        return count

    def _load_or_create_master(self) -> bytes:
        """
        Charge ou cree le master secret pour deriver les HMAC keys par mission.

        Priorite :
          1. Variable env LAFORGE_MEMBRANE_MASTER (hex 0x... ou utf-8)
          2. Fichier .membrane_master.key dans le meme dir que membrane.db
          3. Premier run : genere et persiste

        Avec ce schema, le meme mission_id donne la meme cle a travers les
        restarts et les process simultanes. L'audit trail est verifiable
        par tout auditeur ayant acces au master + mission_id.
        """
        env = os.environ.get("LAFORGE_MEMBRANE_MASTER")
        if env:
            if env.startswith("0x") and len(env) >= 34:
                try:
                    return bytes.fromhex(env[2:])
                except ValueError:
                    __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 220, exc_info=True)
            return env.encode("utf-8")

        secret_file = Path(self._db).parent / ".membrane_master.key"
        if secret_file.exists():
            return secret_file.read_bytes()

        # Premier run : genere et persiste — création ATOMIQUE (audit 2026-06-15 :
        # exists()->write_bytes() = TOCTOU, 2 process concurrents -> masters divergents
        # -> alias divergents ; + fenêtre lecture-monde avant chmod).
        master = os.urandom(32)
        try:
            fd = os.open(str(secret_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, master)
            finally:
                os.close(fd)
        except FileExistsError:
            return secret_file.read_bytes()  # course : un autre process l'a créé -> SA clé
        try:
            os.chmod(secret_file, 0o600)
        except (OSError, NotImplementedError):
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 242, exc_info=True)
        return master

    @staticmethod
    def _enc_original(s: str) -> str:
        """Chiffre la valeur réelle AU REPOS (DPAPI machine, forge_machine_vault). Audit
        2026-06-15 CRITICAL : `original`/`real` étaient stockés EN CLAIR (promesse 'jamais
        le sensible at-rest' cassée). Réversible (unwrap post-restart en a besoin).
        Dégradé -> clair si le vault est indispo (pas pire que l'état d'avant)."""
        try:
            import base64 as _b64
            from nokido_agent.app.forge_machine_vault import _protect
            return "ENC:" + _b64.b64encode(_protect(s.encode("utf-8"))).decode("ascii")
        except Exception:
            return s

    @staticmethod
    def _dec_original(s: str) -> str:
        if isinstance(s, str) and s.startswith("ENC:"):
            try:
                import base64 as _b64
                from nokido_agent.app.forge_machine_vault import _unprotect
                return _unprotect(_b64.b64decode(s[4:])).decode("utf-8", "replace")
            except Exception:
                return s
        return s  # legacy clair (rétro-compat)

    # ── DB ────────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with closing(sqlite3.connect(self._db)) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alias_map (
                    mission_id TEXT NOT NULL,
                    original   TEXT NOT NULL,
                    alias      TEXT NOT NULL,
                    category   TEXT NOT NULL,
                    created_ts TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (mission_id, original)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts           TEXT,
                    direction    TEXT,
                    mission_id   TEXT,
                    model        TEXT,
                    alias_count  INTEGER,
                    content_hash TEXT,
                    tool_calls   INTEGER,
                    elapsed_ms   REAL
                )
            """)
            conn.commit()

    def _load_aliases(self) -> None:
        """Charge les alias existants de cette mission depuis SQLite."""
        with closing(sqlite3.connect(self._db)) as conn:
            rows = conn.execute(
                "SELECT original, alias FROM alias_map WHERE mission_id=?", (self.mission_id,)
            ).fetchall()
        for orig_enc, alias in rows:
            orig = self._dec_original(orig_enc)  # déchiffre la valeur réelle
            self._alias_cache[orig] = alias
            self._reverse_cache[alias] = orig

    def _persist_alias(self, original: str, alias: str, category: str) -> None:
        with closing(sqlite3.connect(self._db)) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO alias_map (mission_id,original,alias,category) VALUES (?,?,?,?)",
                (self.mission_id, self._enc_original(original), alias, category),
            )
            conn.commit()
        # WAL mirror sur bind mount Windows (VSS-friendly).
        # Best-effort, ne lève jamais : SQLite reste source de vérité.
        try:
            persist_dir = Path(
                os.environ.get("LAFORGE_PERSIST_DIR") or str(Path(__file__).resolve().parent.parent / "nokido_persist")
            )
            persist_dir.mkdir(parents=True, exist_ok=True)
            wal_file = persist_dir / "vault_wal.jsonl"
            record = {
                "op": "set",
                "alias": alias,
                "real": self._enc_original(original),  # chiffré at-rest (audit CRITICAL)
                "mission": self.mission_id,
                "category": category,
                "ts": int(time.time() * 1000),
            }
            with open(wal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 336, exc_info=True)

    def replay_wal_to_db(self) -> int:
        """Replay vault_wal.jsonl dans alias_map SQLite.
        Utile si membrane.db perdue (vhdx corrompu) mais WAL préservé sur bind mount.
        Retourne nb d entrées restaurées pour cette mission.
        """
        try:
            persist_dir = Path(
                os.environ.get("LAFORGE_PERSIST_DIR") or str(Path(__file__).resolve().parent.parent / "nokido_persist")
            )
            wal_file = persist_dir / "vault_wal.jsonl"
            ckp_file = persist_dir / "vault_checkpoint.json"
            count = 0
            entries: list[dict] = []
            # 1. checkpoint complet
            if ckp_file.exists():
                try:
                    entries = json.loads(ckp_file.read_text(encoding="utf-8")) or []
                except Exception:
                    entries = []
            # 2. WAL postérieur
            if wal_file.exists():
                for line in wal_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        entries.append(rec)
                    except Exception:
                        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 366, exc_info=True)
                        continue
            with closing(sqlite3.connect(self._db)) as conn:
                for rec in entries:
                    if rec.get("mission") != self.mission_id:
                        continue
                    if rec.get("op") == "set":
                        try:
                            conn.execute(
                                "INSERT OR IGNORE INTO alias_map (mission_id,original,alias,category) VALUES (?,?,?,?)",
                                (rec["mission"], rec["real"], rec["alias"], rec.get("category", "GEN")),
                            )
                            count += 1
                        except Exception:
                            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 379, exc_info=True)
                    elif rec.get("op") == "del":
                        try:
                            conn.execute(
                                "DELETE FROM alias_map WHERE mission_id=? AND alias=?", (rec["mission"], rec["alias"])
                            )
                        except Exception:
                            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 386, exc_info=True)
                conn.commit()
            self._load_aliases()
            return count
        except Exception:
            return 0

    # ── Alias engine ──────────────────────────────────────────────────────────

    def _make_alias(self, original: str, category: str) -> str:
        if original in self._alias_cache:
            return self._alias_cache[original]

        # Alias déterministe HMAC — même original = même alias par mission. 12 hex (48 bits)
        # au lieu de 6 (24 bits) : audit 2026-06-15, collision birthday ~4096 originaux/cat
        # -> unwrap restituait le MAUVAIS original. + détection collision explicite.
        sig = hmac.new(self._hmac_key, original.encode(), hashlib.sha256).hexdigest()[:12].upper()
        alias = f"SRV_{category}_{sig}"
        _existing = self._reverse_cache.get(alias)
        if _existing is not None and _existing != original:
            sig = hmac.new(self._hmac_key, (original + "\x00c").encode(), hashlib.sha256).hexdigest()[:12].upper()
            alias = f"SRV_{category}_{sig}"
        self._alias_cache[original] = alias
        self._reverse_cache[alias] = original
        self._persist_alias(original, alias, category)
        return alias

    def _apply_guardian(self, text: str) -> tuple[str, int]:
        """Applique NoiseGuardian (IPs, MACs, CVEs) + patterns étendus."""
        if self._guardian is None:
            try:
                self._guardian = _get_guardian()
            except Exception:
                self._guardian = None

        count = 0
        result = text

        # NoiseGuardian (IPs, MACs, CVEs déjà gérés)
        if self._guardian is not None:
            try:
                result, rpt = self._guardian.sanitize(result, add_entropy=False)
                count += rpt.get("neutralized_ips", 0) + rpt.get("neutralized_sigs", 0)
            except Exception:
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 430, exc_info=True)

        # Patterns étendus
        for pattern, category in self._EXTRA_PATTERNS:
            for m in list(set(pattern.findall(result))):
                val = m if isinstance(m, str) else m[0]
                alias = self._make_alias(val, category)
                result = result.replace(val, alias)
                count += 1

        # Sujets prives : meme definition que la publication.
        try:
            for pattern in _sujets_compiles()["masques"]:
                for val in {m.group(0) for m in pattern.finditer(result)}:
                    result = result.replace(val, self._make_alias(val, "SUJET_PRIVE"))
                    count += 1
            for pattern, category in _motifs_secrets():
                for val in {m.group(0) for m in pattern.finditer(result)}:
                    result = result.replace(val, self._make_alias(val, category))
                    count += 1
        except Exception as exc:  # noqa: BLE001 - sans la liste, la couverture baisse : on le DIT
            logger.warning("[membrane] sujets prives ou secrets illisibles (%s) : couverture reduite", type(exc).__name__)

        return result, count

    # ── PUBLIC API ────────────────────────────────────────────────────────────

    # ── Mode REVERSIBLE (2026-09-25, passerelle :7777, decision owner « pseudonymiser ») ──
    # Le mode historique (reconnaissance) passe par NoiseGuardian, qui ecrit du bruit a SENS
    # UNIQUE : `neutralize_magic` remplace `0x...` et des ports par des compteurs sans table de
    # retour, `sanitize` rend une chaine VIDE sur un motif d'injection. Pour un agent de CODE
    # (opencode) qui lit un fichier et le reecrit, c'est une corruption. Le mode reversible
    # n'emploie QUE des alias HMAC persistants (`_make_alias`) : les motifs de la membrane, les
    # IP hors boucle locale, et les motifs de la DLP du pare-feu -- rien de ce qu'elle refuserait
    # ne sort, et tout revient par `unwrap`. Le mode par defaut ne change pas.
    _IP_REVERSIBLE = re.compile(r"\b(?!127\.)(?:\d{1,3}\.){3}\d{1,3}\b")

    # Motifs « en forme de chemin » ecartes du mode reversible. MESURE runtime 2026-09-25 :
    # WINPATH avale un chemin jusqu'au premier espace et WINUSER prend `IA\Nokido` pour
    # DOMAINE\user -> gpt-oss recevait `SRV_WINPATH_… python SRV_WINUSER_…` et rendait un chemin
    # TRONQUE. Un agent de code doit LIRE le chemin : seule la partie sensible (le compte, motif
    # PATH_WIN / PATH_UNIX de la DLP) est masquee, le reste du chemin reste en clair.
    _GROSSIERS_POUR_LE_CODE = {"WINPATH", "NIXPATH", "WINUSER"}

    def _motifs_reversibles(self) -> list[tuple[re.Pattern, str]]:
        # Sujets d'abord, sans repli : une liste illisible leve, et la passerelle ne laisse alors rien partir (503).
        motifs: list[tuple[re.Pattern, str]] = [(p, "SUJET_PRIVE") for p in _sujets_compiles()["masques"]] + _motifs_secrets()
        try:
            from nokido_agent.app.forge_semantic_firewall import _REDACT_PATTERNS

            # La DLP D'ABORD : ses motifs sont les plus fins (le compte, pas le chemin entier).
            motifs += [(p, str(label)) for p, label in _REDACT_PATTERNS]
        except Exception as exc:  # noqa: BLE001 - sans les motifs DLP, la DLP refusera : on le DIT
            logger.warning("[membrane] motifs DLP illisibles (%s) : couverture reduite", type(exc).__name__)
        motifs.append((self._IP_REVERSIBLE, "IP"))
        motifs += [(p, c) for p, c in self._EXTRA_PATTERNS if c not in self._GROSSIERS_POUR_LE_CODE]
        return motifs

    # Un chemin garde sa RACINE en clair (`C:\`, `/`) : il reste ABSOLU aux yeux du modele.
    # MESURE runtime 2026-09-25 : avec l'alias nu (`SRV_PATH_WIN_…\Script…`), gpt-oss prefixait
    # parfois `C:\` lui-meme -> `C:\C:\Users\...` a la restitution (1 essai sur 3). Le reste
    # (`Users\<compte>`) est masque : l'alias ne rappelle pas le motif de la DLP.
    _RACINE_DE_CHEMIN = re.compile(r"^(?:[A-Za-z]:[\\/]|/)")
    _CHEMINS_A_RACINE = {"PATH_WIN", "PATH_UNIX"}

    def _apply_reversible(self, text: str) -> tuple[str, int]:
        count = 0
        result = text
        for pattern, category in self._motifs_reversibles():
            for m in list(pattern.finditer(result)):
                val = m.group(0)
                if not val or val.startswith("SRV_"):
                    continue  # deja un alias
                racine = ""
                if category in self._CHEMINS_A_RACINE:
                    r = self._RACINE_DE_CHEMIN.match(val)
                    racine = r.group(0) if r else ""
                result = result.replace(val, racine + self._make_alias(val[len(racine):], category))
                count += 1
        return result, count

    def _restituer_texte(self, text: str, echapper_json: bool = False) -> str:
        result = text
        for alias in sorted(self._reverse_cache.keys(), key=len, reverse=True):
            if alias in result:
                original = self._reverse_cache[alias]
                result = result.replace(alias, json.dumps(original)[1:-1] if echapper_json else original)
        if self._guardian is not None:
            try:
                result = self._guardian.deanonymize(result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[membrane] deanonymize guardian echoue (%s)", type(exc).__name__)
        return result

    def _parcourir(self, obj: Any, sur_texte: Callable[[str], str], sur_json: Callable[[str], str]) -> Any:
        """Copie de `obj` (listes, dicts, chaines) ; `arguments` d'un appel d'outil = JSON en chaine."""
        if isinstance(obj, str):
            return sur_texte(obj)
        if isinstance(obj, list):
            return [self._parcourir(x, sur_texte, sur_json) for x in obj]
        if isinstance(obj, dict):
            return {k: (sur_json(v) if k == "arguments" and isinstance(v, str)
                        else self._parcourir(v, sur_texte, sur_json)) for k, v in obj.items()}
        return obj

    def _json_via(self, chaine: str, sur_texte: Callable[[str], str], sinon: Callable[[str], str]) -> str:
        """Transforme les chaines DANS le JSON parse puis re-serialise : jamais de chemin brut
        reinjecte dans du JSON serialise (`\\U...` = echappement invalide, mesure 2026-09-25)."""
        try:
            donnees = json.loads(chaine)
        except (json.JSONDecodeError, TypeError):
            return sinon(chaine)
        return json.dumps(self._parcourir(donnees, sur_texte, lambda s: s), ensure_ascii=False)

    def wrap_objet(self, obj: Any) -> Any:
        """LOCAL → CLOUD, mode reversible, sur un objet (messages, schemas d'outils). Un audit."""
        t0 = time.perf_counter()
        compte = [0]

        def _texte(s: str) -> str:
            sortie, n = self._apply_reversible(s)
            compte[0] += n
            return sortie

        resultat = self._parcourir(obj, _texte, lambda s: self._json_via(s, _texte, _texte))
        empreinte = hashlib.sha256(json.dumps(obj, ensure_ascii=False, default=str).encode()).hexdigest()[:16]
        self._audit("out", "", compte[0], empreinte, 0, (time.perf_counter() - t0) * 1000)
        return resultat

    def unwrap_objet(self, obj: Any, model: str = "") -> Any:
        """CLOUD → LOCAL sur un objet (message de reponse, appels d'outil) ; JSON reste valide."""
        t0 = time.perf_counter()
        resultat = self._parcourir(
            obj, self._restituer_texte,
            lambda s: self._json_via(s, self._restituer_texte,
                                     lambda brut: self._restituer_texte(brut, echapper_json=True)))
        empreinte = hashlib.sha256(json.dumps(resultat, ensure_ascii=False, default=str).encode()).hexdigest()[:16]
        self._audit("in", model, len(self._alias_cache), empreinte, 0, (time.perf_counter() - t0) * 1000)
        return resultat

    def wrap(self, content: str, reversible: bool = False) -> MembraneResult:
        """
        LOCAL → CLOUD
        Anonymise le contenu. Retourne le contenu sécurisé + metadata.
        Les decoys NE sont PAS injectés dans le contenu — metadata seulement.
        `reversible=True` : alias HMAC seulement, tout revient par `unwrap` (voir plus haut).
        """
        t0 = time.perf_counter()

        # Hash du contenu original (pour audit — sans stocker le contenu)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Anonymisation
        if reversible:
            safe_content, alias_count = self._apply_reversible(content)
        else:
            safe_content, alias_count = self._apply_guardian(content)

        # Choix de 2 decoys (metadata, pas injectés dans le prompt)
        import random

        decoy_meta = random.sample(self._DECOY_POOL, k=2)

        # alias_map : SEULEMENT les alias présents dans CE contenu (audit 2026-06-15 :
        # retourner tout self._alias_cache fuitait TOUS les originaux de la mission).
        used = {orig: al for orig, al in self._alias_cache.items() if al in safe_content}
        result = MembraneResult(
            content=safe_content,
            alias_map=used,
            decoy_meta=decoy_meta,
            content_hash=content_hash,
            alias_count=alias_count,
        )

        self._audit("out", "", alias_count, content_hash, 0, (time.perf_counter() - t0) * 1000)
        return result

    def unwrap(
        self,
        cloud_response: str,
        tool_calls: list[dict] | None = None,
        model: str = "",
    ) -> str:
        """
        CLOUD → LOCAL
        Restitue les données réelles. Résout les tool_calls si présents.
        """
        t0 = time.perf_counter()

        # 1. Résolution des alias dans la réponse texte (plus longs d'abord), puis des alias du
        # guardian -- ceux-la n'etaient jamais restitues (mesure 2026-09-25).
        result = self._restituer_texte(cloud_response)

        # 2. Résolution des alias dans les tool_calls
        resolved_calls = 0
        if tool_calls:
            resolved_calls = self._unwrap_tool_calls(tool_calls)

        content_hash = hashlib.sha256(result.encode()).hexdigest()[:16]
        self._audit(
            "in", model, len(self._alias_cache), content_hash, resolved_calls, (time.perf_counter() - t0) * 1000
        )

        return result.strip()

    def build_payload(
        self,
        model: str,
        content: str,
        tools: list[dict],
        system: str = "Tu es un assistant technique expert opérant sur un environnement segmenté.",
    ) -> dict:
        """
        Construit le payload final pour l'API cloud.
        [DIRECTIVE 2026-03-22] : tools obligatoires — lève une exception sinon.
        """
        if not tools:
            raise ValueError(
                "DIRECTIVE SOUVERAINE VIOLÉE : les définitions d'outils sont obligatoires. "
                "Aucun payload ne peut être généré sans la liste tools complète."
            )

        # Wrap du contenu
        wrapped = self.wrap(content)

        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": wrapped.content},
            ],
            "tools": tools,
            "tool_choice": "auto",
            # Metadata souveraine — jamais envoyée au LLM cloud
            # (usage interne pour logging / debug)
            "_sovereign_meta": {
                "mission_id": self.mission_id,
                "alias_count": wrapped.alias_count,
                "content_hash": wrapped.content_hash,
                "decoys": wrapped.decoy_meta,
            },
        }

    # ── Tool call resolver ────────────────────────────────────────────────────

    def _unwrap_tool_calls(self, tool_calls: list[dict]) -> int:
        """
        Résout les alias dans les arguments de tool_calls AVANT exécution.
        Modifie tool_calls en place. Retourne le nb d'alias résolus.
        """
        # MESURE 2026-09-25 : l'alias etait remplace par l'original DANS le JSON serialise -- un
        # chemin Windows y devenait `\U`, `\N`... (JSONDecodeError chez le client). On restitue
        # dans les chaines du JSON PARSE, puis on re-serialise.
        count = 0
        for call in tool_calls:
            if "function" in call:
                args_raw = call["function"].get("arguments", "{}")
                texte = args_raw if isinstance(args_raw, str) else json.dumps(args_raw)
                restitue = self._json_via(
                    texte, self._restituer_texte,
                    lambda brut: self._restituer_texte(brut, echapper_json=True))
                if restitue != texte:
                    count += 1
                call["function"]["arguments"] = restitue
        return count

    # ── Audit ─────────────────────────────────────────────────────────────────

    def _audit(
        self,
        direction: str,
        model: str,
        alias_count: int,
        content_hash: str,
        tool_calls: int,
        elapsed_ms: float,
    ) -> None:
        record = TraversalRecord(
            ts=time.strftime("%Y-%m-%dT%H:%M:%S"),
            direction=direction,
            mission_id=self.mission_id,
            model=model,
            alias_count=alias_count,
            content_hash=content_hash,
            tool_calls=tool_calls,
            elapsed_ms=round(elapsed_ms, 2),
        )
        # Persiste dans SQLite
        try:
            with closing(sqlite3.connect(self._db)) as conn:
                conn.execute(
                    "INSERT INTO audit_log "
                    "(ts,direction,mission_id,model,alias_count,content_hash,tool_calls,elapsed_ms) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        record.ts,
                        record.direction,
                        record.mission_id,
                        record.model,
                        record.alias_count,
                        record.content_hash,
                        record.tool_calls,
                        record.elapsed_ms,
                    ),
                )
                conn.commit()
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 723, exc_info=True)
        # Callback externe (ex: BUS SSE)
        if self.audit_cb:
            try:
                self.audit_cb(record)
            except Exception:
                __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'app/forge_sovereign_membrane.py', 729, exc_info=True)

    # ── Utilitaires ───────────────────────────────────────────────────────────

    def session_report(self) -> dict:
        """Résumé de la session courante — sans contenu sensible."""
        with closing(sqlite3.connect(self._db)) as conn:
            total_out = conn.execute(
                "SELECT COUNT(*), SUM(alias_count) FROM audit_log WHERE mission_id=? AND direction='out'",
                (self.mission_id,),
            ).fetchone()
            total_in = conn.execute(
                "SELECT COUNT(*), SUM(tool_calls) FROM audit_log WHERE mission_id=? AND direction='in'",
                (self.mission_id,),
            ).fetchone()
        return {
            "mission_id": self.mission_id,
            "aliases_persisted": len(self._alias_cache),
            "calls_out": total_out[0] or 0,
            "total_aliases_out": total_out[1] or 0,
            "calls_in": total_in[0] or 0,
            "tool_calls_fixed": total_in[1] or 0,
        }

    def reset_mission(self) -> None:
        """Efface tous les alias de la mission courante (nouvelle mission)."""
        with closing(sqlite3.connect(self._db)) as conn:
            conn.execute("DELETE FROM alias_map WHERE mission_id=?", (self.mission_id,))
            conn.commit()
        self._alias_cache.clear()
        self._reverse_cache.clear()

    @classmethod
    def for_mission(cls, mission_id: str, **kwargs) -> "SovereignMembrane":
        """Factory — crée ou reprend une session existante."""
        return cls(mission_id=mission_id, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# DEMO / TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== SovereignMembrane — Demo ===\n")

    membrane = SovereignMembrane.for_mission("demo_2026")

    # Données locales réelles
    real_prompt = (
        "La base de données sur localhost (exegol-tapple) refuse les connexions SSL. "
        "Le hostname est db.nokido.local et le cert est stocké dans /etc/ssl/certs/nokido.pem. "
        "CVE-2021-44228 a été détectée sur le service.\n"
        "Utilisateur : NOKIDO\\user. Token : ghp_DEMO_FACTICE_redacted_non_reel"  # dummy demo (placeholder non-matching, ex-PAT realiste bloque par egress gate)
    )

    print("📥 ORIGINAL (local):")
    print(f"  {real_prompt[:120]}...\n")

    # WRAP
    wrapped = membrane.wrap(real_prompt)
    print("📡 ENVOYÉ AU CLOUD (anonymisé):")
    print(f"  {wrapped.content[:120]}...")
    print(f"  Alias count: {wrapped.alias_count}")
    print(f"  Decoys (metadata only): {wrapped.decoy_meta[0][:50]}...\n")

    # Simule réponse cloud avec alias
    mock_response = (
        f"Vérifiez la configuration du certificat sur {list(membrane._alias_cache.values())[0] if membrane._alias_cache else 'SRV_NET_XXXXXX'}. "
        "Assurez-vous que le port 443 est ouvert et que TLS 1.2 est activé."
    )

    # UNWRAP
    restored = membrane.unwrap(mock_response)
    print("✅ RÉPONSE RESTITUÉE (réel):")
    print(f"  {restored[:120]}\n")

    # Rapport de session
    print("📊 Session report:")
    for k, v in membrane.session_report().items():
        print(f"  {k}: {v}")
