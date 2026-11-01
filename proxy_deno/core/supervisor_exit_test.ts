/**
 * supervisor_exit_test.ts — Tests de la classification des sorties de processus.
 *
 * Joué par : deno test -A proxy_deno/core/supervisor_exit_test.ts
 */

import { fromFileUrl, join } from "https://deno.land/std@0.224.0/path/mod.ts";
import {
  chargerCodesSortie,
  classerSortie,
} from "./supervisor_exit.ts";

const ROOT = fromFileUrl(new URL("../../", import.meta.url)).replace(/[\\/]$/, "");
const CONTRAT_PATH = join(ROOT, "config", "codes_sortie_organes.json");

function verifier(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

Deno.test("chargerCodesSortie : lit le VRAI config/codes_sortie_organes.json", () => {
  const codes = chargerCodesSortie(CONTRAT_PATH);
  verifier(
    codes.INSTANCE_DEJA_VIVANTE === 75,
    `Attendu INSTANCE_DEJA_VIVANTE = 75, recu ${codes.INSTANCE_DEJA_VIVANTE}`,
  );
});

Deno.test("chargerCodesSortie : repli sur 75 sans throw si fichier illisible ou absent", () => {
  const fauxChemin = join(ROOT, "config", "fichier_totalement_inexistant.json");
  const repli = chargerCodesSortie(fauxChemin);
  verifier(
    repli.INSTANCE_DEJA_VIVANTE === 75,
    `Attendu repli 75, recu ${repli.INSTANCE_DEJA_VIVANTE}`,
  );
});

Deno.test("classerSortie : 75 en 70 ms -> instance_deja_vivante", () => {
  const codes = chargerCodesSortie(CONTRAT_PATH);
  const res = classerSortie(75, 70, codes, 30_000);
  verifier(res === "instance_deja_vivante", `Attendu instance_deja_vivante, recu ${res}`);
});

Deno.test("classerSortie : 1 en 70 ms -> echec_rapide", () => {
  const codes = chargerCodesSortie(CONTRAT_PATH);
  const res = classerSortie(1, 70, codes, 30_000);
  verifier(res === "echec_rapide", `Attendu echec_rapide, recu ${res}`);
});

Deno.test("classerSortie : 0 en 70 ms -> echec_rapide (comportement actuel conserve)", () => {
  const codes = chargerCodesSortie(CONTRAT_PATH);
  const res = classerSortie(0, 70, codes, 30_000);
  verifier(res === "echec_rapide", `Attendu echec_rapide, recu ${res}`);
});

Deno.test("classerSortie : 1 apres 60 s -> sortie", () => {
  const codes = chargerCodesSortie(CONTRAT_PATH);
  const res = classerSortie(1, 60_000, codes, 30_000);
  verifier(res === "sortie", `Attendu sortie, recu ${res}`);
});

Deno.test("classerSortie : 75 apres 60 s -> instance_deja_vivante", () => {
  const codes = chargerCodesSortie(CONTRAT_PATH);
  const res = classerSortie(75, 60_000, codes, 30_000);
  verifier(res === "instance_deja_vivante", `Attendu instance_deja_vivante, recu ${res}`);
});
