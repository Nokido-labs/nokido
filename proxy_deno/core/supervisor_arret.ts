/**
 * supervisor_arret.ts — Arrêt réel et garanti des processus supervisés.
 *
 * Enquête : docs/enquete_skill_curator_relance_0813.md (2026-10-21)
 *
 * Sous Windows, un simple `proc.kill("SIGTERM")` ou l'absence d'escalade SIGKILL
 * peut laisser un processus survivre silencieusement en arrière-plan.
 * De plus, si le processus est un lanceur (runAs=interactive), son enfant
 * tient le travail réel dans la session console : tuer le lanceur seul
 * orpheline l'enfant. Il faut alors tuer l'arbre entier via `taskkill /PID <pid> /T /F`.
 */

export type ResultatArret = "ARRETE" | "FORCE" | "SURVIT";

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Vérifie si un PID répond encore sur le système.
 * Sous Windows : utilise `tasklist /FI "PID eq <pid>"` (ne tue jamais par nom d'image).
 * Sous Unix : utilise `kill -0 <pid>`.
 */
export async function estPidVivant(
  pid: number | null | undefined,
): Promise<boolean> {
  if (!pid || pid <= 0) return false;
  if (Deno.build.os === "windows") {
    try {
      const out = await new Deno.Command("tasklist", {
        args: ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"],
        stdout: "piped",
        stderr: "null",
      }).output();
      if (!out.success) return false;
      const text = new TextDecoder().decode(out.stdout);
      const lines = text.split(/\r?\n/);
      for (const line of lines) {
        const match = line.match(/^"([^"]+)","(\d+)"/);
        if (match && parseInt(match[2], 10) === pid) {
          return true;
        }
        if (line.includes(`"${pid}"`)) {
          return true;
        }
      }
      return false;
    } catch {
      return false;
    }
  } else {
    try {
      const out = await new Deno.Command("kill", {
        args: ["-0", String(pid)],
        stdout: "null",
        stderr: "null",
      }).output();
      return out.success;
    } catch {
      return false;
    }
  }
}

/**
 * Tue l'arbre complet d'un processus sous Windows (`taskkill /PID <pid> /T /F`).
 * Ne JAMAIS tuer par nom d'image.
 */
export async function tuerArbreWindows(pid: number): Promise<boolean> {
  if (!pid || pid <= 0) return false;
  try {
    const cmd = new Deno.Command("taskkill", {
      args: ["/PID", String(pid), "/T", "/F"],
      stdout: "null",
      stderr: "null",
    });
    const out = await cmd.output();
    return out.success;
  } catch {
    return false;
  }
}

/**
 * Attend que le processus `proc` termine (ou que `pid` ne réponde plus),
 * dans la limite de `maxMs`.
 */
async function attendreArret(
  proc: Deno.ChildProcess | null | undefined,
  pid: number | null | undefined,
  maxMs: number,
): Promise<boolean> {
  if (proc) {
    let timer: number | undefined;
    const timeoutPromise = new Promise<boolean>((resolve) => {
      timer = setTimeout(() => resolve(false), maxMs);
    });
    const statusPromise = proc.status.then(() => true).catch(() => true);
    const ok = await Promise.race([statusPromise, timeoutPromise]);
    if (timer !== undefined) clearTimeout(timer);
    return ok;
  }
  if (pid) {
    const debut = Date.now();
    while (Date.now() - debut < maxMs) {
      if (!(await estPidVivant(pid))) return true;
      await delay(50);
    }
    return !(await estPidVivant(pid));
  }
  return true;
}

/**
 * Arrête réellement un processus supervisé :
 * 1. SIGTERM gracieux avec attente de `proc.status` bornée par `attenteMs`.
 * 2. Si le processus ne quitte pas : escalade SIGKILL (avec `taskkill /PID <pid> /T /F` sous Windows)
 *    et nouvelle attente bornée.
 * 3. Si le processus suivi est un lanceur sous Windows (runAs=interactive), tue l'arbre
 *    pour que l'enfant ne survive pas orphelin.
 * 4. Si le PID répond encore après escalade -> "SURVIT".
 */
export async function arreterVraiment(
  proc?: Deno.ChildProcess | null,
  pid?: number | null,
  attenteMs = 5000,
  estLanceur = false,
): Promise<ResultatArret> {
  const targetPid = pid ?? proc?.pid ?? null;
  if (!proc && !targetPid) {
    return "ARRETE";
  }

  // Cas particulier : Lanceur sous Windows (runAs=interactive : son ENFANT tient le travail)
  // Tuer directement l'arbre complet (/T /F) pour éviter d'orpheliner l'enfant console.
  if (Deno.build.os === "windows" && estLanceur && targetPid) {
    await tuerArbreWindows(targetPid);
    await attendreArret(proc, targetPid, attenteMs);
    const survit = await estPidVivant(targetPid);
    return survit ? "SURVIT" : "FORCE";
  }

  // Étape 1 : SIGTERM gracieux
  if (proc) {
    try {
      proc.kill("SIGTERM");
    } catch {
      // Déjà terminé
    }
  } else if (targetPid) {
    try {
      Deno.kill(targetPid, "SIGTERM");
    } catch {
      // Déjà terminé
    }
  }

  // Attente de sortie bornée par attenteMs
  const termineTerm = await attendreArret(proc, targetPid, attenteMs);
  if (termineTerm) {
    if (targetPid) {
      const vivant = await estPidVivant(targetPid);
      if (!vivant) return "ARRETE";
    } else {
      return "ARRETE";
    }
  }

  // Étape 2 : Escalade SIGKILL forcé
  if (Deno.build.os === "windows" && targetPid) {
    // Sous Windows, force-kill l'arbre complet par taskkill /PID <pid> /T /F
    await tuerArbreWindows(targetPid);
    if (proc) {
      try {
        proc.kill("SIGKILL");
      } catch {
        // Ignorer
      }
    }
  } else {
    if (proc) {
      try {
        proc.kill("SIGKILL");
      } catch {
        // Ignorer
      }
    } else if (targetPid) {
      try {
        Deno.kill(targetPid, "SIGKILL");
      } catch {
        // Ignorer
      }
    }
  }

  // Nouvelle attente bornée
  await attendreArret(proc, targetPid, attenteMs);

  // Étape 3 : Vérification finale si le pid répond encore
  if (targetPid) {
    const survit = await estPidVivant(targetPid);
    if (survit) {
      return "SURVIT";
    }
  }

  return "FORCE";
}
