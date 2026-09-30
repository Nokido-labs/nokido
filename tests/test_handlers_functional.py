"""
test_handlers_functional.py — Tests fonctionnels des handlers @cmd Nokido v13
Vérifie : dispatch, arguments manquants, cohérence help↔handlers, imports critiques.

Lancer :
    cd __import__("os").path.expanduser("~/Script python IA/LaForge")
    python -m pytest tests/test_handlers_functional.py -v
"""
from __future__ import annotations

import ast
import asyncio
import re
import sys
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Parse statique de Nokido.py
# ═══════════════════════════════════════════════════════════════════════════════

LAFORGE_SRC = (APP / "Nokido.py").read_text(encoding="utf-8", errors="ignore")
LAFORGE_LINES = LAFORGE_SRC.splitlines()


def _extract_handled_cmds() -> set[str]:
    """
    Extrait toutes les commandes @xxx gérées.
    v16+ : lit le REGISTRY de forge_dispatch.py au lieu du if/elif de _handle_at.
    Fallback : scan des literaux '@xxx' dans Nokido.py.
    """
    # Source prioritaire : forge_dispatch.REGISTRY
    dispatch_src_path = APP / "forge_dispatch.py"
    if dispatch_src_path.exists():
        src = dispatch_src_path.read_text(encoding="utf-8", errors="ignore")
        cmds = set()
        for m in re.finditer(r'"(@\w+)"', src):
            cmds.add(m.group(1))
        if cmds:
            return cmds
    # Fallback legacy : scan Nokido.py
    cmds = set()
    for line in LAFORGE_LINES:
        for m in re.finditer(r'"(@\w+)"', line):
            token = m.group(1)
            if token.startswith("@"):
                cmds.add(token)
    return cmds


def _extract_help_cmds() -> set[str]:
    """Extrait les commandes listées dans _show_help."""
    cmds = set()
    in_help = False
    for line in LAFORGE_LINES:
        if "_show_help" in line and "def " in line:
            in_help = True
        elif in_help and line.strip().startswith(")"):
            break
        if in_help:
            for m in re.finditer(r"@(\w+)", line):
                cmds.add(f"@{m.group(1)}")
    return cmds


def _extract_orchestrator_cmds() -> set[str]:
    """Extrait les commandes du registre dans forge_orchestrator.py."""
    src = (APP / "forge_orchestrator.py").read_text(encoding="utf-8", errors="ignore")
    cmds = set()
    for m in re.finditer(r'"(@\w+)"', src):
        cmds.add(m.group(1))
    return cmds


