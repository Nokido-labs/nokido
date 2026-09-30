import { bus, BloodCell } from "../core/nervous_system.ts";

/**
 * Organe WASM : Exécution éphémère de modules WebAssembly.
 *
 * payload attendu dans BloodCell :
 *   { wasm_b64: string }          → module WASM encodé base64
 *   { wasm_url: string }          → URL du binaire WASM
 *   { func: string }              → nom de la fonction exportée (défaut: "run")
 *   { args?: number[] }           → arguments i32 (défaut: [])
 *
 * Résultat : { return_value: number | null, duration_ms: number }
 *
 * Deno supporte WebAssembly nativement — zéro dépendance externe.
 * Exécution isolée : chaque job instancie un module fresh, pas de state partagé.
 */

const MAX_WASM_SIZE = 4 * 1024 * 1024; // 4 MB limit

async function loadWasmBytes(payload: Record<string, unknown>): Promise<Uint8Array> {
  if (typeof payload.wasm_b64 === "string") {
    // base64 → bytes
    const binary = atob(payload.wasm_b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    if (bytes.length > MAX_WASM_SIZE) throw new Error(`WASM trop grand: ${bytes.length} bytes`);
    return bytes;
  }
  if (typeof payload.wasm_url === "string") {
    const resp = await fetch(payload.wasm_url, { signal: AbortSignal.timeout(10_000) });
    if (!resp.ok) throw new Error(`WASM fetch error: ${resp.status}`);
    const buf = await resp.arrayBuffer();
    if (buf.byteLength > MAX_WASM_SIZE) throw new Error(`WASM trop grand: ${buf.byteLength} bytes`);
    return new Uint8Array(buf);
  }
  throw new Error("payload doit contenir wasm_b64 ou wasm_url");
}

bus.subscribe("wasm_organ", async (cell: BloodCell) => {
  if (cell.status !== "pending") return;

  const t0 = Date.now();
  const payload = (cell.payload ?? {}) as Record<string, unknown>;
  const funcName = (payload.func as string) ?? "run";
  const args = Array.isArray(payload.args) ? (payload.args as number[]) : [];

  try {
    const wasmBytes = await loadWasmBytes(payload);

    // Compile + instancie en RAM (éphémère — détruit après résultat)
    // `as BufferSource` (neutre : loadWasmBytes rend deja un Uint8Array) leve
    // l'ambiguite de surcharge — sans lui le compilateur choisit la variante
    // Module, qui ne porte pas `.instance`.
    const { instance } = await WebAssembly.instantiate(wasmBytes as BufferSource, {
      env: {
        // imports minimalistes : les modules simples n'en ont pas besoin
        memory: new WebAssembly.Memory({ initial: 1 }),
        abort: () => { throw new Error("WASM abort()"); },
      },
    });

    const fn = (instance.exports as Record<string, unknown>)[funcName];
    if (typeof fn !== "function") {
      throw new Error(`Fonction '${funcName}' non exportée. Exports: ${Object.keys(instance.exports).join(", ")}`);
    }

    const returnValue = fn(...args);
    const duration_ms = Date.now() - t0;

    bus.pump({
      ...cell,
      status: "completed",
      result: { return_value: returnValue ?? null, duration_ms, func: funcName },
      timestamp: Date.now(),
    });
  } catch (err) {
    bus.pump({
      ...cell,
      status: "failed",
      error: (err as Error).message,
      timestamp: Date.now(),
    });
  }
});
