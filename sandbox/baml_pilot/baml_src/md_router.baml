// Nokido MD Router — semantic gateway for ADR/spec/style/doc Markdown files
// Goal: lazy-load decisions from /docs/*.md instead of dumping raw content.
// Token economy : 2000-3000 tok (full doc) → 200-300 tok (extracted decision).

// ─────────────────────────────────────────────────────────────────────────────
// Schemas
// ─────────────────────────────────────────────────────────────────────────────

class MdDocSummary {
  path string @description("Relative path of the Markdown file")
  doc_type "adr" | "spec" | "style" | "guide" | "incident" | "roadmap" | "skill" | "other"
  title string @description("First H1 or file basename")
  status "draft" | "accepted" | "planned" | "rejected" | "superseded" | "deprecated" | "active" | "unknown"
  topics string[] @description("3-7 short keyword tags extracted from title + first paragraph")
}

class AdrExtract {
  id int? @description("ADR sequential id if numbered (e.g. ADR-002 → 2)")
  title string
  status "draft" | "accepted" | "planned" | "rejected" | "superseded" | "deprecated"
  context_one_line string @description("One sentence — what problem motivated this ADR")
  decision string @description("The actual decision in 1-3 sentences. No history, no debate, just what was decided.")
  constraints string[] @description("Hard constraints/requirements derived from the decision (max 5)")
  invalidates_if string? @description("Condition under which this decision becomes obsolete")
  source_path string
}

class SpecExtract {
  title string
  endpoints string[] @description("API endpoints, ports, URLs mentioned (max 10)")
  data_types string[] @description("Key types/schemas referenced")
  rules string[] @description("Hard rules (MUST/SHALL) extracted from spec, max 8")
  source_path string
}

class StyleExtract {
  naming_convention "camelCase" | "snake_case" | "kebab-case" | "PascalCase" | "mixed" | "unspecified"
  forbidden_libraries string[]
  mandatory_patterns string[] @description("Coding patterns the doc requires (max 5)")
  forbidden_patterns string[] @description("Patterns the doc forbids (max 5)")
  source_path string
}

class RouterDecision {
  query string
  selected_paths string[] @description("Relative paths of MD files relevant to query, ranked. Max 3.")
  rationale string @description("One short sentence : why these were chosen.")
  confidence float @description("0.0-1.0")
}

// ─────────────────────────────────────────────────────────────────────────────
// Functions
// ─────────────────────────────────────────────────────────────────────────────

// Index step : take a list of (path, headers + first 500 chars) and return summaries.
// Cheap: only reads frontmatter-equivalent, not full bodies.
function IndexMarkdownDocs(doc_previews: string) -> MdDocSummary[] {
  client MdRouterFallback
  prompt #"
    You receive a list of Markdown file previews. Each preview is delimited by:
    `### PATH: <relative_path>\n<content first 500 chars>\n---END---`

    Produce one MdDocSummary per file. Detect doc_type from path/title patterns:
    - `ADR-*` or `adr-*` → "adr"
    - `SPEC*`, `*_SPEC*` → "spec"
    - `style_*`, `STYLE*` → "style"
    - `INCIDENT-*`, `POC-*` → "incident"
    - `ROADMAP*`, `roadmap_*` → "roadmap"
    - `SKILL.md` in skills/ → "skill"
    - else → "guide" or "other"

    Status detection: search "Statut", "Status", "État" near top.
    Topics: 3-7 short technical keywords from title + first paragraph.

    {{ ctx.output_format }}

    Documents to index:
    {{ doc_previews }}
  "#
}

// Routing step : given a user query + lightweight index, pick relevant docs.
function RouteQueryToDocs(user_query: string, doc_index: MdDocSummary[]) -> RouterDecision {
  client MdRouterFallback
  prompt #"
    The user asks: "{{ user_query }}"

    You have an index of documentation files (path + title + status + topics).
    Pick at most 3 paths most likely to contain the answer. Prefer:
    - status="accepted" or "active" over "rejected" / "superseded" / "deprecated"
    - exact topic match over fuzzy match
    - Recent ADRs over old ones if both seem relevant

    If query is vague or no doc fits, return empty selected_paths and confidence < 0.3.

    {{ ctx.output_format }}

    Index:
    {{ doc_index }}
  "#
}

// Extraction step : take a single ADR's full content, return structured decision only.
function ExtractAdrDecision(adr_content: string, adr_path: string) -> AdrExtract {
  client MdRouterFallback
  prompt #"
    Extract the decision essence from this ADR. IGNORE :
    - rejected alternatives, debate history, dates
    - rationale paragraphs (we only want the result)

    KEEP :
    - one-sentence context (problem statement)
    - the decision itself (1-3 sentences)
    - hard constraints/requirements (max 5, imperative form)
    - invalidation condition if mentioned

    Source path : {{ adr_path }}

    {{ ctx.output_format }}

    ADR content:
    {{ adr_content }}
  "#
}

// Spec extraction
function ExtractSpec(spec_content: string, spec_path: string) -> SpecExtract {
  client MdRouterFallback
  prompt #"
    Extract the API/spec essentials from this Markdown. KEEP endpoints, types, hard rules.
    IGNORE prose intros, business goals, motivation paragraphs.

    Source path : {{ spec_path }}

    {{ ctx.output_format }}

    Spec content:
    {{ spec_content }}
  "#
}

// Style extraction
function ExtractStyle(style_content: string, style_path: string) -> StyleExtract {
  client MdRouterFallback
  prompt #"
    Extract coding style constraints from this Markdown. Identify naming convention,
    forbidden libraries, mandatory and forbidden patterns. IGNORE redundant examples and philosophy.

    Source path : {{ style_path }}

    {{ ctx.output_format }}

    Style doc content:
    {{ style_content }}
  "#
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests (token bench targets)
// ─────────────────────────────────────────────────────────────────────────────

test AdrExtractionADR002 {
  functions [ExtractAdrDecision]
  args {
    adr_path "docs/ADR-002-netcfg-streamable-http.md"
    adr_content #"
# ADR-002 : Migration netcfg-agent-mcp SSE → Streamable HTTP

**Date** : 2026-04-27
**Statut** : PLANIFIÉ — deadline mi-2026

## Contexte
netcfg-agent-mcp v0.1.1 tourne en HTTP+SSE (spec MCP 2024-11-05).
La spec 2025-03-26 déprécie SSE.

## Décision
Migrer netcfg-agent-mcp vers Streamable HTTP avant juin 2026.

## Plan d'action
1. Remplacer SSEServerTransport par StreamableHTTP
2. Endpoint unique /mcp
3. Ajouter Mcp-Session-Id header
4. Origin validation
"#
  }
}

test RouterPicksRelevantAdr {
  functions [RouteQueryToDocs]
  args {
    user_query "comment dois-je gérer la session MCP côté netcfg ?"
    doc_index [
      {
        path "docs/ADR-002-netcfg-streamable-http.md"
        doc_type "adr"
        title "Migration netcfg-agent-mcp SSE → Streamable HTTP"
        status "planned"
        topics ["mcp", "netcfg", "streamable-http", "session-id", "transport"]
      },
      {
        path "docs/ADR-003-secrets-wcm-vault.md"
        doc_type "adr"
        title "Secrets WCM Vault"
        status "accepted"
        topics ["secrets", "vault", "wcm", "credentials"]
      },
      {
        path "docs/WASM_PLAN.md"
        doc_type "roadmap"
        title "WASM Plan"
        status "active"
        topics ["wasm", "wasmtime", "embedding"]
      }
    ]
  }
}
