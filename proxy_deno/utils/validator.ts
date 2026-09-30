/**
 * RÈGLE D'OR : Validation souveraine des schémas d'outils.
 * Phase 1.2 hardened — strict inputSchema MCP + blacklist élargie sensible.
 */

const FORBIDDEN_PATTERNS = [
  // Fichiers secrets
  /\.env\b/i,
  /nokido\.env\b/i,
  /id_rsa\b/i,
  /id_ed25519\b/i,
  /\.pem\b/i,
  /\.kdbx\b/i,
  /\.token\b/i,
  /credentials\.json/i,
  /oauth_creds\.json/i,
  // Paths Linux/Windows sensibles
  /\/etc\/passwd/i,
  /\/etc\/shadow/i,
  /\/root\/\.ssh/i,
  /~\/\.ssh\/id_/i,
  /~\/\.aws\/credentials/i,
  /\.docker\/config\.json/i,
  // Windows Credential Manager exfil
  /Get-StoredCredential/i,
  /Export-PfxCertificate/i,
  /ConvertFrom-SecureString/i,
  // Mimikatz / lsass
  /sekurlsa::/i,
  /lsadump::/i,
  /Invoke-Mimikatz/i,
  // Reverse shells / destructeur
  /rm\s+-rf\s+\//i,
  /sudo\s+rm\s+-rf/i,
  /bash\s+-i\s+>&\s*\/dev\/tcp/i,
  /Remove-Item.*-Recurse.*-Force.*[Cc]:/i,
];


export function validateToolDefinitions(payload: any): boolean {
  // Pas de tools = OK (intent peut etre task/message)
  if (!payload.tools || !Array.isArray(payload.tools)) {
    return true;
  }

  for (const tool of payload.tools) {
    // STRICT — name obligatoire (string non vide)
    if (!tool.name || typeof tool.name !== "string" || tool.name.trim().length === 0) {
      console.error(`🛡️ [Validator] Tool sans nom valide`);
      return false;
    }

    // STRICT — schema obligatoire (inputSchema preferred, parameters legacy)
    const schema = tool.inputSchema || tool.parameters;
    if (!schema) {
      console.error(`🛡️ [Validator] Tool ${tool.name} : inputSchema/parameters manquant`);
      return false;
    }

    // STRICT — type=object requis (MCP spec)
    if (typeof schema !== "object" || schema === null) {
      console.error(`🛡️ [Validator] Tool ${tool.name} : schema doit etre objet`);
      return false;
    }
    if (schema.type !== "object") {
      console.error(`🛡️ [Validator] Tool ${tool.name} : schema.type="${schema.type}" (attendu "object")`);
      return false;
    }
    if (!schema.properties || typeof schema.properties !== "object") {
      console.error(`🛡️ [Validator] Tool ${tool.name} : schema.properties manquant`);
      return false;
    }

    // MEMBRANE SELECTIVE — blacklist elargie sur arguments
    const argsString = JSON.stringify(tool.arguments || {});
    for (const pattern of FORBIDDEN_PATTERNS) {
      if (pattern.test(argsString)) {
        console.error(`🛡️ [Membrane] Blocage tool=${tool.name} pattern=${pattern}`);
        return false;
      }
    }
  }

  return true;
}


export function validateIntent(payload: any): { ok: boolean; reason?: string } {
  if (!payload || typeof payload !== "object") {
    return { ok: false, reason: "payload doit etre objet" };
  }
  if (!payload.tools && !payload.task && !payload.message) {
    return { ok: false, reason: "intent vide (manque tools|task|message)" };
  }
  const intentString = JSON.stringify({ task: payload.task, message: payload.message });
  for (const pattern of FORBIDDEN_PATTERNS) {
    if (pattern.test(intentString)) {
      return { ok: false, reason: `pattern interdit: ${pattern}` };
    }
  }
  return { ok: true };
}
