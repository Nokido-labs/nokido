# -*- coding: utf-8 -*-
"""Index de pointeurs de contexte sans copie et rejeu déterministe (Phase ① - Observation).

Pourquoi pas un module existant ?
forge_mcp_registry archive les blobs CCR sous sandbox/ccr, et forge_run_sortie borne
les sorties d'outils sous sandbox/run_sorties : aucun de ces modules n'indexe les pointeurs
sans copie, ne filtre selon une requête ni ne sert ou rejoue de façon déterministe
le contexte utile avec preuve cryptographique par SHA-256.

Contrat fixé par tests/nr/test_context_ledger_nr.py (décision owner 2026-11-08) :
- Index SQLite sous <racine>/sandbox/context_ledger.db (jamais embeddings.db).
- Résolution locale : ccr://, run_sortie://, agent_messages://, git://.
- Aucune copie de matière dans l'index (essence <= 150 caractères).
- Invalidation par superseded_by / active (jamais de suppression).
- Sélection et service déterministes (payload <= budget_car).
- Rejeu bit-à-bit vérifié par empreinte SHA-256.
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/context_ledger : index de pointeurs sans copie et service deterministe"

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger("nokido.context_ledger")


ARCS_MEME_TACHE = 16  # voisins de meme tache relies a chaque nouveau pointeur (croissance lineaire)


class ContextLedger:
    """Registre de pointeurs de contexte sans copie, servant la matière utile locale."""

    def __init__(
        self,
        db_path: Union[str, Path],
        racine: Union[str, Path],
        messages_db: Optional[Union[str, Path]] = None,
        depot_git: Optional[Union[str, Path]] = None,
        racines_autorisees: Optional[Union[list, tuple]] = None,
        exiger_sandbox: bool = True,
    ) -> None:
        self.racine = Path(racine).resolve()
        self.db_path = Path(db_path).resolve()
        self.messages_db = Path(messages_db).resolve() if messages_db is not None else None
        self.depot_git = Path(depot_git).resolve() if depot_git is not None else self.racine
        # Magasins de FICHIERS servis (documents cites) : un fichier n'est lisible que sous une de ces racines.
        self.racines_autorisees = tuple(Path(r).resolve() for r in (racines_autorisees or ()))

        # Vérification 1 : jamais embeddings.db
        if self.db_path.name.lower() == "embeddings.db":
            raise ValueError(f"db_path ne peut pas être nommé embeddings.db : {self.db_path}")

        # Vérification 2 : obligatoirement situé sous <racine>/sandbox/. Un ledger de TACHE
        # explicite (exiger_sandbox=False) vit là où l'appelant l'a nommé, déjà borné à sa tâche.
        if exiger_sandbox:
            sandbox_dir = (self.racine / "sandbox").resolve()
            try:
                rel = self.db_path.relative_to(sandbox_dir)
                if rel == Path(".") or str(rel) in ("", "."):
                    raise ValueError("db_path ne peut pas être le dossier sandbox lui-même")
            except ValueError:
                raise ValueError(
                    f"db_path ({self.db_path}) doit être situé sous <racine>/sandbox ({sandbox_dir})"
                )

        self._init_db()

    def _init_db(self) -> None:
        """Initialise la table context_ledger sous SQLite."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS context_ledger (
                    uri TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    taille INTEGER NOT NULL,
                    essence TEXT,
                    access_count INTEGER DEFAULT 0,
                    valid_until TEXT,
                    superseded_by TEXT,
                    active INTEGER DEFAULT 1,
                    meta TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context_active ON context_ledger(active)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS context_arcs (
                    src TEXT NOT NULL,
                    dst TEXT NOT NULL,
                    type TEXT NOT NULL,
                    PRIMARY KEY (src, dst, type)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context_arcs_src ON context_arcs(src)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context_arcs_dst ON context_arcs(dst)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context_arcs_type ON context_arcs(type)")
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS context_fts USING fts5(
                    uri,
                    essence
                )
            """)
            conn.commit()

    def _confiner(self, magasin: str, nom: str) -> Path:
        """Chemin de `nom` DANS sandbox/<magasin>, sinon ValueError.

        Relecture 8/11 : `../` sortait du magasin, et un chemin absolu remplaçait la racine
        (Path jette la gauche). Un pointeur ne désigne qu'un fichier de son magasin, nom simple."""
        base = (self.racine / "sandbox" / magasin).resolve()
        if not nom or Path(nom).name != nom or nom in (".", ".."):
            raise ValueError(f"nom hors magasin {magasin} : {nom!r}")
        p = (base / nom).resolve()
        if p.parent != base:
            raise ValueError(f"nom hors magasin {magasin} : {nom!r}")
        if not p.is_file() and not nom.endswith(".txt"):
            p_txt = base / f"{nom}.txt"
            if p_txt.is_file():
                return p_txt
        return p

    def _confiner_fichier(self, chemin: str) -> Path:
        """Résout un chemin de FICHIER réel, confiné aux racines autorisées.

        Relecture 9/11 : l'adaptateur de l'exécuteur lisait tout chemin absolu,
        contournant `_confiner`. Un document cité n'est servi que s'il vit sous une
        racine donnée à la construction ; sinon ValueError, jamais une lecture libre."""
        p = Path(chemin)
        if not p.is_absolute():
            raise ValueError(f"chemin de fichier non absolu : {chemin!r}")
        reel = Path(os.path.realpath(str(p)))
        for racine in self.racines_autorisees:
            try:
                reel.relative_to(racine)
                break
            except ValueError:  # muet-ok : hors de cette racine, on essaie la suivante
                continue
        else:
            raise ValueError(f"chemin hors racines autorisées : {chemin!r}")
        if not reel.is_file():
            raise FileNotFoundError(f"fichier introuvable : {reel}")
        return reel

    def purger_pointeurs_morts(self, dry: bool = False) -> dict:
        """Retire les pointeurs ccr:// et run_sortie:// dont la cible n'existe plus.

        Borne la table (gate firehose 8/11) : une ligne par URI, et un pointeur sans cible ne se
        sert ni ne se rejoue. agent_messages:// et git:// ne sont jamais touchés ici."""
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            uris = [r[0] for r in conn.execute(
                "SELECT uri FROM context_ledger WHERE uri LIKE 'ccr://%' OR uri LIKE 'run_sortie://%'")]
            morts = []
            for u in uris:
                try:
                    p = (self._chemin_ccr(u[len("ccr://"):]) if u.startswith("ccr://")
                         else self._chemin_run_sortie(u[len("run_sortie://"):]))
                    if not p.is_file():
                        morts.append(u)
                except ValueError:
                    morts.append(u)
            if dry or not morts:
                return {"morts": len(morts), "purges": 0, "dry_run": dry}
            conn.executemany("DELETE FROM context_ledger WHERE uri = ?", [(u,) for u in morts])
            conn.executemany("DELETE FROM context_arcs WHERE src = ? OR dst = ?", [(u, u) for u in morts])
            conn.executemany("DELETE FROM context_fts WHERE uri = ?", [(u,) for u in morts])
            conn.commit()
        return {"morts": len(morts), "purges": len(morts)}

    def _chemin_ccr(self, ident: str) -> Path:
        """Résout le chemin d'un blob CCR sous sandbox/ccr."""
        return self._confiner("ccr", ident)

    def _chemin_run_sortie(self, nom: str) -> Path:
        """Résout le chemin d'une sortie sous sandbox/run_sorties."""
        return self._confiner("run_sorties", nom)

    def _sha256_du_stocke(self, uri: str) -> str:
        """Calcule le SHA-256 du contenu stocké d'origine (octets bruts)."""
        if uri.startswith("ccr://"):
            ident = uri[len("ccr://"):]
            path = self._chemin_ccr(ident)
            if not path.is_file():
                raise FileNotFoundError(f"Blob CCR introuvable : {path}")
            return hashlib.sha256(path.read_bytes()).hexdigest()

        elif uri.startswith("run_sortie://"):
            nom = uri[len("run_sortie://"):]
            path = self._chemin_run_sortie(nom)
            if not path.is_file():
                raise FileNotFoundError(f"Fichier run_sortie introuvable : {path}")
            return hashlib.sha256(path.read_bytes()).hexdigest()

        elif uri.startswith("agent_messages://"):
            content = self.resoudre(uri)
            return hashlib.sha256(content.encode("utf-8")).hexdigest()

        elif uri.startswith("git://"):
            content = self.resoudre(uri)
            return hashlib.sha256(content.encode("utf-8")).hexdigest()

        else:
            content = self.resoudre(uri)
            return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _taille_du_stocke(self, uri: str) -> int:
        """Retourne la taille du contenu stocké."""
        if uri.startswith("ccr://"):
            ident = uri[len("ccr://"):]
            path = self._chemin_ccr(ident)
            return path.stat().st_size if path.is_file() else len(self.resoudre(uri))
        elif uri.startswith("run_sortie://"):
            nom = uri[len("run_sortie://"):]
            path = self._chemin_run_sortie(nom)
            return path.stat().st_size if path.is_file() else len(self.resoudre(uri))
        else:
            return len(self.resoudre(uri))

    def resoudre(self, uri: str) -> str:
        """Résout l'URI vers le contenu textuel exact de la matière locale pointée."""
        if uri.startswith("ccr://"):
            ident = uri[len("ccr://"):]
            path = self._chemin_ccr(ident)
            if not path.is_file():
                raise FileNotFoundError(f"Blob CCR introuvable : {path}")
            return path.read_text(encoding="utf-8")

        elif uri.startswith("run_sortie://"):
            nom = uri[len("run_sortie://"):]
            path = self._chemin_run_sortie(nom)
            if not path.is_file():
                raise FileNotFoundError(f"Fichier run_sortie introuvable : {path}")
            return path.read_text(encoding="utf-8")

        elif uri.startswith("agent_messages://"):
            msg_id = uri[len("agent_messages://"):]
            if not self.messages_db or not Path(self.messages_db).is_file():
                raise ValueError(f"messages_db non configuré ou introuvable : {self.messages_db}")
            with sqlite3.connect(str(self.messages_db), timeout=5.0) as conn:
                cur = conn.execute("SELECT payload FROM agent_messages WHERE id = ?", (msg_id,))
                row = cur.fetchone()
                if not row:
                    raise KeyError(f"Message {msg_id} introuvable dans {self.messages_db}")
                payload_raw = row[0]
                data = json.loads(payload_raw)
                return data.get("content", "")

        elif uri.startswith("git://"):
            spec = uri[len("git://"):]
            if ":" not in spec:
                raise ValueError(f"Format git:// invalide, attendu git://<commit>:<chemin> : {uri}")
            commit, chemin = spec.split(":", 1)
            # Commit HEXADÉCIMAL seul : immuable (rejeu au caractère près) et jamais une option
            # de git show (`--output=...` écrivait un fichier).
            if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit) or not chemin:
                raise ValueError(f"git:// exige un commit hexadécimal et un chemin : {uri}")
            res = subprocess.run(
                ["git", "show", f"{commit}:{chemin}"],
                cwd=str(self.depot_git),
                capture_output=True,
                text=True,
                errors="replace",
                check=True,
            )
            return res.stdout

        elif "://" not in uri and self.racines_autorisees:
            # Document cité : chemin de FICHIER réel, confiné aux racines autorisées.
            return self._confiner_fichier(uri).read_text(encoding="utf-8")

        else:
            raise ValueError(f"Schéma d'URI non supporté : {uri}")

    def indexer(
        self,
        uri: str,
        essence: str = "",
        meta: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Indexe un pointeur d'URI sans copier son texte complet.

        Retourne un dictionnaire contenant au moins 'uri' et 'sha256'.
        """
        sha = self._sha256_du_stocke(uri)
        taille = self._taille_du_stocke(uri)
        essence_courte = (essence or "")[:150]
        meta_json = json.dumps(meta, ensure_ascii=False) if meta is not None else None
        now_iso = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            conn.execute("""
                INSERT INTO context_ledger (
                    uri, sha256, taille, essence, access_count, valid_until, superseded_by, active, meta, created_at
                )
                VALUES (?, ?, ?, ?, 0, NULL, NULL, 1, ?, ?)
                ON CONFLICT(uri) DO UPDATE SET
                    sha256 = excluded.sha256,
                    taille = excluded.taille,
                    essence = excluded.essence,
                    meta = excluded.meta
            """, (uri, sha, taille, essence_courte, meta_json, now_iso))

            conn.execute("DELETE FROM context_fts WHERE uri = ?", (uri,))
            conn.execute("INSERT INTO context_fts (uri, essence) VALUES (?, ?)", (uri, essence_courte))

            conn.execute("DELETE FROM context_arcs WHERE (src = ? OR dst = ?) AND type = 'meme_tache'", (uri, uri))
            task_id = meta.get("task_id") if isinstance(meta, dict) else None
            if task_id:
                cur = conn.execute(
                    # Bornage : les ARCS_MEME_TACHE plus recents seulement (chaine connexe pour le PPR) ;
                    # relier a TOUS donnait N^2 arcs (gate firehose 2026-11-08).
                    "SELECT uri FROM context_ledger WHERE active = 1 AND uri != ? AND json_extract(meta, '$.task_id') = ? "
                    "ORDER BY rowid DESC LIMIT ?",
                    (uri, str(task_id), ARCS_MEME_TACHE),
                )
                autres = [row[0] for row in cur.fetchall()]
                for autre in autres:
                    conn.execute(
                        "INSERT OR IGNORE INTO context_arcs (src, dst, type) VALUES (?, ?, 'meme_tache')",
                        (uri, autre),
                    )
                    conn.execute(
                        "INSERT OR IGNORE INTO context_arcs (src, dst, type) VALUES (?, ?, 'meme_tache')",
                        (autre, uri),
                    )

            conn.commit()

        return {
            "uri": uri,
            "sha256": sha,
            "taille": taille,
            "essence": essence_courte,
            "access_count": 0,
            "valid_until": None,
            "superseded_by": None,
            "active": 1,
            "meta": meta,
        }

    def invalider(self, uri: str, superseded_by: Optional[str] = None) -> None:
        """Invalide un pointeur (active=0, superseded_by=...) sans jamais le supprimer."""
        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            conn.execute("""
                UPDATE context_ledger
                SET active = 0, superseded_by = ?
                WHERE uri = ?
            """, (superseded_by, uri))
            conn.execute("DELETE FROM context_fts WHERE uri = ?", (uri,))
            conn.commit()

    def servir(self, requete: str, budget_car: int, uris: Optional[list[str]] = None) -> dict[str, Any]:
        """Sélectionne de façon déterministe les entrées utiles et sert un payload <= budget_car.

        Retourne :
            {"payload": str, "manifeste": {"entrees": [{"uri", "sha256", "debut", "fin", "taille"}]}}
        """
        if budget_car <= 0:
            return {"payload": "", "manifeste": {"entrees": []}}

        # Charger la FONCTION qui désigne les fichiers privés (jamais l'affecter : c'est une
        # fonction, pas une liste — mesure 9/11 : `set(function)` levait). `nokido_agent.` en
        # premier : c'est le pont qui garantit l'identité d'objet avec le module monkeypatché.
        _fichiers_prives = None
        for _nom_mod in ("nokido_agent.app.forge_sovereign_membrane",
                         "app.forge_sovereign_membrane", "forge_sovereign_membrane"):
            try:
                _mod = __import__(_nom_mod, fromlist=["fichiers_prives"])
                _fichiers_prives = getattr(_mod, "fichiers_prives")
                break
            except (ImportError, AttributeError):  # muet-ok : chaine d'import ; aucune -> fail-closed plus bas, dit
                continue

        with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
            cur = conn.execute("""
                SELECT uri, sha256, taille, essence, access_count, meta, rowid
                FROM context_ledger
                WHERE active = 1
                ORDER BY rowid ASC
            """)
            rows = cur.fetchall()
            active_dict = {r[0]: r for r in rows}
            
            # Filtrer par URIs si spécifié
            if uris is not None:
                rows = [r for r in rows if r[0] in uris]
                active_dict = {r[0]: r for r in rows}

            # Exclure ce que la membrane déclare PRIVÉ ; la liste part dans manifeste["refuses"].
            # FAIL-CLOSED (9/11) : sans juge (membrane introuvable ou en panne), « inconnu » n'est pas « non prive » --
            # rien n'est servi et chaque entree est refusee avec son motif. Avant : refuses_prives = [] -> tout servi.
            refuses_prives: list[str] = []
            juge_ok = False
            if _fichiers_prives is not None:
                try:
                    refuses_prives = list(_fichiers_prives([r[0] for r in rows]) or [])
                    juge_ok = True
                except Exception as exc:  # noqa: BLE001
                    logger.warning("fichiers_prives en panne : %s: %s -> rien servi", type(exc).__name__, exc)
            else:
                logger.warning("membrane introuvable (fichiers_prives) -> rien servi")
            if not juge_ok:
                refuses_prives = [r[0] for r in rows]
            if refuses_prives:
                _refuse_set = set(refuses_prives)
                rows = [r for r in rows if r[0] not in _refuse_set]
                active_dict = {r[0]: r for r in rows}

            def _manifeste_base() -> dict[str, Any]:
                _m: dict[str, Any] = {"entrees": []}
                if refuses_prives:
                    _m["refuses"] = list(refuses_prives)
                return _m

            req = (requete or "").strip()
            if not req or req == "*":
                seed_uris = [r[0] for r in rows]
                raw_scores = {u: 1.0 for u in active_dict}
            else:
                tokens = [tok for tok in re.findall(r"\w+", req.lower()) if len(tok) >= 3]
                if not tokens:
                    return {"payload": "", "manifeste": _manifeste_base()}
                fts_q = " OR ".join(f'"{t}"' for t in tokens)
                try:
                    cur_fts = conn.execute("SELECT uri FROM context_fts WHERE context_fts MATCH ?", (fts_q,))
                    seed_uris = [r[0] for r in cur_fts.fetchall() if r[0] in active_dict]
                except Exception:
                    seed_uris = [
                        r[0] for r in rows
                        if any(t in set(re.findall(r"\w+", (r[3] or "").lower())) for t in tokens)
                    ]

                if not seed_uris:
                    return {"payload": "", "manifeste": _manifeste_base()}

                cur_arcs = conn.execute("SELECT src, dst FROM context_arcs")
                arcs = cur_arcs.fetchall()
                graph: dict[str, list[str]] = {r[0]: [] for r in rows}
                for src, dst in arcs:
                    if src in graph and dst in graph:
                        graph[src].append(dst)

                try:
                    from nokido_agent.app.forge_graph_ppr import ppr
                except ImportError:
                    try:
                        from app.forge_graph_ppr import ppr
                    except ImportError:
                        from forge_graph_ppr import ppr

                raw_scores = {u: 0.0 for u in graph}
                for s in seed_uris:
                    seed_ppr = ppr(graph, seed=s)
                    for node, ppr_val in seed_ppr.items():
                        raw_scores[node] = raw_scores.get(node, 0.0) + ppr_val

            candidates = []
            for u in active_dict:
                s_val = raw_scores.get(u, 0.0)
                if s_val > 1e-9:
                    r = active_dict[u]
                    meta_raw = r[5]
                    try:
                        meta_val = json.loads(meta_raw) if meta_raw else {}
                    except Exception:
                        meta_val = {}
                    grade = meta_val.get("grade") if isinstance(meta_val, dict) else None
                    if grade == "OPTIMAL":
                        grade_factor = 1.2
                    elif grade == "REJECTED":
                        grade_factor = 0.3
                    else:
                        grade_factor = 1.0

                    acc_count = r[4] or 0
                    access_factor = math.log2(2 + acc_count)
                    final_score = s_val * grade_factor * access_factor
                    candidates.append({
                        "uri": u,
                        "sha256": r[1],
                        "taille": r[2],
                        "essence": r[3] or "",
                        "score": final_score,
                        "rowid": r[6],
                    })

            candidates.sort(key=lambda x: (-x["score"], x["rowid"]))

            perimes: list[str] = []
            valid_items: list[dict[str, Any]] = []

            for item in candidates:
                u, s, t, ess = item["uri"], item["sha256"], item["taille"], item["essence"]
                try:
                    actual_sha = self._sha256_du_stocke(u)
                except Exception:
                    actual_sha = None

                if actual_sha != s:
                    perimes.append(u)
                else:
                    valid_items.append({"uri": u, "sha256": s, "taille": t, "essence": ess})

            manifeste: dict[str, Any] = _manifeste_base()
            if perimes:
                manifeste["perimes"] = perimes

            if not valid_items:
                return {"payload": "", "manifeste": manifeste}

        contents: list[str] = []
        tailles: list[int] = []
        shas: list[str] = []
        for item in valid_items:
            c = self.resoudre(item["uri"])
            contents.append(c)
            tailles.append(len(c))
            shas.append(item["sha256"])

        n = len(valid_items)

        def _header(idx: int, fin: int) -> str:
            return f"[source: {valid_items[idx]['uri']} sha256:{shas[idx][:12]} car 0-{fin}/{tailles[idx]}]\n"

        def _total_len(alloc_list: list[int]) -> int:
            tot = 0
            for i, a in enumerate(alloc_list):
                if a > 0:
                    tot += len(_header(i, a)) + a
            return tot

        # Trouver le nombre maximal de sources m (0..n) pouvant recevoir au moins 1 caractère
        m = 0
        min_costs = 0
        for i in range(n):
            c_min = len(_header(i, 1)) + 1
            if min_costs + c_min <= budget_car:
                min_costs += c_min
                m += 1
            else:
                break

        if m == 0:
            return {"payload": "", "manifeste": manifeste}

        # Allocation initiale : 1 caractère pour chacune des m sources
        alloc = [1] * m
        active_indices = set(range(m))
        for i in range(m):
            if alloc[i] >= tailles[i]:
                active_indices.remove(i)

        rem_budget = budget_car - _total_len(alloc)

        while active_indices and rem_budget > 0:
            share = rem_budget // len(active_indices)
            if share == 0:
                for idx in sorted(active_indices):
                    if alloc[idx] < tailles[idx]:
                        alloc[idx] += 1
                        if _total_len(alloc) <= budget_car:
                            rem_budget = budget_car - _total_len(alloc)
                        else:
                            alloc[idx] -= 1
                            break
                break

            progress = False
            to_remove = []
            for idx in sorted(active_indices):
                needed = tailles[idx] - alloc[idx]
                take = min(needed, share)
                if take > 0:
                    alloc[idx] += take
                    progress = True
                if alloc[idx] >= tailles[idx]:
                    to_remove.append(idx)
            for idx in to_remove:
                active_indices.remove(idx)
            current_len = _total_len(alloc)
            rem_budget = budget_car - current_len
            if not progress or rem_budget <= 0:
                break

        # Sécurité : si dépassement dû au changement de longueur du header
        while _total_len(alloc) > budget_car:
            reduced = False
            for idx in reversed(range(m)):
                if alloc[idx] > 0:
                    alloc[idx] -= 1
                    reduced = True
                    if _total_len(alloc) <= budget_car:
                        break
            if not reduced:
                break

        # Optimisation fine : utiliser la marge restante dans l'ordre déterministe
        current_cost = _total_len(alloc)
        while current_cost < budget_car:
            increased = False
            for idx in range(m):
                if alloc[idx] < tailles[idx]:
                    alloc[idx] += 1
                    new_cost = _total_len(alloc)
                    if new_cost <= budget_car:
                        current_cost = new_cost
                        increased = True
                    else:
                        alloc[idx] -= 1
                        break
            if not increased:
                break

        entrees = []
        payload_parts = []
        served_uris = []

        for i in range(m):
            if alloc[i] <= 0:
                continue
            uri = valid_items[i]["uri"]
            sha = shas[i]
            debut = 0
            fin = alloc[i]
            taille = tailles[i]
            hdr = _header(i, fin)
            part = hdr + contents[i][debut:fin]
            payload_parts.append(part)
            entrees.append({
                "uri": uri,
                "sha256": sha,
                "debut": debut,
                "fin": fin,
                "taille": taille,
            })
            served_uris.append(uri)

        if served_uris:
            with sqlite3.connect(str(self.db_path), timeout=10.0) as conn:
                conn.executemany(
                    "UPDATE context_ledger SET access_count = access_count + 1 WHERE uri = ?",
                    [(u,) for u in served_uris],
                )
                conn.commit()

        manifeste["entrees"] = entrees
        payload = "".join(payload_parts)
        return {
            "payload": payload,
            "manifeste": manifeste,
        }

    def rejouer(self, manifeste: Union[dict[str, Any], list[dict[str, Any]]]) -> str:
        """Rejoue le payload au caractère près à partir du manifeste.

        Lève ValueError si le sha256 d'une source ne correspond plus.
        """
        entrees = manifeste.get("entrees", []) if isinstance(manifeste, dict) else manifeste
        parts = []
        for e in entrees:
            uri = e["uri"]
            expected_sha = e["sha256"]
            actual_sha = self._sha256_du_stocke(uri)
            if actual_sha != expected_sha:
                raise ValueError(
                    f"Source modifiée pour {uri} : sha256 attendu {expected_sha}, obtenu {actual_sha}"
                )
            content = self.resoudre(uri)
            debut = e.get("debut", 0)
            fin = e.get("fin", len(content))
            taille = e.get("taille", len(content))
            hdr = f"[source: {uri} sha256:{expected_sha[:12]} car {debut}-{fin}/{taille}]\n"
            parts.append(hdr + content[debut:fin])
        return "".join(parts)


def observer(
    uri: str,
    essence: str = "",
    racine: Optional[Union[str, Path]] = None,
    task_id: Optional[str] = None,
    session: Optional[str] = None,
    agent: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Indexe un pointeur de contexte sans copie si l'observation est active.

    Fail-silent : n'échoue jamais vers l'appelant.
    """
    try:
        if os.environ.get("LAFORGE_CONTEXT_LEDGER_OBS", "").strip() in ("0", "false", "off", "no"):
            return None
        if racine is None:
            try:
                from nokido_agent.app.forge_db_path import racine_donnees
                racine = racine_donnees()
            except ImportError:
                try:
                    from app.forge_db_path import racine_donnees
                    racine = racine_donnees()
                except ImportError:
                    import forge_db_path
                    racine = forge_db_path.racine_donnees()
        racine_path = Path(racine).resolve()
        db_path = racine_path / "sandbox" / "context_ledger.db"
        # agent_messages:// se resout sur la base M2M dediee (forge_db_path.m2m_path), jamais sur la grosse base :
        # sans elle, aucun pointeur agent_messages:// ne s'indexait (messages_db None -> ValueError avalee).
        try:
            from nokido_agent.app.forge_db_path import m2m_path
        except ImportError:
            try:
                from app.forge_db_path import m2m_path
            except ImportError:
                from forge_db_path import m2m_path
        ledger = ContextLedger(db_path=db_path, racine=racine_path, messages_db=m2m_path())
        m = dict(meta) if isinstance(meta, dict) else {}
        if task_id is not None:
            m["task_id"] = task_id
        if session is not None:
            m["session"] = session
        if agent is not None:
            m["agent"] = agent
        meta_to_pass = m if m else None
        return ledger.indexer(uri=uri, essence=essence, meta=meta_to_pass)
    except Exception as exc:
        logger.debug("ContextLedger observer failed: %s", exc)
        return None


def observer_relecture(uri: str, agent: str, racine: Optional[Union[str, Path]] = None) -> None:
    """Journalise la relecture d'un blob CCR sous sandbox/context_ledger_relectures.jsonl.

    Fail-silent : n'échoue jamais vers l'appelant.
    """
    try:
        if os.environ.get("LAFORGE_CONTEXT_LEDGER_OBS", "").strip() in ("0", "false", "off", "no"):
            return
        if racine is None:
            try:
                from nokido_agent.app.forge_db_path import racine_donnees
                racine = racine_donnees()
            except ImportError:
                try:
                    from app.forge_db_path import racine_donnees
                    racine = racine_donnees()
                except ImportError:
                    import forge_db_path
                    racine = forge_db_path.racine_donnees()
        racine_path = Path(racine).resolve()
        sandbox_dir = racine_path / "sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        relectures_file = sandbox_dir / "context_ledger_relectures.jsonl"
        ligne = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "uri": uri,
            "agent": agent,
        }
        with open(relectures_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("ContextLedger observer_relecture failed: %s", exc)

