#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_golden_rules_ast.py — moteur NATIF des Golden Rules Nokido.

Porte les six invariants de `.semgrep/nokido_golden_rules.yml` en AST + regex
Python purs, sans aucune dependance externe.

Pourquoi : semgrep passe par un coeur natif qui refuse de demarrer sous un
compte de service — « Failed to create system store X509 authenticator:
CertOpenSystemStore returned NULL » — y compris sur `--version`, et le chemin
Python legacy delegue au meme coeur (il ecrit `<ERROR: missing output>`).
Resultat mesure le 2026-08-15 : le gate archi-lint affichait `scanned_files=0`
puis une coche verte (run 31873587600). Un invariant doctrinal ne peut pas
dependre d'un binaire qui ne demarre pas sur la machine qui le verifie.

Usage :
    forge_golden_rules_ast.py [chemin ...]     # defaut : app tools
    forge_golden_rules_ast.py --json           # sortie machine
Sortie : exit 1 si au moins un finding de severite ERROR.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : moteur natif des golden rules (AST)"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import builtins
import ast
import json
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Repertoires jamais analyses : code tiers, archives, caches. Un lint qui
# accuse `site-packages` noie ses vraies trouvailles dans le bruit.
_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "_attic", "node_modules",
              "site-packages", ".semgrep_home", "_archive", "shadow_mutation"}

_RE_SECRET = re.compile(r"(?i)(API_KEY|_SECRET|SECRET_KEY|_TOKEN|PASSWORD)")
# Motif DEDIE a la lecture d'un secret dans l'environnement. Distinct de
# `_RE_SECRET` pour ne pas elargir au passage les autres regles qui s'en
# servent. Il couvre en plus `*_KEY` tout court : `LAFORGE_DB_KEY`,
# `LANGFUSE_PUBLIC_KEY` et `PRIVATE_KEY_*` echappaient a la detection, alors
# que ce sont exactement des secrets (mesure 2026-08-19). `_PATH`/`_DIR`/`_FILE`
# sont exclus : `LAFORGE_DB_PATH` n'est pas un secret, et un garde qui crie sur
# un chemin se fait desarmer. 2026-09-26 : meme raison pour les DUREES (`_S`, `_MS`,
# `_SECONDS`) -- `LAFORGE_KEY_LEDGER_LOCK_S`, un delai de verrou, rompait le cliquet
# (forge_key_rotation 3 -> 4) parce que `_KEY` est accroche n'importe ou dans le nom.
# NR test_golden_secret_env_duree_nr (les vrais secrets restent pris).
_RE_SECRET_ENV = re.compile(
    r"(?i)^(?!.*(?:_PATH|_DIR|_FILE|_S|_MS|_SECONDS)$).*(API_KEY|_SECRET|SECRET_KEY|_TOKEN|PASSWORD|_KEY)")
_RE_EMBED_DB = re.compile(r"(?i)embeddings\.db")
_RE_INSERT_COLS = re.compile(r"(?i)INSERT\s+INTO\s+rag_chunks\s*\(([^)]*)\)")
_RE_LIKE_ON_RAG = re.compile(r"(?i)FROM\s+rag_\w+\b[^;]{0,200}\bLIKE\b")
# INSERT OR IGNORE dans rag_chunks (2026-10-01, decision owner). Le trigger
# `rag_chunks_fts_bi` (BEFORE INSERT) retire l'entree lexicale de l'id existant
# AVANT que l'insertion soit ignoree : un chunk INCHANGE re-vu sort du lexical.
# Mesure : 15 213 chunks actifs de claude_docs absents de rag_chunks_fts, 37
# fichiers ecrivains. Exception EXPLICITE et locale : le marqueur
# `existence-verifiee` dans les lignes qui precedent, la ou l'ecrivain teste
# l'existence par cle primaire avant d'inserer.
_RE_INSERT_IGNORE_RAG = re.compile(r"(?i)INSERT\s+OR\s+IGNORE\s+INTO\s+rag_chunks\b(?!_)")
_MARQUEUR_EXISTENCE = "existence-verifiee"
# Forme SQL sure (2026-10-01) : `... SELECT ?,... WHERE NOT EXISTS (SELECT 1 FROM
# rag_chunks WHERE id = ?)`. Id deja present -> le SELECT ne rend AUCUNE ligne -> aucune
# insertion n'est tentee -> le trigger BEFORE INSERT ne tire pas. Reconnue dans les
# 600 caracteres qui SUIVENT le motif (la meme instruction).
_RE_SANS_EXISTANT = re.compile(
    r"(?i)WHERE\s+NOT\s+EXISTS\s*\(\s*SELECT\s+1\s+FROM\s+rag_chunks\s+WHERE\s+id\s*=")

# ── REGLES APPRISES : la boucle echec -> garde produit des DONNEES ───────────
# Distiller un garde depuis un correctif reel n'a de valeur que si la boucle
# n'ecrit pas de Python dans le scanner : une regle apprise est une ligne JSON
# validee ici, appliquee par des formes closes. Et elle reste plafonnee a
# WARNING tant qu'un humain ne l'a pas `promue` — un garde ne s'attribue pas
# tout seul le pouvoir de fermer la CI.
APPRISES = os.path.join(ROOT, "tests", "nr", "golden_rules_apprises.json")
_FORMES = ("appel_sans_kwarg", "appel_interdit")

_SUBPROCESS_CALLS = {"subprocess.run", "subprocess.Popen", "subprocess.check_output",
                     "subprocess.call", "subprocess.check_call"}
_BARE_PYTHON = {"python", "python3", "python.exe", "python3.exe"}


