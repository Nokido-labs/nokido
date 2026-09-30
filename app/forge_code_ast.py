from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : analyse statique AST du code"  # organe declare le 2026-09-06 (audit de raccordement)
import ast
import logging
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Tuple

logger = logging.getLogger("forge.code.ast")

def analyze_ast(code: str) -> Tuple[bool, str]:
    """
    Analyse statique AST du code Python.
    Retourne (True, "OK") si le code est syntaxiquement valide.
    Retourne (False, msg_erreur) sinon.
    """
    try:
        ast.parse(code)
        return True, "AST OK"
    except SyntaxError as e:
        msg = f"SyntaxError ligne {e.lineno}, colonne {e.offset}: {e.msg}\n"
        if e.text:
            msg += f"  {e.text.strip()}\n"
            msg += f"  {' ' * ((e.offset or 1) - 1)}^\n"
        return False, msg
    except Exception as e:
        return False, f"Erreur AST inconnue : {e}"

def validate_python_syntax(code: str) -> Tuple[bool, str]:
    """Alias pour analyze_ast."""
    return analyze_ast(code)

async def pylint_score(code: str) -> float:
    """
    Exécute Pylint de manière isolée sur un bloc de code et retourne la note sur 10.
    """
    # Exécution via subprocess pour éviter les fuites de mémoire pylint
    script = (
        f"import pylint.lint, sys; "
        f"from io import StringIO; "
        f"import tempfile, os; "
        f"fd, path = tempfile.mkstemp(suffix='.py'); "
        f"os.write(fd, sys.argv[1].encode('utf-8')); "
        f"os.close(fd); "
        f"pylint_output = StringIO(); "
        f"Run([path, '--output-format=text', '--score=y'], reporter=TextReporter(pylint_output), exit=False); "
        f"txt = pylint_output.getvalue(); "
        f"import re; m=re.search(r'rated at ([\\d.]+)', txt); "
        f"print(m.group(1) if m else '0.0'); "
        f"os.unlink(path)"
    )
    import asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script, code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            return float(stdout.decode().strip())
    except Exception as e:
        logger.error(f"Pylint error: {e}")
    return 0.0

def count_real_errors(code: str) -> int:
    """Compte le nombre de types d'erreurs réelles via AST/Regex simples (fallback rapide)."""
    errors = 0
    ok, _ = analyze_ast(code)
    if not ok:
        errors += 1
    # Check imports manquants basiques (très naïf)
    if re.search(r"^\s*import [a-zA-Z_]\w*\s*$", code, re.MULTILINE):
        # On ne peut pas statiquement savoir si c'est valide sans sys.modules
        pass 
    return errors

def score_code_quality(code: str) -> int:
    """Retourne un score abstrait basé sur la longueur et la complexité."""
    return len(code) // 100

def compute_diff_summary(before: str, after: str) -> str:
    import difflib
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), n=0))
    added = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
    removed = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
    return f"+{added} -{removed} lignes"

class AuditParser:
    """
    Parse les réponses textuelles des LLMs (audits).
    Complémentaire à count_real_errors qui analyse le CODE.
    AuditParser analyse ce que le LLM dit sur le code.
    """

    SUGGESTION_RE = re.compile(
        r"(?:Suggestion|Fix|Correction|Patch)\s*[#°N]*\s*(\d+)\s*[:\-]\s*(.*?)\n```python\n(.*?)\n```",
        re.DOTALL | re.IGNORECASE,
    )
    CLEAN_PHRASES = [
        "aucun problème", "no issues", "code is clean", "aucune erreur",
        "no errors found", "looks good", "bien structuré", "no bugs",
        "nothing to fix", "parfait", "optimal"
    ]

    @classmethod
    def extract_suggestions(cls, text: str) -> List[Dict]:
        """Extrait les blocs de code markdown étiquetés comme suggestions."""
        results = []
        for match in cls.SUGGESTION_RE.finditer(text):
            results.append({
                "id": match.group(1),
                "desc": match.group(2).strip(),
                "code": match.group(3).strip()
            })
        return results

    @classmethod
    def count_audit_errors(cls, text: str) -> int:
        """Compte les occurences de mots-clés d'erreurs dans l'audit."""
        err_keywords = ["error", "bug", "issue", "vulnerability", "leak", "crash", "exception", "fail"]
        return sum(text.lower().count(kw) for kw in err_keywords)

    @classmethod
    def is_clean(cls, text: str) -> bool:
        """Détermine si l'audit conclut que le code est propre."""
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in cls.CLEAN_PHRASES) and cls.count_audit_errors(text) < 2