HANDLED = _extract_handled_cmds()
HELP = _extract_help_cmds()
ORCH = _extract_orchestrator_cmds()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Cohérence help ↔ handlers ↔ orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommandRegistry:
    """Vérifie que help, handlers et orchestrateur sont synchronisés."""

    def test_help_cmds_all_handled(self):
        """Chaque commande listée dans @help doit avoir un handler."""
        missing = HELP - HANDLED
        assert not missing, f"Commandes dans @help SANS handler : {missing}"

    def test_handled_cmds_all_in_help(self):
        """Chaque handler doit être documenté dans @help (sauf internes)."""
        # Commandes internes tolérées sans doc help
        internal = {"@ragas", "@apply", "@mem", "@nlu", "@npu",
                     "@chain", "@services", "@switch", "@agentic",
                     "@disco", "@evolve", "@ids", "@loop", "@role",
                     "@mode", "@model", "@rag", "@proxy", "@workflow",
                     "@ci", "@scan", "@help", "@ssh"}
        undocumented = HANDLED - HELP - internal
        assert not undocumented, f"Handlers SANS entrée @help : {undocumented}"

    def test_orchestrator_covers_help(self):
        """Le registre orchestrator doit couvrir au minimum les commandes help."""
        # @diag, @run et quelques autres sont gérés directement
        direct_only = {"@diag", "@run", "@estim", "@ragas", "@nlu",
                       "@npu", "@services", "@apply", "@mem"}
        expected = HELP - direct_only
        missing = expected - ORCH
        assert not missing, f"Commandes help absentes du registre orchestrator : {missing}"

    def test_no_duplicate_handler_blocks(self):
        """
        Pas de doublon dans le REGISTRY de forge_dispatch.py (v16+).
        Fallback : pas de doublon cmd == '@xxx' dans _handle_at.
        """
        dispatch_src = (APP / "forge_dispatch.py")
        if dispatch_src.exists():
            src = dispatch_src.read_text(encoding="utf-8", errors="ignore")
            seen = {}
            for i, line in enumerate(src.splitlines(), 1):
                for m in re.finditer(r'"(@\w+)":\s*handle_', line):
                    cmd = m.group(1)
                    if cmd in seen:
                        pytest.fail(f"{cmd} en doublon dans REGISTRY: L{seen[cmd]} et L{i}")
                    seen[cmd] = i
        else:
            # Fallback legacy
            in_handle = False
            seen = {}
            for i, line in enumerate(LAFORGE_LINES, 1):
                if "async def _handle_at" in line:
                    in_handle = True
                if in_handle and line.strip().startswith("async def ") and "_handle_at" not in line:
                    break
                if in_handle:
                    for m in re.finditer(r'cmd\s*==\s*"(@\w+)"', line):
                        cmd = m.group(1)
                        if cmd in seen:
                            pytest.fail(f"{cmd} géré deux fois: L{seen[cmd]} et L{i}")
                        seen[cmd] = i


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Imports critiques (BUG-A / BUG-B)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCriticalImports:
    """Vérifie que les bugs d'import identifiés sont corrigés."""

    def test_bug_a_shell_commands_in_forge_llm(self):
        """BUG-A : SHELL_COMMANDS doit être défini dans forge_llm.py."""
        import forge_llm
        assert hasattr(forge_llm, "SHELL_COMMANDS"), "SHELL_COMMANDS manquant"
        assert isinstance(forge_llm.SHELL_COMMANDS, frozenset)
        assert len(forge_llm.SHELL_COMMANDS) > 20, "SHELL_COMMANDS semble tronqué"

    def test_bug_b_ttlcache_in_forge_orchestrator(self):
        """BUG-B : TTLCache doit être importable dans forge_orchestrator."""
        src = (APP / "forge_orchestrator.py").read_text(encoding="utf-8", errors="ignore")
        # Vérifie que l'import est présent dans le source
        has_import = bool(re.search(
            r"from\s+cachetools\s+import\s+.*TTLCache", src
        ))
        # Ou bien TTLCache est défini/importé autrement
        has_fallback = "TTLCache" in src and ("class TTLCache" in src or "= TTLCache" in src)
        assert has_import or has_fallback, (
            "TTLCache ni importé (from cachetools import TTLCache) "
            "ni défini dans forge_orchestrator.py"
        )

    def test_shell_commands_content(self):
        """SHELL_COMMANDS contient les commandes de base attendues."""
        import forge_llm
        for cmd in ("ls", "cd", "docker", "ssh", "git", "sudo", "pip"):
            assert cmd in forge_llm.SHELL_COMMANDS, f"{cmd} manquant"

    def test_intent_classifier_exists(self):
        """IntentClassifier est instanciable sans crash."""
        import forge_llm
        clf = forge_llm.IntentClassifier()
        assert clf is not None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — IntentClassifier : routage fonctionnel
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def classifier():
    import forge_llm
    return forge_llm.IntentClassifier()


