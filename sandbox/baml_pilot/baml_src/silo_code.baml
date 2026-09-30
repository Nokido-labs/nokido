// Pilote BAML pour ForgeSiloEngine — silo CODE
// Replace pydantic JSON Schema (~800 tokens overhead) avec types BAML (~160 tokens)

client<llm> NokidoLocalLlamaCpp {
  provider openai-generic
  options {
    base_url "http://127.0.0.1:8080/v1"
    model "qwen2.5-coder"
    api_key "noop"
  }
}

client<llm> NokidoLocalOllama {
  provider openai-generic
  options {
    base_url "http://127.0.0.1:11434/v1"
    model "qwen2.5-coder:7b-instruct-q4_K_M"
    api_key "noop"
  }
}

// Fallback : Ollama only (:11434).
// NOTE 2026-05-02 : NokidoLocalLlamaCpp dropped from fallback — port :8080
// héberge en réalité SearXNG, pas llama.cpp. CLAUDE.md §8 inexact.
// Si llama.cpp natif est relancé sur un port libre, ré-ajouter NokidoLocalLlamaCpp.
client<llm> MdRouterFallback {
  provider fallback
  options {
    strategy [NokidoLocalOllama]
  }
}

// Output structuré silo CODE
class CodeAnalysis {
  language string @description("Programming language detected")
  complexity_score int @description("Cyclomatic complexity 1-100")
  issues Issue[]
  suggestions string[]
  refactor_priority "low" | "medium" | "high" | "critical"
}

class Issue {
  line int
  severity "info" | "warning" | "error"
  category "security" | "performance" | "style" | "logic"
  message string
  fix_hint string?
}

// Fonction silo CODE — le pattern qu'on adopte
function AnalyzeCode(code: string, context: string?) -> CodeAnalysis {
  client NokidoLocalOllama
  prompt #"
    Analyse ce code et retourne une analyse structurée.

    {{ ctx.output_format }}

    {% if context %}
    Contexte fourni :
    {{ context }}
    {% endif %}

    Code à analyser :
    ```
    {{ code }}
    ```
  "#
}

// Test pour mesurer tokens
test BasicCodeAnalysis {
  functions [AnalyzeCode]
  args {
    code "def add(a, b):\n    eval(input())\n    return a + b"
    context "Module utilitaire mathématique"
  }
}