def _dotted(node: ast.AST) -> str:
    """Reconstitue `a.b.c` depuis un Attribute/Name, sinon chaine vide."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def _literal_str(node: ast.AST) -> str | None:
    """Valeur textuelle d'un litteral, y compris la part constante d'une f-string.

    Une f-string qui interpole le dossier mais code en dur `embeddings.db` viole
    l'invariant autant qu'une chaine simple : ne regarder que `ast.Constant`
    laisserait passer le cas le plus frequent.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return None


def charger_apprises(chemin: str | None = None) -> tuple[list[dict], list[str]]:
    """(regles valides, ids rejetes). Fichier absent = aucune regle, sans bruit."""
    try:
        with open(chemin or APPRISES, encoding="utf-8") as fh:
            brut = json.load(fh).get("regles", [])
    except (OSError, json.JSONDecodeError):
        # muet-ok : l'absence de regles apprises est l'etat NORMAL du depot ;
        # une regle mal formee, elle, est nommee par le second element du tuple.
        return [], []
    valides: list[dict] = []
    rejets: list[str] = []
    for r in brut if isinstance(brut, list) else []:
        rid, forme, cible = r.get("id"), r.get("forme"), r.get("cible")
        if not rid or forme not in _FORMES or not cible:
            rejets.append(str(rid or "<sans id>"))
            continue
        if forme == "appel_sans_kwarg" and not r.get("kwarg"):
            rejets.append(str(rid))
            continue
        sev = r.get("severity", "WARNING")
        if sev not in ("INFO", "WARNING", "ERROR") or (sev == "ERROR" and not r.get("promue")):
            sev = "WARNING"
        valides.append({**r, "severity": sev})
    return valides, rejets


class _GoldenVisitor(ast.NodeVisitor):
    def __init__(self, rel: str, apprises: list[dict] | None = None) -> None:
        self.rel = rel
        self.apprises = apprises or []
        self.findings: list[dict] = []
        # Portees (fonctions) dans lesquelles le COFFRE est interroge. Voir
        # `_repli_apres_coffre` : la regle cloud-secret-from-env interdisait
        # ce que son propre message declare acceptable.
        self._portees_coffre: list[bool] = []

    # ── le repli n'est pas la faute que la regle poursuit ────────────────────
    # Mesure 2026-09-02 : le cliquet a casse sur 5 lectures d'environnement
    # qui etaient TOUTES dans une fonction interrogeant deja le coffre --
    # `load_token()` des hooks, `load_token()` de la passerelle. Or le message
    # de la regle dit lui-meme « le COFFRE est l'autorite [...], l'env n'est
    # qu'un repli » : elle signalait donc exactement le motif qu'elle prescrit.
    #
    # Un garde qui crie sur la forme correcte se fait desarmer -- c'est la
    # raison ecrite plus haut pour laquelle `_PATH`/`_DIR`/`_FILE` sont deja
    # exclus. Ce qui reste POURSUIVI, et c'est l'essentiel : une lecture d'env
    # dans une fonction qui n'interroge JAMAIS le coffre, c'est-a-dire un
    # secret pris a l'environnement comme autorite plutot que comme repli.
    # `resolve` a ete ESSAYE puis RETIRE dans la minute : `Path(...).resolve()`
    # est partout, et l'inclure faisait passer 14 violations au lieu des 5
    # replis reels -- une exemption qui aurait blanchi n'importe quelle
    # fonction manipulant un chemin. Un nom d'appel generique ne peut pas
    # servir de preuve qu'on parle au coffre.
    _COFFRE = ("get_secret", "vault_get", "jeton_pour")

    def _entrer_portee(self, node: ast.AST) -> None:
        appels = {_dotted(n.func) or "" for n in ast.walk(node)
                  if isinstance(n, ast.Call)}
        self._portees_coffre.append(
            any(a.split(".")[-1] in self._COFFRE for a in appels))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._entrer_portee(node)
        self.generic_visit(node)
        self._portees_coffre.pop()

    # `async def` suit exactement le meme chemin : alias plutot que copie --
    # le detecteur de clones avait deja signale les deux corps identiques.
    visit_AsyncFunctionDef = visit_FunctionDef

    def _repli_apres_coffre(self) -> bool:
        """Sommes-nous dans une fonction qui interroge le coffre ?

        Hors de toute fonction (module), la reponse est NON : une lecture au
        niveau module ne peut pas etre un repli, elle EST l'autorite.
        """
        return any(self._portees_coffre)

    def _apprises_sur_appel(self, node: ast.Call, name: str) -> None:
        for r in self.apprises:
            if name != r["cible"]:
                continue
            sev = r.get("severity", "WARNING")   # plafond deja applique au chargement
            if r["forme"] == "appel_interdit":
                self._add(node, r["id"], sev,
                          r.get("message") or f"appel interdit : {name}")
                continue
            fournis = {k.arg for k in node.keywords}
            # `None` = `**kwargs` : le kwarg PEUT etre la. On n'accuse jamais ce
            # qu'on ne peut pas lire (cf. le faux positif de forge_skill_curator).
            if r["kwarg"] in fournis or None in fournis:
                continue
            self._add(node, r["id"], sev,
                      r.get("message") or f"{name} appele sans `{r['kwarg']}`")

    def _add(self, node: ast.AST, rule: str, sev: str, msg: str) -> None:
        self.findings.append({"rule": rule, "severity": sev, "path": self.rel,
                              "line": getattr(node, "lineno", 0), "message": msg})

    # ── laforge-no-anthropic-api-direct (ERROR) ──────────────────────────────
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "anthropic" or alias.name.startswith("anthropic."):
                self._add(node, "laforge-no-anthropic-api-direct", "ERROR",
                          "API Anthropic directe (pay-per-token) : passer par "
                          "claude_cli / claude_agent_sdk via le hub")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if (node.module or "").split(".")[0] == "anthropic":
            self._add(node, "laforge-no-anthropic-api-direct", "ERROR",
                      "API Anthropic directe (pay-per-token) : passer par "
                      "claude_cli / claude_agent_sdk via le hub")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = _dotted(node.func)

        # ── laforge-embeddings-db-literal-path (ERROR) ───────────────────────
        if name.endswith("sqlite3.connect") or name == "connect":
            if node.args:
                txt = _literal_str(node.args[0])
                if txt and _RE_EMBED_DB.search(txt):
                    self._add(node, "laforge-embeddings-db-literal-path", "ERROR",
                              "connexion a embeddings.db par chemin litteral : "
                              "contourne forge_db_path.db_path() (realpath C: -> V:), "
                              "base en lecture seule SILENCIEUSE hors service")

        # ── laforge-no-anthropic-api-direct (ERROR) ──────────────────────────
        if name in ("anthropic.Anthropic", "anthropic.AsyncAnthropic"):
            self._add(node, "laforge-no-anthropic-api-direct", "ERROR",
                      "client Anthropic instancie directement")

        # ── laforge-bare-python-subprocess (WARNING) ─────────────────────────
        if name in _SUBPROCESS_CALLS and node.args:
            argv = node.args[0]
            first = None
            if isinstance(argv, (ast.List, ast.Tuple)) and argv.elts:
                first = _literal_str(argv.elts[0])
            elif isinstance(argv, ast.Constant):
                first = _literal_str(argv)
                first = (first or "").split(" ")[0] or None
            if first and os.path.basename(first).lower() in _BARE_PYTHON:
                self._add(node, "laforge-bare-python-subprocess", "WARNING",
                          "interpreteur `python` ambigu : utiliser "
                          "forge_python_bin.LAFORGE_PYTHON")

        # ── laforge-cloud-secret-from-env (INFO) ─────────────────────────────
        if name in ("os.environ.get", "os.getenv") and node.args:
            key = _literal_str(node.args[0])
            if key and _RE_SECRET_ENV.search(key) and not self._repli_apres_coffre():
                self._add(node, "laforge-cloud-secret-from-env", "ERROR",
                          f"secret `{key}` lu depuis l'environnement : le COFFRE "
                          "est l'autorite (forge_secrets.get_secret / "
                          "forge_machine_vault.vault_get), l'env n'est qu'un repli")

        self._apprises_sur_appel(node, name)
        self.generic_visit(node)

    # ── laforge-cloud-secret-from-env, forme os.environ["X"] (INFO) ──────────
    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _dotted(node.value) == "os.environ":
            key = _literal_str(node.slice)
            if key and _RE_SECRET_ENV.search(key) and not self._repli_apres_coffre():
                self._add(node, "laforge-cloud-secret-from-env", "ERROR",
                          f"secret `{key}` lu depuis l'environnement : le COFFRE "
                          "est l'autorite (forge_secrets.get_secret / "
                          "forge_machine_vault.vault_get), l'env n'est qu'un repli")
        self.generic_visit(node)


