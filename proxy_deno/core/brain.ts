import { bus, BloodCell } from "./nervous_system.ts";
import { validateToolDefinitions } from "../utils/validator.ts";
import { isServiceAlive } from "../utils/health.ts";
import { getVaultVar, setVaultVar } from "./vault.ts";

/**
 * Le Cerveau : Reçoit l'intention du LLM, la valide et la route.
 */
export async function processLLMIntent(payload: any) {
  // 1. BARRIÈRE HÉMATO-ENCÉPHALIQUE (Validation Souveraine)
  if (!validateToolDefinitions(payload)) {
    console.error("🛑 [Brain] Rejet : Payload corrompu ou schéma manquant.");
    return {
      isError: true,
      content: [{ 
        type: "text", 
        text: "Erreur Nokido Proxy : Validation échouée. Définitions d'outils manquantes." 
      }]
    };
  }

  const tool = payload.tools?.[0];
  if (!tool) return { isError: false, content: [] };

  const jobId = crypto.randomUUID();
  const traceId = payload.traceId || payload.metadata?.session_id || "root_session";

  // --- GESTION DU VAULT (GET/SET ENV) ---
  if (tool.name === "get_env_var") {
    const key = tool.arguments?.key;
    const value = getVaultVar(key);
    console.log(`🔒 [Brain] Accès Vault : ${key}`);
    return {
      isError: false,
      content: [{ type: "text", text: value || `Variable ${key} non trouvée.` }]
    };
  }

  if (tool.name === "set_env_var") {
    const { key, value } = tool.arguments || {};
    console.warn(`⚠️ [Brain] Tentative de modification secret : ${key}`);
    
    // Déclenchement du mécanisme __LAFORGE_YIELD__ pour approbation humaine
    const yieldPayload = {
      intent_id: jobId,
      tool_requested: "set_env_var",
      risk_assessment: "high",
      ai_justification: `L'agent souhaite modifier ou ajouter la clé ${key} dans les secrets.`,
      payload: { key, value }
    };

    return {
      isError: true, // Marqué comme erreur pour stopper l'exécution automatique
      status: "pending_negotiation",
      content: [{ 
        type: "text", 
        text: `__LAFORGE_YIELD__:${JSON.stringify(yieldPayload)}` 
      }]
    };
  }

  // 2. FAST-FAIL (Vérification de l'organe moteur)
  // On assume ici que les tâches lourdes vont vers le WASM sur 55555
  if (!(await isServiceAlive(55555))) {
    console.error("💥 [Brain] Fast-Fail : Le moteur WASM (55555) est injoignable.");
    return {
      isError: true,
      content: [{ 
        type: "text", 
        text: "Erreur Nokido Proxy : Le moteur WASM (55555) est injoignable. Tâche annulée immédiatement." 
      }]
    };
  }

  // 3. CRÉATION DE LA CELLULE DE SANG
  const cell: BloodCell = {
    jobId,
    traceId,
    organName: mapToolToOrgan(tool.name),
    payload: tool.arguments,
    status: "pending",
    timestamp: Date.now()
  };

  // 4. PROPULSION DANS LE SYSTÈME
  bus.pump(cell);

  // 5. RÉPONSE INSTANTANÉE (Libération du Cerveau)
  return {
    isError: false,
    content: [{ 
      type: "text", 
      text: `🧠 Intention routée avec succès. JobID: ${jobId}. Origine: ${traceId}. L'organe traite la demande en arrière-plan.` 
    }]
  };
}

/**
 * Mapping des outils vers les organes compétents.
 * default_executor → hub_forwarder.ts relaye vers hub :8766.
 */
function mapToolToOrgan(toolName: string): string {
  // WASM / index FAISS
  if (toolName.includes("wasm") || toolName.includes("index")) return "wasm_organ";
  // CTF / sécurité offensive
  if (toolName.includes("exegol") || toolName.includes("ctf") || toolName.includes("pwn")) return "exegol_organ";
  // Tout le reste → hub_forwarder → hub :8766
  return "default_executor";
}
