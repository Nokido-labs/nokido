"""Bench tokens BAML vs pydantic JSON Schema for ForgeSiloEngine code silo."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Pydantic equivalent (verbeux)
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from enum import Enum

class Severity(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"

class Category(str, Enum):
    security = "security"
    performance = "performance"
    style = "style"
    logic = "logic"

class IssuePydantic(BaseModel):
    line: int = Field(description="Line number")
    severity: Severity = Field(description="Severity level")
    category: Category = Field(description="Issue category")
    message: str = Field(description="Issue description")
    fix_hint: Optional[str] = Field(None, description="Optional fix hint")

class CodeAnalysisPydantic(BaseModel):
    language: str = Field(description="Programming language detected")
    complexity_score: int = Field(description="Cyclomatic complexity 1-100", ge=1, le=100)
    issues: List[IssuePydantic] = Field(description="List of issues found")
    suggestions: List[str] = Field(description="Refactoring suggestions")
    refactor_priority: Literal["low", "medium", "high", "critical"]

# JSON schema = ce qu'on injecterait dans prompt avec OpenAI tool calling / pydantic
pyd_schema_json = json.dumps(CodeAnalysisPydantic.model_json_schema(), indent=2)
print("=== Pydantic JSON Schema ===")
print(pyd_schema_json)
print()

# BAML schema (ce que BAML injecte dans le prompt) — on extrait via runtime
try:
    from baml_client import b
    from baml_client.types import CodeAnalysis  # type: ignore
    # BAML format est plus compact, on lit depuis le .baml
    baml_schema_text = Path(__file__).parent.joinpath("baml_src", "silo_code.baml").read_text(encoding="utf-8")
    # Extract "class CodeAnalysis" + "class Issue" blocks
    lines = baml_schema_text.split("\n")
    in_class = False
    extracted = []
    for line in lines:
        if line.strip().startswith("class "):
            in_class = True
        if in_class:
            extracted.append(line)
            if line.strip() == "}":
                in_class = False
    baml_schema = "\n".join(extracted)
    print("=== BAML Schema (compact) ===")
    print(baml_schema)
    print()
except Exception as e:
    print(f"baml_client import skipped: {e}")
    baml_schema = ""

# Tokenize via tiktoken
import tiktoken
enc = tiktoken.get_encoding("cl100k_base")
pyd_tokens = len(enc.encode(pyd_schema_json))
baml_tokens = len(enc.encode(baml_schema)) if baml_schema else 0

print("=" * 60)
print(f"Pydantic JSON Schema : {pyd_tokens:>5} tokens")
print(f"BAML compact schema  : {baml_tokens:>5} tokens")
if pyd_tokens and baml_tokens:
    saving = (pyd_tokens - baml_tokens) / pyd_tokens * 100
    print(f"Économie             : {saving:>5.1f}%")
    print(f"Ratio                : {pyd_tokens/baml_tokens:.1f}× moins")