def _scan_text(rel: str, src: str) -> list[dict]:
    """Regles textuelles : le SQL vit dans des chaines, l'AST n'y voit rien."""
    out: list[dict] = []
    for m in _RE_INSERT_COLS.finditer(src):
        cols = m.group(1)
        if re.search(r"\bid\b", cols, re.I):
            continue
        # Liste de colonnes INTERPOLEE ({','.join(keys)}) : indecidable
        # statiquement. Verification du 2026-08-15 : forge_skill_curator.py:273
        # construit ses colonnes ainsi ET gere ON CONFLICT(id) -- l'accuser etait
        # un faux positif. On n'accuse que ce qu'on peut lire.
        if "{" in cols or "%" in cols or "+" in cols:
            continue
        out.append({"rule": "laforge-insert-rag-chunks-no-id", "severity": "ERROR",
                    "path": rel, "line": src.count("\n", 0, m.start()) + 1,
                    "message": "INSERT INTO rag_chunks sans colonne `id` explicite "
                               "(TEXT PRIMARY KEY, sha256(source+text)[:16])"})
    for m in _RE_INSERT_IGNORE_RAG.finditer(src):
        if _MARQUEUR_EXISTENCE in src[max(0, m.start() - 600):m.start()]:
            continue
        if _RE_SANS_EXISTANT.search(src[m.end():m.end() + 600]):
            continue
        out.append({"rule": "laforge-insert-or-ignore-rag-chunks", "severity": "ERROR",
                    "path": rel, "line": src.count("\n", 0, m.start()) + 1,
                    "message": "insertion OR IGNORE vers rag_chunks : le trigger rag_chunks_fts_bi "
                               "desindexe l'id existant AVANT que l'insertion soit ignoree -- "
                               "tester l'existence par cle primaire (marqueur "
                               "`existence-verifiee`) ou ecrire par forge_db_path.ecrire_chunk"})
    for m in _RE_LIKE_ON_RAG.finditer(src):
        out.append({"rule": "laforge-raw-sql-like-on-rag", "severity": "WARNING",
                    "path": rel, "line": src.count("\n", 0, m.start()) + 1,
                    "message": "LIKE brut sur une table rag_* : utiliser rag_fts "
                               "(FTS5/BM25) ou RAGEngine.search"})
    return out


