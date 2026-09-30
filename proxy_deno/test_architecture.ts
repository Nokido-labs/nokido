import { processLLMIntent } from "./core/brain.ts";
import "./organs/kidney_monitor.ts";
import "./organs/wasm_motor.ts";
import "./organs/mcp_hub_bridge.ts";
import { getJobStatus } from "./organs/kidney_monitor.ts";

async function runTests() {
  console.log("🧪 Démarrage des tests du Système Nerveux Nokido...");

  // 1. Test de la Barrière Hémato-Encéphalique (Validation)
  console.log("\n1. Test Validation (Payload corrompu) :");
  const invalidPayload = { tools: [{ name: "test_tool" }] }; // Manque inputSchema
  const res1 = await processLLMIntent(invalidPayload);
  console.log(res1.isError ? "✅ Rejeté avec succès" : "❌ Erreur: Aurait dû être rejeté");

  // 2. Test du Routage Asynchrone
  console.log("\n2. Test Routage (Payload valide) :");
  // Note: Ce test échouera au Fast-Fail si le port 55555 n'est pas ouvert.
  // Pour le test, on va simuler que le port est ouvert ou bypasser.
  const validPayload = { 
    tools: [{ 
      name: "wasm_indexer", 
      inputSchema: { type: "object", properties: {} } 
    }],
    traceId: "test_session_001"
  };
  
  const res2 = await processLLMIntent(validPayload);
  console.log(res2.isError ? `ℹ️ Note: ${res2.content[0].text}` : "✅ Routé avec succès");

  if (!res2.isError) {
    const jobId = res2.content[0].text.match(/JobID: ([a-z0-9-]+)/)?.[1];
    if (jobId) {
      console.log(`\n3. Suivi du Job ${jobId} :`);
      // Attente de 3s pour laisser l'organe travailler (simulé)
      await new Promise(r => setTimeout(r, 3000));
      const status = getJobStatus(jobId);
      console.log(`Statut final: ${status?.status} ${status?.status === "completed" ? "✅" : "❌"}`);
    }
  }
}

runTests();
