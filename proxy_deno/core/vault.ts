import { join } from "https://deno.land/std/path/mod.ts";

/**
 * Nokido Vault : Gestionnaire sécurisé des variables d'environnement.
 * Charge les secrets en RAM et empêche l'accès direct au disque par l'IA.
 */

let envVault = new Map<string, string>();
const envFiles = ["Nokido.env", ".env"];
const rootDir = join(Deno.cwd(), "..");

/**
 * Charge les fichiers .env en mémoire
 */
export async function reloadEnvToMemory() {
  const newVault = new Map<string, string>();
  
  for (const fileName of envFiles) {
    const filePath = join(rootDir, fileName);
    try {
      const content = await Deno.readTextFile(filePath);
      console.log(`🔒 [Vault] Chargement de ${fileName}...`);
      
      content.split("\n").forEach(line => {
        const [key, ...valueParts] = line.split("=");
        if (key && valueParts.length > 0) {
          const value = valueParts.join("=").trim().replace(/^['"]|['"]$/g, "");
          newVault.set(key.trim(), value);
        }
      });
    } catch (_err) {
      // Le fichier peut ne pas exister, on passe au suivant
    }
  }
  
  envVault = newVault;
  console.log(`🔒 [Vault] ${envVault.size} variables chargées en mémoire.`);
}

/**
 * Surveille les modifications manuelles des fichiers .env
 */
export async function watchEnvFiles() {
  for (const fileName of envFiles) {
    const filePath = join(rootDir, fileName);
    try {
      const watcher = Deno.watchFs(filePath);
      console.log(`🔒 [Vault] Watcher actif sur ${fileName}`);
      
      (async () => {
        for await (const event of watcher) {
          if (event.kind === "modify" || event.kind === "create") {
            console.log(`🔒 [Vault] Détection modification sur ${fileName}. Rechargement...`);
            await reloadEnvToMemory();
          }
        }
      })();
    } catch (_err) {
      // Si le fichier n'existe pas encore, on ne peut pas le watcher
    }
  }
}

/**
 * Récupère une variable du Vault
 */
export function getVaultVar(key: string): string | undefined {
  return envVault.get(key);
}

/**
 * Met à jour une variable (Ecriture disque + RAM)
 * NOTE: Cette fonction ne doit être appelée qu'après approbation humaine (Yield).
 */
export async function setVaultVar(key: string, value: string) {
  envVault.set(key, value);
  
  // On écrit par défaut dans Nokido.env
  const filePath = join(rootDir, "Nokido.env");
  let content = "";
  try {
    content = await Deno.readTextFile(filePath);
  } catch (_err) {
    // Si absent, on va le créer
  }
  
  const lines = content.split("\n");
  let found = false;
  const newLines = lines.map(line => {
    if (line.startsWith(`${key}=`)) {
      found = true;
      return `${key}=${value}`;
    }
    return line;
  });
  
  if (!found) {
    newLines.push(`${key}=${value}`);
  }
  
  await Deno.writeTextFile(filePath, newLines.join("\n"));
  console.log(`🔒 [Vault] Variable ${key} mise à jour sur disque.`);
}

// Initialisation au chargement du module
await reloadEnvToMemory();
watchEnvFiles();
