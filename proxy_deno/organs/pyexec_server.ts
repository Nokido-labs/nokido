// pyexec_server.ts — serveur Pyodide AUTONOME (Phase B, 2026-07-28).
//
// But (exigence owner) : executer le code Python genere par le CLI EN WASM, sans
// laisser de trace sur le disque hote. Prouve faisable ce jour (2+3=5, dist locale).
//
// Autonome par CHOIX : un serveur DEDIE sur son propre port, JAMAIS greffe dans le
// runner web_hub :7401 (le nerf). Si Pyodide plante ou fuit, il tombe seul et le
// superviseur le releve ; le hub et le web_hub ne sont pas touches.
//
// Charge la dist LOCALE (components/pyodide_dist, asset permanent hors /tmp) une
// seule fois au boot, puis sert POST /pyexec {code} -> {ok, stdout, result, error}.
// Le code s'execute dans la sandbox WASM Pyodide : pas d'acces au FS hote, pas
// d'ecriture disque. Deux details mesures le 28/07 : indexURL = chemin fs BRUT (pas
// file://), et --unstable-detect-cjs requis (pyodide.asm.js est du CommonJS).

const PORT = Number(Deno.env.get("LAFORGE_PYEXEC_PORT") ?? "7402");

// ── JOURNAL PROPRE (P0 du 2026-07-30) ─────────────────────────────────────────
// Cet organe n'avait AUCUNE cible de log declaree : sa sortie allait au neant, et sa
// mort — mesuree deux fois ce jour, a l'instant exact ou l'interruption tirait — n'a
// laisse aucune trace du POURQUOI. « Un organe qui vit sans journal est un organe dont
// la prochaine mort sera tout aussi muette. » On ecrit donc en append, et on capture
// AUSSI les deux voies par lesquelles un runtime Deno s'en va en silence : l'erreur
// globale et la promesse rejetee sans preneur.
// Racine DERIVEE (organs/ -> proxy_deno/ -> depot). Le repli figé "…/LaForge" —
// l'ancien nom du depot — s'appliquait TOUJOURS, `LAFORGE_ROOT` n'etant posee nulle
// part : le journal partait donc lui aussi dans un dossier qui n'existe plus, ce qui
// a rendu la panne du 2026-08-01 doublement invisible (ni port, ni trace).
// `URL.pathname` rend un chemin URL-ENCODE : "Script python IA" y devient
// "Script%20python%20IA", que `Deno.stat` ne trouve pas. Le fichier annoncait deja
// ce piege plus bas ("ni les espaces de Script python IA") — il fallait l'appliquer
// ici aussi. decodeURIComponent AVANT tout usage systeme de fichiers.
const RACINE = Deno.env.get("LAFORGE_ROOT") ??
  decodeURIComponent(new URL("../..", import.meta.url).pathname)
    .replace(/^\/([A-Za-z]:)/, "$1")
    .replace(/\/$/, "");