def scan_file(path: str, apprises: list[dict] | None = None) -> list[dict]:
    try:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        # Cible sur un AUTRE volume (le RAG vit sur V:) : relpath leve
        # « path is on mount 'D:', start on mount 'C:' ». Le chemin absolu reste
        # une identite valable ; planter ici rendrait l'outil inutilisable hors C:.
        rel = os.path.abspath(path).replace("\\", "/")
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
    except OSError as exc:
        return [{"rule": "lecture", "severity": "INFO", "path": rel, "line": 0,
                 "message": f"illisible : {exc}"}]
    return scan_source(rel, src, apprises)


def scan_source(rel: str, src: str, apprises: list[dict] | None = None) -> list[dict]:
    """Scan d'un TEXTE deja en memoire.

    Le distillateur de regles compare une version git a l'autre : lui imposer un
    fichier temporaire violerait la consigne « zero fichier temporaire » et
    ferait dependre le verdict d'un chemin disque.
    """
    findings = _scan_text(rel, src)
    try:
        tree = ast.parse(src, filename=rel)
    except SyntaxError as exc:
        # Un fichier impossible a parser n'est pas "conforme" : il est NON VU.
        findings.append({"rule": "parse", "severity": "WARNING", "path": rel,
                         "line": exc.lineno or 0,
                         "message": f"non analyse (SyntaxError: {exc.msg})"})
        return findings
    v = _GoldenVisitor(rel, apprises)
    v.visit(tree)
    return (findings + v.findings + _scan_noms_non_lies(rel, tree)
            + _scan_effet_de_bord_import(rel, tree))


def _scan_noms_non_lies(rel: str, tree: ast.AST) -> list[dict]:
    """Appels a un nom qui n'est lie NULLE PART dans le fichier.

    POURQUOI CETTE REGLE EXISTE (incident 2026-08-19). Le hub est tombe et n'a
    plus jamais redemarre : `tools/nokido_hub.py:160` appelait `_gs(...)` alors
    que l'import aliase qui lie ce nom vit ligne 166 -- SIX lignes plus bas.
    Un `NameError` au chargement du module, donc un crash loop de 2 s, donc tous
    les outils MCP hors service.

    Ce que les gardes existants ne pouvaient PAS voir :
      * `ast.parse` reussit -- un fichier qui PARSE peut appeler n'importe quoi ;
      * flake8/ruff en mode critique (E9,F63,F7) ne portent pas sur F821 ;
      * les 4853 tests passaient : aucun ne charge le point d'entree du hub ;
      * le service TOURNAIT depuis des heures avec son ancien code en memoire.
    Un service qui tourne ne prouve pas que son code demarre.

    Deux migrations `get_secret` sont tombees dans le meme piege de prefixe --
    la mienne (`_os.environ.get` -> `_get_secret`) et une anterieure, `f4707013`
    (`_gs` -> `__gs`, sur les chemins Groq/XAI/DeepSeek). Ce n'est donc pas un
    accident isole : c'est un motif qui se REPETE, ce qui est exactement ce qu'un
    cliquet doit arreter.

    PRUDENCE, pour ne pas se faire desarmer :
      * les builtins sont lies d'office ;
      * un fichier qui fait `from x import *` est SAUTE -- ses noms sont
        indecidables statiquement, et accuser au hasard tuerait la regle ;
      * `global`/`nonlocal`, arguments, alias d'exception et cibles
        d'affectation comptent comme des liaisons.
    Mesure a l'introduction : 17 fichiers, 66 noms sur 2326 fichiers scannes --
    dette bornee, que le socle gele et dont il interdit la croissance.
    """
    lies = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == "*":
                    return []  # indecidable : on n'accuse pas ce qu'on ne peut pas lire
                lies.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            lies |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lies.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            lies.add(n.id)
        elif isinstance(n, ast.arg):
            lies.add(n.arg)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            lies |= set(n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            lies.add(n.name)

    out: list[dict] = []
    vus: set[str] = set()
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)):
            continue
        nom = n.func.id
        if nom in lies or nom in vus:
            continue
        vus.add(nom)
        out.append({"rule": "laforge-appel-nom-non-lie", "severity": "ERROR",
                    "path": rel, "line": getattr(n, "lineno", 0),
                    "message": f"`{nom}()` appele mais lie NULLE PART dans ce "
                               "fichier : NameError a l'execution. Verifier que "
                               "l'import precede l'USAGE, pas seulement qu'il existe"})
    return (out + _scan_chemin_erreur_non_lie(rel, tree, lies)
            + _scan_usage_avant_liaison(rel, tree) + _scan_global_incomplet(rel, tree))