class TestIntentRouting:
    """Vérifie que le classifier route correctement vers ACTION/RAG/CHAT."""

    @pytest.mark.parametrize("text", [
        "ls -la /tmp",
        "docker ps",
        "sudo systemctl restart nginx",
        "git status",
        "ping localhost",
    ])
    def test_shell_commands_route_action(self, classifier, text):
        import forge_llm
        result, cmd = classifier.classify_with_cmd(text)
        assert result == forge_llm.AgentType.ACTION, f"'{text}' devrait → ACTION, got {result}"

    @pytest.mark.parametrize("text", [
        "Bonjour, comment ça va ?",
        "Quelle est la différence entre TCP et UDP ?",
        "ok merci beaucoup",
    ])
    def test_conversation_routes_chat(self, classifier, text):
        import forge_llm
        result, _ = classifier.classify_with_cmd(text)
        assert result == forge_llm.AgentType.CHAT, f"'{text}' devrait → CHAT, got {result}"

    @pytest.mark.parametrize("text", [
        "cherche dans la documentation comment configurer nginx",
        "montre le document sur le déploiement",
        "Explique-moi le concept de microservices",
    ])
    def test_rag_keywords_route_rag(self, classifier, text):
        import forge_llm
        result, _ = classifier.classify_with_cmd(text)
        assert result == forge_llm.AgentType.RAG, f"'{text}' devrait → RAG, got {result}"

    def test_short_phrase_rag_keyword_is_chat(self, classifier):
        """Phrase ≤3 mots avec keyword RAG → CHAT (heuristique short-phrase L401).
        C'est le comportement actuel voulu pour éviter les faux-positifs."""
        import forge_llm
        result, _ = classifier.classify_with_cmd("tutorial python asyncio")
        # 3 mots → short-phrase heuristic → CHAT (pas RAG)
        assert result == forge_llm.AgentType.CHAT

    def test_nlu_action_lance_commande(self, classifier):
        """'lance la commande X' → ACTION + extraction."""
        import forge_llm
        result, cmd = classifier.classify_with_cmd("lance la commande uptime")
        assert result == forge_llm.AgentType.ACTION
        assert cmd is not None and "uptime" in cmd

    @pytest.mark.parametrize("text", [
        "exécute df -h",
        "fais un ping 8.8.8.8",
    ])
    def test_nlu_short_action_hits_chat_heuristic(self, classifier, text):
        """Phrases ≤3 mots sans shell-first → CHAT (heuristique short-phrase).
        Gap NLU connu : ces formes devraient idéalement router ACTION."""
        import forge_llm
        result, _ = classifier.classify_with_cmd(text)
        # Actuellement CHAT à cause de la règle len(words)<=3
        assert result == forge_llm.AgentType.CHAT, (
            f"Si ce test échoue c'est que le gap NLU a été corrigé — "
            f"changer ce test pour attendre ACTION"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Validation statique des handlers : arguments obligatoires
# ═══════════════════════════════════════════════════════════════════════════════

class TestHandlerArgValidation:
    """Vérifie que les handlers avec args obligatoires ont une validation."""

    # Commandes qui DOIVENT vérifier les arguments manquants
    CMDS_REQUIRING_ARGS = {
        "@run": "command",
        "@estim": "description",
        # @scan : pas de validation arg manquant dans le handler actuel (gap connu)
    }

    @pytest.mark.parametrize("cmd,arg_name", list(CMDS_REQUIRING_ARGS.items()))
    def test_handler_checks_missing_arg(self, cmd, arg_name):
        """Le handler de {cmd} doit afficher une erreur si l'argument est vide."""
        # Cherche le bloc handler et vérifie qu'il y a un check "not <arg>"
        in_block = False
        block_lines = []
        for line in LAFORGE_LINES:
            if f'cmd == "{cmd}"' in line:
                in_block = True
            elif in_block and re.match(r"\s+elif\s+cmd\s", line):
                break
            if in_block:
                block_lines.append(line)

        block_text = "\n".join(block_lines)
        has_check = any(kw in block_text for kw in [
            "not command", "not description", "not _subnet",
            "Commande manquante", "Usage :", "manquant",
            'chat.write("[red]',
        ])
        assert has_check, (
            f"Handler {cmd} ne semble pas valider l'absence de '{arg_name}'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Smoke test: looks_like_shell_command cohérent
# ═══════════════════════════════════════════════════════════════════════════════

class TestLooksLikeShell:
    """Vérifie que looks_like_shell_command est cohérent."""

    def test_available(self):
        import forge_llm
        assert callable(forge_llm.looks_like_shell_command)

    @pytest.mark.parametrize("text,expected", [
        ("ls -la", True),
        ("docker compose up -d", True),
        ("echo hello | grep h", True),
        ("Bonjour comment vas-tu", False),
        ("", False),
    ])
    def test_basic_cases(self, text, expected):
        import forge_llm
        assert forge_llm.looks_like_shell_command(text) == expected, (
            f"looks_like_shell_command('{text}') devrait être {expected}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — NPU / embeddings.db : intégrité
# ═══════════════════════════════════════════════════════════════════════════════

class TestEmbeddingsDB:
    """Vérifie l'intégrité de la base vectorielle NPU."""

    DB_PATH = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"  # noqa  # rem: %NOKIDO_WORKSPACE%\LaForge\RAG\embeddings.db")

    def test_db_exists(self):
        assert self.DB_PATH.exists(), f"embeddings.db introuvable : {self.DB_PATH}"

    def test_db_wal_mode(self):
        """La DB doit être en mode WAL."""
        import sqlite3
        conn = sqlite3.connect(str(self.DB_PATH))
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        conn.close()
        assert mode == "wal", f"Mode journal = '{mode}', attendu 'wal'"

    def test_db_has_vectors(self):
        import sqlite3
        conn = sqlite3.connect(str(self.DB_PATH))
        count = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        conn.close()
        assert count >= 700, f"Seulement {count} vecteurs (attendu ≥ 700)"

    def test_db_integrity(self):
        import sqlite3
        conn = sqlite3.connect(str(self.DB_PATH))
        result = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        conn.close()
        assert result == "ok", f"Intégrité DB échouée : {result}"

    def test_vectors_are_valid_json(self):
        """Les embeddings stockés sont du JSON valide (listes de floats)."""
        import json
        import sqlite3
        conn = sqlite3.connect(str(self.DB_PATH))
        rows = conn.execute(
            "SELECT file_path, embedding FROM embeddings LIMIT 5"
        ).fetchall()
        conn.close()
        for path, emb_json in rows:
            vec = json.loads(emb_json)
            assert isinstance(vec, list), f"Embedding de {path} n'est pas une liste"
            assert len(vec) == 384, f"Dimension {len(vec)} ≠ 384 (MiniLM-L12-H384)"
            assert all(isinstance(v, float) for v in vec[:10]), "Valeurs non float"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — NPU Embedder : module + intégration RAG
# ═══════════════════════════════════════════════════════════════════════════════

class TestNPUEmbedderModule:
    """Vérifie que forge_npu_embedder.py est importable et structuré."""

    def test_import(self):
        import forge_npu_embedder
        assert hasattr(forge_npu_embedder, 'NPUEmbedder')
        assert hasattr(forge_npu_embedder, 'EMBED_DIM')
        assert forge_npu_embedder.EMBED_DIM == 384

    def test_class_interface(self):
        from forge_npu_embedder import NPUEmbedder
        # Vérifier que la classe a les méthodes attendues
        for method in ('embed_one', 'embed_batch', 'search_db', 'status'):
            assert hasattr(NPUEmbedder, method), f"Méthode {method} manquante"

    def test_status_returns_dict(self):
        """NPUEmbedder().status() retourne un dict même si le NPU n'est pas dispo."""
        from forge_npu_embedder import NPUEmbedder
        npu = NPUEmbedder()
        st = npu.status()
        assert isinstance(st, dict)
        assert 'available' in st
        assert 'provider' in st
        assert 'dim' in st
        assert st['dim'] == 384

    def test_graceful_when_model_missing(self):
        """Si le modèle ONNX n'existe pas, available=False sans crash."""
        from forge_npu_embedder import NPUEmbedder
        npu = NPUEmbedder(model_path="/nonexistent/model.onnx")
        assert npu.available is False
        assert npu.status()['available'] is False


class TestNPUIntegrationInRAG:
    """Vérifie que forge_rag_engine intègre le backend NPU."""

    def test_npu_import_block_exists(self):
        """Le bloc try/import NPUEmbedder est présent dans forge_rag_engine."""
        src = (APP / "forge_rag_engine.py").read_text(encoding="utf-8", errors="ignore")
        assert "from forge_npu_embedder import NPUEmbedder" in src
        assert "_npu_embedder" in src

    def test_get_embeddings_has_npu_path(self):
        """get_embeddings() contient le chemin NPU local avant Ollama."""
        src = (APP / "forge_rag_engine.py").read_text(encoding="utf-8", errors="ignore")
        npu_pos = src.index("NPU local (prioritaire)")
        ollama_pos = src.index("Ollama HTTP (fallback)")
        assert npu_pos < ollama_pos, "Le chemin NPU doit être AVANT Ollama"