const JOURNAL = RACINE + "/logs/pyexec_organ.log";
// Faux tant que Pyodide n'est pas charge : sert a distinguer une rejection du TISSU
// (amorcage, fatale) d'une rejection de la CELLULE (code etranger, absorbee).
let PRET = false;
function noter(msg: string) {
  const ligne = `${new Date().toISOString()} ${msg}\n`;
  try {
    Deno.writeTextFileSync(JOURNAL, ligne, { append: true });
  } catch (_) { /* journal best-effort : ne jamais faire mourir l'organe pour sa trace */ }
  console.log(msg);
}
addEventListener("error", (e: Event) => {
  noter(`[FATAL] erreur globale : ${String((e as ErrorEvent).message ?? e).slice(0, 400)}`);
});
addEventListener("unhandledrejection", (e: Event) => {
  const raison = String((e as PromiseRejectionEvent).reason ?? e);
  // CAUSE EXACTE DE LA MORT, lue dans le journal a 05:41:30 : l'interruption ne remonte
  // PAS par la promesse que le serveur attend. Pyodide la leve dans un callback de sa
  // propre webloop (`pyodide/webloop.py:332 run_handle` -> `eval_code_async`), donc
  // AUCUN try/catch autour de `runPythonAsync` ne peut l'attraper. Elle devenait une
  // rejection sans preneur, et Deno TERMINE le process dans ce cas : le remede tuait
  // l'organe qu'il devait sauver.
  //
  // `preventDefault` est donc ce qui rend l'apoptose possible : la cellule meurt, la
  // rejection est absorbee, l'organe continue de servir. Absorber LARGEMENT est ici
  // justifie et non paresseux — cet organe n'a qu'un metier, executer du code etranger
  // en bac a sable, et toute rejection qui en vient est par nature le fait de la
  // cellule, pas du tissu. Elle est journalisee AVANT d'etre absorbee : on n'avale
  // jamais en silence.
  // AMORCAGE vs SERVICE — la distinction manquait, et elle a coute 38 jours de
  // silence (mesure 2026-09-08). Le raisonnement ci-dessus ne vaut QUE pour une
  // cellule deja vivante : tant que Pyodide n'est pas pret, une rejection vient du
  // TISSU (dist introuvable, import casse), pas du code etranger. L'absorber faisait
  // survivre un organe INCAPABLE de servir : port jamais ouvert, journal muet, et le
  // superviseur voyait un process vivant. Une panne d'amorcage doit TUER, fort.
  if (!PRET) {
    console.error("[pyexec] FATAL a l'AMORCAGE (Pyodide pas encore pret) : "
      + raison.slice(0, 400));
    console.error("[pyexec] dist attendue : " + DIST);
    Deno.exit(3);
  }
  const apoptose = /KeyboardInterrupt/i.test(raison);
  noter(`[${apoptose ? "APOPTOSE-webloop" : "FATAL-absorbe"}] rejection sans preneur : `
    + raison.slice(0, 400));
  e.preventDefault();
});
// Chemin de la dist Pyodide locale. Defaut = components/pyodide_dist sous le repo.
// La racine se DERIVE du fichier, elle ne se devine pas. Le repli precedent etait
// "…/Script python IA/LaForge" — l'ANCIEN nom du depot, renomme en Nokido depuis.
// `LAFORGE_ROOT` n'etant posee NULLE PART (ni machine, ni user, ni services.toml),
// ce repli s'appliquait TOUJOURS : la dist Pyodide etait cherchee a un chemin qui
// n'existe plus, alors qu'elle est bien la sous `Nokido/components/pyodide_dist`.
// Mesure du 2026-09-08 : service muet depuis le 2026-08-01 (38 jours), l'erreur
// etant absorbee par le garde `[FATAL-absorbe]` — personne ne l'a jamais vue.
const DIST = (Deno.env.get("LAFORGE_PYODIDE_DIST") ??
  `${RACINE}/components/pyodide_dist`).replace(/\\/g, "/");

// Import DYNAMIQUE : un import statique file:// ne peut pas porter un chemin resolu
// au lancement (ni les espaces de "Script python IA"). indexURL = chemin fs BRUT.
const _mjsUrl = "file:///" + DIST.replace(/ /g, "%20") + "/pyodide.mjs";
console.log(`[pyexec] chargement Pyodide depuis ${DIST} ...`);
const t0 = Date.now();
// Verification EXPLICITE de l'asset : un chemin manquant se dit AVANT l'import,
// avec le chemin en clair, plutot que de ressortir en rejection obscure.
try {
  await Deno.stat(DIST + "/pyodide.mjs");
} catch {
  console.error(`[pyexec] FATAL : dist Pyodide introuvable -> ${DIST}/pyodide.mjs`);
  console.error("[pyexec] poser LAFORGE_PYODIDE_DIST, ou installer la dist sous "
    + "<racine>/components/pyodide_dist");
  Deno.exit(2);
}
const { loadPyodide } = await import(_mjsUrl);
const pyodide = await loadPyodide({ indexURL: DIST + "/" });
PRET = true;
noter(`[pyexec] Pyodide pret en ${Date.now() - t0}ms — port ${PORT}`);

// ── APOPTOSE (mesure 2026-07-30) ──────────────────────────────────────────────
// Defaut corrige : Pyodide tourne sur CE thread, donc une boucle sans fin ne tuait pas
// la cellule mais l'ORGANE — la requete expirait, et l'appel SUIVANT expirait aussi.
// Le corps mourait avec la cellule ; il n'y avait pas d'apoptose, juste une necrose.
//
// Aucun point de preemption n'existe pour interrompre du WASM depuis son propre thread.
// Mais Pyodide CONSULTE un buffer d'interruption pendant l'execution : un AUTRE thread
// y ecrit 2, et un KeyboardInterrupt est leve DANS la sandbox. Le minuteur
// (pyexec_worker.ts) est ce thread — il n'execute aucun code, il marque un octet.
const TIMEOUT_MS = Number(Deno.env.get("LAFORGE_PYEXEC_TIMEOUT_MS") ?? "10000");
const interruptBuf = new Uint8Array(new SharedArrayBuffer(1));
let minuteur: Worker | null = null;
try {
  pyodide.setInterruptBuffer(interruptBuf);
  minuteur = new Worker(new URL("./pyexec_worker.ts", import.meta.url).href,
                        { type: "module" });
  // SANS CET ECOUTEUR L'ORGANE MEURT. Mesure 2026-07-30 : l'interruption tirait bien a
  // 4,05 s, puis le process disparaissait et le port se fermait. En Deno une exception
  // non capturee dans un worker se PROPAGE au parent et le termine — le minuteur cense
  // sauver l'organe devenait la cause de sa mort. On avale donc l'erreur du minuteur en
  // la NOMMANT : perdre l'apoptose est un degradé acceptable, perdre l'organe non.
  minuteur.addEventListener("error", (e: Event) => {
    e.preventDefault();
    console.log(`[pyexec] minuteur en ERREUR — apoptose perdue, organe conserve : `
      + `${String((e as ErrorEvent).message ?? e).slice(0, 200)}`);
  });
  noter(`[pyexec] apoptose ARMEE (timeout ${TIMEOUT_MS}ms)`);
} catch (e) {
  // Sans interruption on SERT QUAND MEME, mais on le DIT : un organe qui se croit
  // protege alors qu'il ne l'est pas est plus dangereux qu'un organe qui l'avoue.
  console.log(`[pyexec] ATTENTION apoptose INDISPONIBLE (${String(e).slice(0, 160)}) — `
    + `une execution sans fin bloquera l'organe`);
}