def _racine_attribut(node: ast.AST) -> str | None:
    """`a.b.c()` -> `a`. Le nom qu'il faut avoir lie pour que l'appel existe."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _scan_chemin_erreur_non_lie(rel: str, tree: ast.AST, lies: set) -> list[dict]:
    """Un handler `except` qui appelle un nom non lie : le garde devient la panne.

    POURQUOI CETTE REGLE EXISTE (2026-09-05, trois occurrences le meme jour). Un
    gestionnaire d'erreur ecrit pour CONTENIR une panne en produisait une nouvelle :

        except Exception as e:
            logger.debug(...)      # `logger` n'existe pas dans ce module

    Le bloc censé garantir « un journal qui casse ne casse pas la regulation » la
    cassait. Deux fois attrape par un NR et un test, la troisieme par cette regle
    -- dans `forge_resource_manager.get_active_intents`, ou le handler aurait leve
    le jour ou l'arbitre des piliers devient indisponible. C'est le pire endroit
    possible : un chemin qui ne s'execute QUE lorsque quelque chose va deja mal.

    Pourquoi `laforge-appel-nom-non-lie` ne les voyait pas : elle ne regarde que
    `foo()` (un `ast.Call` sur un `ast.Name`). Les trois cas etaient `foo.bar()`,
    donc un `ast.Attribute` -- meme NameError, hors de sa portee.

    PORTEE VOLONTAIREMENT ETROITE : les chemins d'erreur, et eux seuls. Mesure du
    jour, sur 2409 fichiers : la meme detection appliquee a TOUT le code sort 90
    usages dont plusieurs faux positifs (des modules de handlers charges dans un
    espace de noms injecte, ou `forge_hub_handlers` tient 832 lignes pour un seul
    import). Restreinte aux `except`, elle sort 16 usages sur 8 fichiers -- assez
    peu pour etre instruite, et centree sur ce que personne ne teste. Un garde qui
    crie a faux se fait desarmer ; celui-ci vise ce qui n'a jamais de couverture.
    """
    out: list[dict] = []
    vus: set[tuple] = set()
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler):
            continue
        for n in ast.walk(handler):
            if not isinstance(n, ast.Call):
                continue
            nom = (_racine_attribut(n.func) if isinstance(n.func, ast.Attribute)
                   else n.func.id if isinstance(n.func, ast.Name) else None)
            if not nom or nom in lies:
                continue
            clef = (nom, getattr(n, "lineno", 0))
            if clef in vus:
                continue
            vus.add(clef)
            out.append({"rule": "laforge-chemin-erreur-nom-non-lie",
                        "severity": "ERROR", "path": rel,
                        "line": getattr(n, "lineno", 0),
                        "message": f"`{nom}` n'est lie NULLE PART mais est appele "
                                   "dans un chemin d'erreur : le handler levera un "
                                   "NameError au moment ou il devait contenir la "
                                   "panne. Importer localement dans le handler"})
    return out


def _flux_module(noeuds):
    """Noeuds executes AU CHARGEMENT du module, dans l'ordre.

    On descend dans `if`/`try`/`with`/`for`/`while` de niveau module, mais JAMAIS
    dans un `def`/`class` : leur corps ne s'execute pas a l'import, donc un nom
    lie plus bas y sera parfaitement resolu le jour de l'appel.
    """
    for n in noeuds:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        yield n
        for champ in ("body", "orelse", "finalbody", "handlers"):
            sous = getattr(n, champ, None)
            if isinstance(sous, list):
                yield from _flux_module(sous)


def _appels_immediats(noeud):
    """Sous-noeuds evalues TOUT DE SUITE, sans entrer dans un corps differe.

    ⚠️ Un `lambda` n'execute rien a sa definition. `forge_task_router.py:57`
    ecrit `lambda: not _ping(...)` alors que `_ping` est defini ligne 180 : le
    nom sera parfaitement resolu le jour ou le lambda est appele. Descendre
    dedans produisait un FAUX POSITIF -- et un garde qui accuse du code correct
    se fait desarmer dans la semaine. Meme raison pour `def`/`class`.
    """
    for enfant in ast.iter_child_nodes(noeud):
        if isinstance(enfant, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            continue
        yield enfant
        yield from _appels_immediats(enfant)


_SCOPES_PROPRES = (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                   ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def _flux_fonction(noeud):
    """Sous-noeuds du MEME scope : on ne descend pas dans un scope imbrique
    (def/lambda/class/comprehension ont chacun leur espace de noms)."""
    for enfant in ast.iter_child_nodes(noeud):
        if isinstance(enfant, _SCOPES_PROPRES):
            continue
        yield enfant
        yield from _flux_fonction(enfant)


def _noms_niveau_module(tree: ast.AST) -> set[str]:
    """Noms LIES au niveau module (ceux qu'un `global` peut viser)."""
    noms: set[str] = set()
    for n in getattr(tree, "body", []):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            noms.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for s in ast.walk(t):
                    if isinstance(s, ast.Name) and isinstance(s.ctx, ast.Store):
                        noms.add(s.id)
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            noms.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                noms.add((a.asname or a.name).split(".")[0])
    return noms


def _params_fonction(fn) -> set[str]:
    a = fn.args
    noms = {x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
    if a.vararg:
        noms.add(a.vararg.arg)
    if a.kwarg:
        noms.add(a.kwarg.arg)
    return noms


# Appels qui OUVRENT un fichier en ecriture. `basicConfig` n'y est que sous
# condition : sans `filename` ni `handlers`, il ne configure qu'une console et
# ne reclame aucun privilege.
_OUVRE_JOURNAL = {"FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler",
                  "WatchedFileHandler"}


def _scan_effet_de_bord_import(rel: str, tree: ast.AST) -> list[dict]:
    """Journal ouvert AU CHARGEMENT du module -- donc privilege exige a l'import.

    MESURE 2026-09-16. `tools/forge_trace_replay.py` appelait
    `logging.basicConfig(handlers=[RotatingFileHandler(...)])` au niveau module.
    Le fichier visé est LISIBLE mais NON inscriptible par les comptes de service
    (verifie sous LaForgeSbxOffline ET LaForgeSbxOnline) : le module etait donc
    INIMPORTABLE, et son propre test de chargement mesurait les ACL du compte au
    lieu du code. Un import DEFINIT des capacites ; il ne reclame pas de droit.

    PORTEE, et c'est pourquoi la severite est WARNING : 28 modules de tools/ et
    6 de app/ ouvrent un handler fichier. Une regle ERROR des son premier
    passage rougirait 34 fois et se ferait desarmer -- on observe d'abord, on
    promeut sur mesure du bruit.

    CE QUI S'EXECUTE, JAMAIS CE QUI EST DEFINI : `_flux_module` descend dans les
    `if`/`try`/`with` de niveau module mais jamais dans un `def`, et
    `_appels_immediats` s'arrete a la meme frontiere. C'est exactement la
    distinction qu'un premier jet de ce garde avait ratee -- il condamnait la
    forme CORRIGEE, celle qui met l'ouverture dans une fonction.
    """
    out: list[dict] = []
    for noeud in _flux_module(getattr(tree, "body", [])):
        for appel in _appels_immediats(noeud):
            if not isinstance(appel, ast.Call):
                continue
            nom = getattr(appel.func, "attr", None) or getattr(appel.func, "id", None)
            if nom in _OUVRE_JOURNAL:
                quoi = nom
            elif nom == "basicConfig" and any(
                    kw.arg in ("filename", "handlers") for kw in appel.keywords):
                quoi = "basicConfig(filename=/handlers=)"
            else:
                continue
            out.append({
                "rule": "laforge-effet-de-bord-import", "severity": "WARNING",
                "path": rel, "line": getattr(appel, "lineno", 0),
                "message": (
                    "`%s` s'execute AU CHARGEMENT du module : l'import exige alors "
                    "un droit d'ecriture, et echoue sous tout compte qui ne l'a pas "
                    "(mesure 2026-09-16 : PermissionError sous deux comptes de "
                    "service). Deplacer la configuration dans une fonction appelee "
                    "par le point d'entree -- un import DEFINIT, il ne reclame pas."
                    % quoi)})
    return out


def _scan_global_incomplet(rel: str, tree: ast.AST) -> list[dict]:
    """Nom GLOBAL assigne dans une fonction SANS `global`, et lu avant sa liaison.

    Angle mort mesure le 2026-08-19 : `forge_llama_keeper` assignait
    `_ZERO_CONNS_DEPUIS` dans sa fonction de decision, mais son `global` ne
    declarait que `_LAST_UNLOAD_TS`. Python rend alors le nom LOCAL dans toute la
    fonction ; sa lecture plus haut leve `UnboundLocalError` a CHAQUE tick. Le
    keeper crashait en boucle -- et `ast.parse`, `compile`, `flake8 F82` passaient
    tous : seul l'IMPORT/execution le revelait. `laforge-usage-avant-liaison` ne
    le voyait pas non plus (il ne porte que le niveau module).

    On ne flague QUE le cas CERTAIN (sinon un garde qui accuse du code correct se
    fait desarmer) : le nom existe au niveau module, il est assigne dans la
    fonction sans `global`/`nonlocal`, il n'est pas un parametre, et
      - soit une LECTURE apparait avant toute liaison (UnboundLocalError garanti),
      - soit un `+=`/augassign est la premiere liaison (il lit avant d'ecrire).
    Le shadowing legitime (assignation AVANT lecture) n'est jamais flague.
    """
    mod = _noms_niveau_module(tree)
    out: list[dict] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        gdecl: set[str] = set()
        store: dict[str, int] = {}
        load: dict[str, int] = {}
        aug: dict[str, int] = {}
        noeuds: list = []
        for stmt in fn.body:
            noeuds.append(stmt)
            noeuds.extend(_flux_fonction(stmt))
        aug_tgt = {id(n.target) for n in noeuds
                   if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name)}
        for node in noeuds:
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                gdecl.update(node.names)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                aug.setdefault(node.target.id, node.lineno)
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store) and id(node) not in aug_tgt:
                    store.setdefault(node.id, node.lineno)
                elif isinstance(node.ctx, ast.Load):
                    load.setdefault(node.id, node.lineno)
        params = _params_fonction(fn)
        for nom in set(store) | set(aug):
            if nom in gdecl or nom in params or nom not in mod:
                continue
            s, a_, l = store.get(nom), aug.get(nom), load.get(nom)
            premiere = min(x for x in (s, a_) if x is not None)
            if a_ is not None and a_ == premiere and (s is None or s > a_):
                out.append({"rule": "laforge-global-incomplet", "severity": "ERROR",
                            "path": rel, "line": a_,
                            "message": f"`{nom}` est un global assigne (`+=`) ligne "
                                       f"{a_} sans `global {nom}` : il devient LOCAL, "
                                       "et `+=` lit avant d'ecrire -> UnboundLocalError"})
            elif l is not None and l < premiere:
                out.append({"rule": "laforge-global-incomplet", "severity": "ERROR",
                            "path": rel, "line": l,
                            "message": f"`{nom}` (global) est LU ligne {l} mais assigne "
                                       f"ligne {premiere} sans `global {nom}` : il devient "
                                       "LOCAL -> UnboundLocalError au runtime. Ajouter "
                                       f"`{nom}` au `global` de la fonction"})
    return out


