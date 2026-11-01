/**
 * supervisor_arret_test.ts — Tests d'arrêt garanti des processus supervisés.
 *
 * Joué par : deno test -A proxy_deno/core/supervisor_arret_test.ts
 */

import { arreterVraiment } from "./supervisor_arret.ts";

function verifier(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

Deno.test("arreterVraiment : cas 1 - processus normal stoppe et proc.status resolu", async () => {
  const proc = new Deno.Command(Deno.execPath(), {
    args: ["eval", "setTimeout(()=>{}, 60000)"],
    stdout: "null",
    stderr: "null",
  }).spawn();

  const pid = proc.pid;
  const res = await arreterVraiment(proc, pid, 5000);

  verifier(
    res === "ARRETE" || res === "FORCE",
    `Attendu "ARRETE" ou "FORCE", recu "${res}"`,
  );

  const status = await proc.status;
  verifier(
    typeof status.code === "number" || status.signal !== undefined,
    "proc.status doit etre resolu",
  );
});

Deno.test(
  "arreterVraiment : cas 2 - processus ignorant SIGTERM (sous Windows SIGTERM = TerminateProcess, se ramene au premier)",
  async () => {
    // Note d'architecture / OS :
    // Sous Windows, Deno ne dispose pas de signaux POSIX : kill("SIGTERM") est implemente
    // via TerminateProcess(handle), qui termine immediatement le processus sans qu'il ne
    // puisse intercepter ou ignorer le signal. Le cas se ramene donc au premier sous Windows
    // et rend "ARRETE".
    // Sous Unix (Linux / macOS), le processus ignore le signal SIGTERM via addSignalListener,
    // ce qui declenche l'escalade SIGKILL apres attenteMs et rend "FORCE".
    // Dans les deux cas, le resultat attendu est "ARRETE" ou "FORCE", et proc.status doit etre resolu.
    const proc = new Deno.Command(Deno.execPath(), {
      args: [
        "eval",
        `
        try {
          Deno.addSignalListener("SIGTERM", () => {
            // ignore SIGTERM volontairement sur les OS POSIX
          });
        } catch (_) {
          // Sur Windows, addSignalListener("SIGTERM") leve ou n'est pas supporte
        }
        setTimeout(() => {}, 60000);
        `,
      ],
      stdout: "null",
      stderr: "null",
    }).spawn();

    const pid = proc.pid;
    const res = await arreterVraiment(proc, pid, 1000);

    verifier(
      res === "ARRETE" || res === "FORCE",
      `Attendu "ARRETE" ou "FORCE", recu "${res}"`,
    );

    const status = await proc.status;
    verifier(
      typeof status.code === "number" || status.signal !== undefined,
      "proc.status doit etre resolu",
    );
  },
);

Deno.test("arreterVraiment : cas 3 - processus deja absent ou nul rend ARRETE sans bloquer", async () => {
  const res = await arreterVraiment(null, null);
  verifier(res === "ARRETE", `Attendu "ARRETE", recu "${res}"`);
});