// Heartbeat fichier : le superviseur lit sandbox/pyexec_server.heartbeat.
const HB = Deno.env.get("LAFORGE_PYEXEC_HB") ?? "";
function beat() {
  if (!HB) return;
  try {
    // `pid` : meme contrat que le canon Python (`forge_heartbeat.beat_daemon`). Sans
  // lui, l'organe atteste d'une vie sans dire QUI la porte, et la topologie ne peut
  // lui attribuer ni hote ni autorite de redemarrage. Cet organe est en Deno, donc
  // hors du canon Python — c'est le CONTRAT qui est partage, pas l'implementation.
  Deno.writeTextFileSync(
    HB,
    JSON.stringify({ ts: new Date().toISOString(), pid: Deno.pid, port: PORT }),
  );
  } catch (_) { /* pouls best-effort */ }
}
beat();
setInterval(beat, 30_000);

globalThis.addEventListener("unload", () => {
  if (HB) {
    try { Deno.removeSync(HB); } catch (_) {}
  }
});

Deno.serve({ port: PORT, hostname: "127.0.0.1" }, async (req) => {
  const url = new URL(req.url);
  if (req.method === "GET" && url.pathname === "/health") {
    return Response.json({ ok: true, backend: "pyodide-wasm", port: PORT });
  }
  if (req.method === "POST" && url.pathname === "/pyexec") {
    let body: { code?: string };
    try {
      body = await req.json();
    } catch {
      return Response.json({ ok: false, error: "JSON body {code} requis" }, { status: 400 });
    }
    const code = body.code ?? "";
    if (!code) return Response.json({ ok: false, error: "code vide" }, { status: 400 });
    // stdout capture DANS la sandbox WASM (pas de fichier hote).
    const budget = Number((body as { timeout_ms?: number }).timeout_ms) || TIMEOUT_MS;
    let out = "";
    // Armement AVANT l'execution : le buffer est remis a zero (une interruption
    // residuelle d'un appel precedent tuerait le suivant a tort) puis le minuteur part.
    interruptBuf[0] = 0;
    minuteur?.postMessage({ buf: interruptBuf.buffer, ms: budget });
    try {
      pyodide.setStdout({ batched: (s: string) => { out += s + "\n"; } });
      pyodide.setStderr({ batched: (s: string) => { out += s + "\n"; } });
      const result = await pyodide.runPythonAsync(code);
      minuteur?.postMessage({ disarm: true });
      noter(`[pyexec] execution OK (${code.length} chars)`);
      // Pouls APRES une execution reussie : atteste du travail, pas de l'existence.
      beat();
      return Response.json({
        ok: true,
        stdout: out,
        result: result === undefined ? null : String(result),
      });
    } catch (e) {
      minuteur?.postMessage({ disarm: true });
      const msg = String(e);
      // On NOMME l'apoptose au lieu de la confondre avec une erreur du code : les deux
      // demandent des suites differentes, l'une revoit le budget, l'autre le programme.
      const apoptose = /KeyboardInterrupt/i.test(msg);
      noter(`[pyexec] ${apoptose ? "APOPTOSE" : "erreur"} : ${msg.slice(0, 300)}`);
      return Response.json({
        ok: false, stdout: out,
        apoptose, timeout_ms: apoptose ? budget : undefined,
        error: apoptose
          ? `apoptose : execution interrompue apres ${budget}ms (cellule detruite, organe intact)`
          : msg.slice(0, 2000),
      });
    } finally {
      // Le buffer NE DOIT PAS rester marque : sinon la cellule suivante naitrait
      // condamnee (defaut classique d'un drapeau d'interruption non reinitialise).
      interruptBuf[0] = 0;
    }
  }
  return new Response("pyexec: POST /pyexec {code} | GET /health", { status: 404 });
});