def _scan_usage_avant_liaison(rel: str, tree: ast.AST) -> list[dict]:
    """Nom appele AU CHARGEMENT avant la ligne qui le lie.

    C'est la forme EXACTE de l'incident du 2026-08-19 : `nokido_hub.py:160`
    appelait `_gs(...)`, et l'import qui lie ce nom vivait ligne 166. Le nom
    EXISTE dans le fichier -- la regle « lie nulle part » ne le voit donc pas.
    Ce n'est pas un probleme d'existence, c'est un probleme d'ORDRE : au
    chargement, la ligne 160 s'execute quand la 166 n'a pas encore eu lieu.
    """
    lignes: dict[str, int] = {}
    for n in ast.walk(tree):
        cible = None
        if isinstance(n, ast.ImportFrom) and not any(a.name == "*" for a in n.names):
            cible = [a.asname or a.name for a in n.names]
        elif isinstance(n, ast.Import):
            cible = [(a.asname or a.name).split(".")[0] for a in n.names]
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            cible = [n.name]
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            cible = [n.id]
        for nom in cible or []:
            l = getattr(n, "lineno", 0)
            if nom not in lignes or l < lignes[nom]:
                lignes[nom] = l

    out: list[dict] = []
    vus: set[str] = set()
    for n in _flux_module(getattr(tree, "body", [])):
        for sous in _appels_immediats(n):
            if not (isinstance(sous, ast.Call) and isinstance(sous.func, ast.Name)):
                continue
            nom = sous.func.id
            liee = lignes.get(nom)
            appel = getattr(sous, "lineno", 0)
            if liee is None or liee <= appel or nom in vus:
                continue
            vus.add(nom)
            out.append({"rule": "laforge-usage-avant-liaison", "severity": "ERROR",
                        "path": rel, "line": appel,
                        "message": f"`{nom}()` appele ligne {appel} au CHARGEMENT du "
                                   f"module, mais lie seulement ligne {liee} : "
                                   "NameError au demarrage. Le nom existe, l'ordre "
                                   "est faux -- l'import doit preceder son USAGE"})
    return out


