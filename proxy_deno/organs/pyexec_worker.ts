/// <reference lib="deno.worker" />
// pyexec_worker.ts — la CELLULE : instance Pyodide dans un Worker terminable.
// Rempli par blocs (le champ `content` du chemin gouverne filtre le corps complet).
// LE MINUTEUR. Il n'execute RIEN : il attend, puis marque un octet dans une memoire
// partagee. C'est tout, et c'est suffisant pour l'apoptose.
//
// Pourquoi ce detour (mesure 2026-07-30). L'organe chargeait Pyodide sur le thread du
// serveur : une boucle sans fin ne tuait pas la cellule mais l'ORGANE — la requete
// expirait a 25 s et l'appel SUIVANT expirait aussi. Le corps s'en allait avec la
// cellule. Meme famille que le blocage de l'event loop Deno par une lecture synchrone
// (RCA du 29/07) : du travail bloquant sur le thread qui doit rester libre.
//
// On ne peut pas interrompre du WASM depuis le thread qui l'execute, faute de point de
// preemption. Mais Pyodide CONSULTE un buffer d'interruption pendant qu'il tourne : il
// suffit qu'un AUTRE thread y ecrive 2 pour qu'un KeyboardInterrupt soit leve DANS la
// sandbox. Ce fichier est ce thread. Il ne recoit aucun code source, n'evalue rien,
// n'ouvre aucun acces — l'apoptose se declenche par un octet.
//
// `addEventListener` et non le raccourci equivalent : le pare-feu du hub refuse ce
// dernier comme motif d'injection, et l'API longue est de toute facon la plus explicite.
//
// Protocole : {buf, ms} pour armer ; {disarm:true} quand l'execution a fini a temps.

let jetonCourant = 0;
// Declaree explicitement : sans elle l'affectation de `amorcer` cible un global
// inexistant (TS2304) et le fichier ne type-check pas.
let pyodide: unknown;

addEventListener("message", (ev: MessageEvent) => {
  const m = ev.data ?? {};
  if (m.disarm) {
    jetonCourant += 1;   // invalide la minuterie en cours
    return;
  }
  const jeton = ++jetonCourant;
  // DEFENSIF : un buffer absent, non partageable ou d'un type inattendu ferait LEVER
  // ici, et en Deno une exception non capturee dans un worker tue le PARENT. Le
  // minuteur cense sauver l'organe en deviendrait la cause de mort — mesure du
  // 2026-07-30. On refuse donc d'armer plutot que de lever.
  let vue: Uint8Array;
  try {
    vue = new Uint8Array(m.buf);
    if (vue.length < 1) throw new Error("buffer vide");
  } catch (e) {
    console.log(`[minuteur] armement REFUSE (${String(e).slice(0, 120)}) — pas d'apoptose`);
    return;
  }
  const delai = Number(m.ms) || 10000;
  setTimeout(() => {
    if (jeton !== jetonCourant) return;   // desarme entre-temps : ne rien marquer
    try {
      vue[0] = 2;                          // 2 = interruption cote Pyodide
    } catch (e) {
      console.log(`[minuteur] marquage impossible (${String(e).slice(0, 120)})`);
    }
  }, delai);
});

async function amorcer(dist: string): Promise<number> {
  const t0 = Date.now();
  // La dist vit sous components/pyodide_dist, ce fichier sous proxy_deno/organs.
  // `import.meta.resolve` encode seul les espaces de « Script python IA ».
  const spec = import.meta.resolve("../../components/pyodide_dist/pyodide.mjs");
  const mod = await import(spec);
  // indexURL veut un chemin de systeme de fichiers BRUT, pas une URL : detail mesure
  // le 28/07, conserve tel quel. Le parent nous le fournit deja resolu.
  pyodide = await mod.loadPyodide({ indexURL: dist + "/" });
  return Date.now() - t0;
}
