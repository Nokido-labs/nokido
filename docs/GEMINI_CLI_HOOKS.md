# Gemini CLI Hooks — Documentation Extraite du Bundle Local

## Hooks disponibles

### SessionStart — gemini-LSLMD4HG.js
```js
"BeforeTool",
  PostToolUse: "AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file",
  Write: "write_file",
  Glob: "glob",
  Grep: "grep",
  LS: "ls"
};
function transformMatcher(matcher) {
  if (!matcher) return matcher;
  let transformed = matcher;
  for (const [claudeName, gemin
```


### AfterAgent — gemini-LSLMD4HG.js
```js
";
var import_strip_json_comments = __toESM(require_strip_json_comments(), 1);
var EVENT_MAPPING = {
  PreToolUse: "BeforeTool",
  PostToolUse: "AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file",
  Write: "write_file",
  Glob: "glob",
  Grep: "grep",
  LS: "ls"
};
function trans
```


### BeforeAgent — gemini-LSLMD4HG.js
```js
s path3 from "node:path";
var import_strip_json_comments = __toESM(require_strip_json_comments(), 1);
var EVENT_MAPPING = {
  PreToolUse: "BeforeTool",
  PostToolUse: "AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file",
  Write: "write_file",
  Glob: "glob",
  Grep: "grep",
  LS:
```


### SessionEnd — gemini-LSLMD4HG.js
```js
AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file",
  Write: "write_file",
  Glob: "glob",
  Grep: "grep",
  LS: "ls"
};
function transformMatcher(matcher) {
  if (!matcher) return matcher;
  let transformed = matcher;
  for (const [claudeName, geminiName] of Object.entries(TOOL_
```


### AfterTool — gemini-LSLMD4HG.js
```js
as fs2 from "node:fs";
import * as path3 from "node:path";
var import_strip_json_comments = __toESM(require_strip_json_comments(), 1);
var EVENT_MAPPING = {
  PreToolUse: "BeforeTool",
  PostToolUse: "AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file",
  Write: "write_file",
  Gl
```


### BeforeTool — gemini-LSLMD4HG.js
```js
ds/hooks/migrate.ts
import * as fs2 from "node:fs";
import * as path3 from "node:path";
var import_strip_json_comments = __toESM(require_strip_json_comments(), 1);
var EVENT_MAPPING = {
  PreToolUse: "BeforeTool",
  PostToolUse: "AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file"
```


### SessionStart — gemini-TKPXJBGX.js
```js
"BeforeTool",
  PostToolUse: "AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file",
  Write: "write_file",
  Glob: "glob",
  Grep: "grep",
  LS: "ls"
};
function transformMatcher(matcher) {
  if (!matcher) return matcher;
  let transformed = matcher;
  for (const [claudeName, gemin
```


### AfterAgent — gemini-TKPXJBGX.js
```js
";
var import_strip_json_comments = __toESM(require_strip_json_comments(), 1);
var EVENT_MAPPING = {
  PreToolUse: "BeforeTool",
  PostToolUse: "AfterTool",
  UserPromptSubmit: "BeforeAgent",
  Stop: "AfterAgent",
  SubAgentStop: "AfterAgent",
  // Gemini doesn't have sub-agents, map to AfterAgent
  SessionStart: "SessionStart",
  SessionEnd: "SessionEnd",
  PreCompact: "PreCompress",
  Notification: "Notification"
};
var TOOL_NAME_MAPPING = {
  Edit: "replace",
  Bash: "run_shell_command",
  Read: "read_file",
  Write: "write_file",
  Glob: "glob",
  Grep: "grep",
  LS: "ls"
};
function trans
```


## Format settings.json

### hooksConfig example — chunk-DYY5TRG5.js
```js

        items: { type: "string" },
        mergeStrategy: "union" /* UNION */
      }
    }
  },
  hooksConfig: {
    type: "object",
    label: "HooksConfig",
    category: "Advanced",
    requiresRestart: false,
    default: {},
    description: "Hook configurations for intercepting and customizing agent behavior.",
    showInDialog: false,
    properties: {
      enabled: {
        type: "boolean",
        label: "Enable Hooks",
        category: "Advanced",
        requiresRestart: true,
        default: true,
        description: "Canonical toggle for the hooks system. When disabled, no hooks will be executed.",
        showInDialog: true
      },
      disabled: {
        type: "array
```


## Format connu (settings.json)
```json
{
  "hooks": {
    "SessionStart": [{"command": "python", "args": ["tools/quota_hook.py"], "timeout": 10000}],
    "AfterModel": [{"command": "python", "args": ["tools/after_model_hook.py"]}],
    "BeforeModel": [{"command": "python", "args": ["tools/before_model_hook.py"]}],
    "AfterAgent": [{"command": "python", "args": ["tools/after_agent_hook.py"]}],
    "SessionEnd": [{"command": "python", "args": ["tools/session_end_hook.py"]}]
  }
}
```

## Injection contexte → LLM
Les hooks sont des process externes. Leur stdout est capturé mais PAS injecté
directement dans le contexte LLM. La seule façon d'injecter du contexte :
1. Écrire dans GEMINI.md projet (rechargé par le CLI)
2. Utiliser save_memory tool du CLI
3. Passer par le hub MCP via notification

## Lecture quota programmatique
Impossible sans /model interactif — les quotas ne sont pas dans les fichiers locaux.
Solution : Gemini reporte manuellement via hub action=quota_report après avoir vu /model.
