"""
tools/forge_trust_broker.py — SecretAnonymizer + OrchestratorTrustBroker
=========================================================================
Protège la PI avant envoi Cloud et synthétise les échecs multi-agents
en feedback actionnable sans trahir l'identité des agents.

Architecture Blind Swarm :
  Ryzen (orchestrateur)
    ↓ anonymise
  Cloud A / Cloud B / Cloud C  ← isolés, ne se voient pas
    ↓ retours bruts
  Ryzen
    ↓ ASTSurgeon + pytest + ruff (vérité absolue)
    ↓ synthèse diagnostic anonyme
  Agent suivant ← reçoit directive, pas les erreurs brutes

Usage :
  from tools.forge_trust_broker import OrchestratorTrustBroker
  broker = OrchestratorTrustBroker()
  payload  = broker.prepare(original_code, failures=[])
  restored, status = broker.process_response(agent_response, payload)
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ── SecretAnonymizer ──────────────────────────────────────────────────────────


class SecretAnonymizer:
    """
    Anonymise le code avant envoi Cloud — génère le mapping depuis l'AST.

    Principes :
    - Les noms de fonctions sont GARDÉS (le LLM doit les typer/documenter)
    - Les imports forge_* sont remplacés (révèle l'archi interne)
    - Les classes métier internes peuvent être masquées (optionnel)
    - Les variables credentials/token/key sont toujours masquées
    """

    # Patterns de variables sensibles
    SECRET_PATTERN = re.compile(
        r"token|key|secret|password|auth|cred|api_key|private", re.IGNORECASE
    )
    # Imports internes à masquer
    INTERNAL_IMPORT = re.compile(r"^forge_|^nokido")

    def __init__(self, mask_classes: bool = False) -> None:
        """Initialise l'anonymiseur."""
        self.mask_classes = mask_classes
        self._mapping: dict[str, str] = {}  # placeholder → original
        self._rev: dict[str, str] = {}  # original → placeholder
        self._counter: int = 0

    def _placeholder(self, kind: str) -> str:
        """Génère un placeholder unique."""
        p = f"FORGE_{kind}_{self._counter}"
        self._counter += 1
        return p

    def _extract_sensitive(self, code: str) -> list[str]:
        """Extrait les noms sensibles depuis l'AST."""
        sensitive = []
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # Imports internes
                if isinstance(node, ast.ImportFrom) and node.module:
                    if self.INTERNAL_IMPORT.match(node.module):
                        sensitive.append(node.module)
                # Variables credentials
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and self.SECRET_PATTERN.search(t.id):
                            sensitive.append(t.id)
                # Args secrets
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in node.args.args:
                        if self.SECRET_PATTERN.search(arg.arg):
                            sensitive.append(arg.arg)
                # Classes (optionnel)
                elif self.mask_classes and isinstance(node, ast.ClassDef):
                    if node.name.startswith("_") or "Internal" in node.name:
                        sensitive.append(node.name)
        except SyntaxError:
            pass
        return list(set(sensitive))

    def anonymize(self, code: str) -> str:
        """Remplace les termes sensibles par des placeholders."""
        self._mapping.clear()
        self._rev.clear()
        self._counter = 0

        sensitive = self._extract_sensitive(code)
        result = code

        for name in sorted(sensitive, key=len, reverse=True):  # plus long d'abord
            if name in self._rev:
                continue
            kind = "MOD" if "." in name or self.INTERNAL_IMPORT.match(name) else "VAR"
            ph = self._placeholder(kind)
            self._mapping[ph] = name
            self._rev[name] = ph
            result = result.replace(name, ph)

        return result

    def restore(self, code: str) -> str:
        """Restaure les vrais noms depuis les placeholders."""
        result = code
        for ph, original in self._mapping.items():
            result = result.replace(ph, original)
        return result

    def mapping_summary(self) -> dict:
        """Retourne le mapping pour debug (ne jamais envoyer au cloud)."""
        return dict(self._mapping)


# ── DiagnosticSynthesizer ─────────────────────────────────────────────────────


class DiagnosticSynthesizer:
    """
    Transforme les échecs bruts de N agents en directive actionnable.
    Ne révèle jamais quel agent a échoué — seulement la cause technique.
    """

    @staticmethod
    def synthesize(results: list[dict]) -> str:
        """
        Agrège les erreurs de N branches en feedback anonyme.

        Input  : [{"agent": "qwen", "score": 0, "feedback": "AST KO: ..."}]
        Output : directive textuelle pour le prochain agent
        """
        if not results:
            return "Aucun retour disponible — première tentative."

        total = len(results)
        failed = [r for r in results if r.get("score", 0) == 0]
        succeeded = [r for r in results if r.get("score", 0) > 0]

        if succeeded:
            best = max(succeeded, key=lambda x: x["score"])
            return (
                f"Une mutation partielle a atteint un score de {best['score']}/100. "
                f"Retour technique: {best.get('feedback', '')[:120]}. "
                f"Améliore ce résultat."
            )

        # Toutes en échec — extrait la cause racine commune
        feedbacks = [r.get("feedback", "") for r in failed]
        causes = DiagnosticSynthesizer._extract_root_causes(feedbacks)

        lines = [f"DIAGNOSTIC ({total} tentatives, toutes en échec):"]
        for cause, count in sorted(causes.items(), key=lambda x: -x[1]):
            lines.append(f"  - {cause} (observé {count}x)")

        lines.append("DIRECTIVE: Corrige ces problèmes en priorité.")
        return chr(10).join(lines)

    @staticmethod
    def _extract_root_causes(feedbacks: list[str]) -> dict[str, int]:
        """Extrait et déduplique les causes racines depuis les feedbacks."""
        cause_patterns = {
            "Troncature détectée": r"tronc|troncature|manquante|supprimée",
            "Erreur de syntaxe": r"SyntaxError|syntax|parse",
            "Import manquant": r"ImportError|ModuleNotFound|import",
            "Test unitaire échoué": r"pytest KO|test.*fail|assertion",
            "Corps de classe vidé": r"vidé|empty.*class|body.*0",
            "Timeout d'inférence": r"timeout|timed out",
        }
        found: dict[str, int] = {}
        for fb in feedbacks:
            for cause, pattern in cause_patterns.items():
                if re.search(pattern, fb, re.IGNORECASE):
                    found[cause] = found.get(cause, 0) + 1
        if not found:
            found["Erreur indéterminée"] = len(feedbacks)
        return found


# ── OrchestratorTrustBroker ───────────────────────────────────────────────────


class OrchestratorTrustBroker:
    """
    Courtier de confiance — point central entre les agents et l'orchestrateur.

    Responsabilités :
    1. Anonymise le code avant envoi (SecretAnonymizer)
    2. Synthétise les échecs en feedback actionnable (DiagnosticSynthesizer)
    3. Valide les retours (anti-injection, intégrité AST)
    4. Logue dans le RAG JSONL pour apprentissage futur
    """

    LOG_FILE = ROOT / "shadow_mutation" / "rag_index" / "trust_broker.jsonl"

    def __init__(self, mask_classes: bool = False) -> None:
        """Initialise le broker."""
        self.anonymizer = SecretAnonymizer(mask_classes=mask_classes)
        self.synthesizer = DiagnosticSynthesizer()

    def prepare(
        self,
        original_code: str,
        failures: list[dict] | None = None,
        task: str = "improve",
    ) -> dict:
        """
        Prépare le payload pour un agent Cloud.

        Retourne un dict avec :
        - code         : code anonymisé
        - feedback     : diagnostic synthétisé des échecs précédents
        - instruction  : directive claire pour l'agent
        - _mapping_id  : hash du mapping (jamais envoyé au cloud)
        """
        clean = self.anonymizer.anonymize(original_code)
        mapping = self.anonymizer.mapping_summary()

        feedback = ""
        if failures:
            feedback = self.synthesizer.synthesize(failures)

        mapping_id = hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest()[:12]

        return {
            # ← envoyé au cloud
            "code": clean,
            "feedback": feedback,
            "instruction": self._build_instruction(task, feedback),
            # ← local uniquement
            "_mapping_id": mapping_id,
            "_mapping": mapping,  # ne jamais envoyer au cloud
        }

    def process_response(
        self,
        raw_response: str,
        payload: dict,
    ) -> tuple[str, str]:
        """
        Valide et restaure la réponse d'un agent Cloud.

        Retourne (code_restauré, status).
        status = "OK" | message d'erreur.
        """
        # 1. Extrait le code si dans un bloc ```python
        code = raw_response
        m = re.search(r"```python\s*(.*?)```", raw_response, re.DOTALL)
        if m:
            code = m.group(1).strip()

        # 2. Restaure les noms réels
        restored = self.anonymizer.restore(code)

        # 3. Validation sécurité — anti-injection
        dangerous = [
            r"os\.system\s*\(",
            r"subprocess\.",
            r"eval\s*\(",
            r"exec\s*\(",
            r"__import__\s*\(",
            r'open\s*\([^)]*["\']w["\']',
        ]
        for pattern in dangerous:
            if re.search(pattern, restored):
                self._log_security_event(pattern, restored[:200])
                return "", f"SECURITE: pattern dangereux détecté ({pattern})"

        # 4. Valide AST basique
        try:
            ast.parse(restored)
        except SyntaxError as e:
            return "", f"SyntaxError: {e}"

        # 5. Vérifie que les placeholders ont bien été retirés
        remaining = re.findall(r"FORGE_(?:CLASS|MOD|VAR)_\d+", restored)
        if remaining:
            return "", f"Placeholders non restaurés: {remaining}"

        return restored, "OK"

    def build_agent_prompt(self, payload: dict) -> str:
        """Construit le prompt final à envoyer au LLM (sans données sensibles)."""
        parts = []
        if payload.get("feedback"):
            parts.append("CONTEXT FROM PREVIOUS ATTEMPTS:")
            parts.append(payload["feedback"])
            parts.append("")
        parts.append(payload["instruction"])
        parts.append("")
        parts.append("```python")
        parts.append(payload["code"])
        parts.append("```")
        return chr(10).join(parts)

    @staticmethod
    def _build_instruction(task: str, has_feedback: bool | str) -> str:
        """Construit la directive selon la tâche."""
        base = {
            "type_hints": "Add Python 3.9+ type hints to ALL function parameters and return values.",
            "docstrings": "Add Google-style docstrings to ALL functions and classes.",
            "refactor": "Refactor this code for clarity and performance.",
            "improve": "Improve this code: add type hints, docstrings, fix any issues.",
        }.get(task, "Improve this Python code.")

        return (
            base + chr(10) + "RULES: Return ONLY the complete Python code. "
            "Never truncate. Preserve ALL classes and their bodies exactly."
        )

    def _log_security_event(self, pattern: str, snippet: str) -> None:
        """Log un événement de sécurité dans le RAG."""
        import datetime as _dt

        self.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _dt.datetime.now(_dt.UTC).isoformat(),
            "type": "security_alert",
            "pattern": pattern,
            "snippet": snippet,
        }
        with self.LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
        print(f"[SECURITY] Pattern dangereux bloqué: {pattern}")


# ── Test rapide ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    broker = OrchestratorTrustBroker()

    code = (Path(ROOT) / "app/forge_routing.py").read_text(encoding="utf-8", errors="replace")

    # Simule 2 échecs précédents
    failures = [
        {"agent": "qwen7b", "score": 0, "feedback": "AST KO: Classe PromptCategory supprimée"},
        {"agent": "llama70b", "score": 0, "feedback": "AST KO: Troncature 198L→120L"},
    ]

    payload = broker.prepare(code, failures, task="type_hints")

    print(f"Code original  : {len(code)}c")
    print(f"Code anonymisé : {len(payload['code'])}c")
    print(f"Mapping        : {len(payload['_mapping'])} substitutions")
    print(f"Feedback       :\n{payload['feedback']}")
    print(f"\nPrompt cloud (extrait):\n{broker.build_agent_prompt(payload)[:300]}...")