# Dossiers que `os.walk` n'a pas pu ouvrir pendant le dernier `collect` : il les
# SAUTE en silence par defaut. Rempli par `collect`, lu par `main` (2026-10-01).
_MURS: list[str] = []


def _noter_mur(exc: OSError) -> None:
    _MURS.append(str(exc))


def collect(paths: list[str]) -> list[str]:
    files: list[str] = []
    _MURS.clear()
    for p in paths:
        target = p if os.path.isabs(p) else os.path.join(ROOT, p)
        if os.path.isfile(target):
            files.append(target)
            continue
        # 3e argument positionnel de os.walk : le rappel d'erreur (sans lui, un
        # dossier illisible disparait du scan sans rien dire).
        for dirpath, dirnames, filenames in os.walk(target, True, _noter_mur):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            files += [os.path.join(dirpath, f) for f in filenames
                      if f.endswith(".py") and not _scratch(f)]
    return files


def _scratch(nom: str) -> bool:
    """Fichier de travail jetable, hors produit.

    `tools/_*.py` et `tools/tmp_*` sont deja exclus du depot par .gitignore :
    les linter revient a mesurer du code que personne ne livre, et c'est la
    moitie des chemins litteraux vers embeddings.db releves au premier passage.
    """
    return nom.startswith(("_", "tmp_")) and nom != "__init__.py"


SOCLE = os.path.join(ROOT, "tests", "nr", "golden_rules_socle.json")

# Une entree gelee depuis plus longtemps que ce seuil n'est plus une dette qu'on
# a l'intention de payer : c'est soit un faux positif admis, soit une regle que
# personne n'applique. Dans les deux cas la regle ment sur ce fichier, et une
# regle qui ment finit par faire desarmer le gate entier. On ne la retire pas
# d'office — on la NOMME, parce qu'aucun compteur ne le faisait.
_APOPTOSE_JOURS = 30


def _cle(f: dict) -> str:
    """Identite d'une violation, INDEPENDANTE de son numero de ligne.

    Geler `path:line` ferait crier le cliquet a chaque ligne inseree au-dessus :
    un garde qui hurle sur un ajout de commentaire finit desarme.
    """
    return f"{f['rule']}|{f['path']}"


def _compter(findings: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for f in findings:
        if f["severity"] == "ERROR":
            out[_cle(f)] = out.get(_cle(f), 0) + 1
    return out


def _dates_de_gel(anciennes: dict, courant: dict, jour: str) -> dict:
    """Date de PREMIER gel par cle : une cle deja connue garde la sienne.

    Sans cette memoire, chaque `--ecrire-socle` remettrait les compteurs a zero
    et une dette de six mois se relirait comme neuve.
    """
    return {cle: anciennes.get(cle, jour) for cle in courant}


def _rapport_apoptose(gele: dict, depuis: dict, jour: str) -> None:
    sans_date = [k for k in gele if k not in depuis]
    illisibles: list[str] = []
    ages: dict[str, int] = {}          # calcules UNE fois : le recompte par regle
    for cle in gele:                   # relisait les dates et crashait sur l'une d'elles
        debut = depuis.get(cle)
        if debut is None:
            continue
        try:
            ages[cle] = (date.fromisoformat(jour) - date.fromisoformat(debut)).days
        except (TypeError, ValueError):
            illisibles.append(cle)
    if sans_date:
        print(f"[golden_ast] {len(sans_date)} entree(s) du socle sans date de gel "
              f"— regenerer avec --ecrire-socle pour armer le compteur d'apoptose")
    if illisibles:
        # Une date corrompue avalee en silence rend le compteur muet sans le dire :
        # exactement l'anergie que ce rapport est cense combattre.
        print(f"[golden_ast] {len(illisibles)} date(s) de gel illisible(s) dans le socle "
              f"— regenerer avec --ecrire-socle")
    vieux: dict[str, int] = {}
    for cle, age in ages.items():
        if age > _APOPTOSE_JOURS:
            regle = cle.split("|", 1)[0]
            vieux[regle] = max(vieux.get(regle, 0), age)
    for regle, age in sorted(vieux.items()):
        prefixe = f"{regle}|"
        total = sum(1 for k in gele if k.startswith(prefixe))
        anciens = sum(1 for k, a in ages.items() if k.startswith(prefixe) and a > _APOPTOSE_JOURS)
        print(f"[golden_ast] apoptose ? {regle} : {anciens}/{total} entree(s) gelee(s) "
              f"depuis plus de {_APOPTOSE_JOURS} j (jusqu'a {age} j) — dette assumee, "
              f"faux positif, ou regle inapplicable : trancher, ne pas laisser dormir")


def _verdict_socle(findings: list[dict]) -> int:
    """0 si la dette n'a pas grossi, 1 sinon. La dette existante ne bloque pas.

    Onze violations ERROR existaient au 2026-08-15 ; exiger zero aurait ferme la
    CI le jour meme, donc le gate aurait ete desarme dans l'heure. Le cliquet
    interdit la NOUVEAUTE, ce qui est la seule promesse tenable.
    """
    courant = _compter(findings)
    try:
        with open(SOCLE, encoding="utf-8") as fh:
            gele = json.load(fh).get("par_regle_et_fichier", {})
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ABORT: socle illisible ({exc}) — regenerer avec --ecrire-socle")
        return 3
    try:
        with open(SOCLE, encoding="utf-8") as fh:
            depuis = json.load(fh).get("depuis_par_cle", {})
    except (OSError, json.JSONDecodeError):
        # muet-ok : l'absence de dates est ANNONCEE par _rapport_apoptose
        # (« entree(s) du socle sans date de gel »), et le socle lui-meme vient
        # d'etre lu plus haut — une seconde plainte ici ferait du bruit double.
        depuis = {}
    _rapport_apoptose(gele, depuis, date.today().isoformat())
    neuf = {k: v for k, v in courant.items() if v > gele.get(k, 0)}
    if not neuf:
        recul = sum(gele.values()) - sum(courant.values())
        print(f"[golden_ast] cliquet OK — aucune nouvelle violation ERROR"
              + (f", {recul} de moins qu'au socle" if recul > 0 else ""))
        return 0
    print(f"[golden_ast] CLIQUET ROMPU — {len(neuf)} violation(s) ERROR nouvelle(s) :")
    for k, v in sorted(neuf.items()):
        rule, path = k.split("|", 1)
        print(f"  + {rule}  {path}  ({gele.get(k, 0)} -> {v})")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Golden Rules Nokido — moteur AST natif")
    ap.add_argument("paths", nargs="*", default=None)
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--max-print", type=int, default=40)
    ap.add_argument("--socle", action="store_true",
                    help="cliquet : echoue seulement sur une violation ERROR NOUVELLE")
    ap.add_argument("--ecrire-socle", action="store_true",
                    help="fige l'etat courant comme reference du cliquet")
    args = ap.parse_args()

    files = collect(args.paths or ["app", "tools"])
    apprises, rejets = charger_apprises()
    findings: list[dict] = []
    for f in files:
        findings += scan_file(f, apprises)

    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    if args.json:
        print(json.dumps({"scanned_files": len(files), "findings": findings,
                          "by_severity": by_sev}, ensure_ascii=False))
        return 1 if by_sev.get("ERROR") else 0

    print(f"[golden_ast] scanned_files={len(files)}")
    if apprises:
        print(f"[golden_ast] {len(apprises)} regle(s) apprise(s) active(s)")
    if rejets:
        print(f"[golden_ast] {len(rejets)} regle(s) apprise(s) REJETEE(S) (forme ou "
              f"champ invalide) : {', '.join(rejets[:5])}")
    # Zero fichier lu n'est jamais un succes — c'est le defaut qui a rendu le
    # gate semgrep aveugle pendant des semaines.
    if not files:
        print("ABORT: 0 fichier analyse")
        return 3

    # NON LU n'est pas CONFORME (2026-10-01). Un fichier illisible rend un INFO
    # « lecture » au lieu de ses ERROR, et un dossier que `os.walk` n'ouvre pas
    # disparait du scan : le cliquet compterait les deux comme un RECUL. Enquete du
    # jour sur les 33 entrees en baisse : toutes corrigees dans le code (regle
    # actuelle rejouee sur la version du gel), 0 illisible -- mais rien ne
    # l'aurait dit dans le cas contraire.
    non_lus = sorted({f["path"] for f in findings if f["rule"] == "lecture"})
    if non_lus or _MURS:
        print(f"[golden_ast] NON LU : {len(non_lus)} fichier(s) illisible(s) "
              f"{non_lus[:5]}, {len(_MURS)} dossier(s) non ouvert(s) {_MURS[:3]} — "
              "leurs violations ne sont PAS comptees")

    if args.ecrire_socle:
        if non_lus or _MURS:
            print("ABORT: socle NON ecrit -- il gelerait comme un recul ce qui n'a pas ete lu")
            return 3
        os.makedirs(os.path.dirname(SOCLE), exist_ok=True)
        try:
            with open(SOCLE, encoding="utf-8") as fh:
                anciennes = json.load(fh).get("depuis_par_cle", {})
        except (OSError, json.JSONDecodeError):
            anciennes = {}
        courant = _compter(findings)
        with open(SOCLE, "w", encoding="utf-8") as fh:
            json.dump({"genere_par": "tools/forge_golden_rules_ast.py --ecrire-socle",
                       "fichiers_analyses": len(files),
                       "par_regle_et_fichier": courant,
                       "depuis_par_cle": _dates_de_gel(anciennes, courant,
                                                       date.today().isoformat())},
                      fh, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"[golden_ast] socle ecrit : {os.path.relpath(SOCLE, ROOT)} "
              f"({sum(_compter(findings).values())} ERROR geles)")
        return 0

    if args.socle:
        print(f"[golden_ast] {len(findings)} finding(s) : {by_sev or '{}'}")
        return _verdict_socle(findings)
    print(f"[golden_ast] {len(findings)} finding(s) : {by_sev or '{}'}")
    order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
    for f in sorted(findings, key=lambda x: (order.get(x["severity"], 9), x["path"]))[:args.max_print]:
        print(f"  [{f['severity']}] {f['rule']}  {f['path']}:{f['line']}")
    reste = len(findings) - args.max_print
    if reste > 0:
        print(f"  ... et {reste} de plus (--max-print pour tout voir)")
    return 1 if by_sev.get("ERROR") else 0


if __name__ == "__main__":
    raise SystemExit(main())
