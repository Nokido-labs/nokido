/**
 * supervisor_exit.ts — Classification des sorties de processus pour le superviseur.
 *
 * Contrat : config/codes_sortie_organes.json
 * Enquête : docs/enquete_skill_curator_faux_crash.md (2026-10-20)
 *
 * Une sortie d'organe avec le code INSTANCE_DEJA_VIVANTE (75) est une sortie
 * VOLONTAIRE (garde d'instance unique). Ce n'est pas un crash : elle ne doit
 * ni incrémenter quickFailCount, ni déclencher scheduleRestart, ni envoyer le
 * service en quarantaine.
 */

export interface CodesSortie {
  INSTANCE_DEJA_VIVANTE: number;
}

export const CODES_SORTIE_DEFAUT: CodesSortie = {
  INSTANCE_DEJA_VIVANTE: 75,
};

export type TypeSortie = "instance_deja_vivante" | "echec_rapide" | "sortie";

/**
 * Fonction pure classant la sortie d'un processus supervisé.
 */
export function classerSortie(
  code: number | null,
  elapsedMs: number,
  codes: { INSTANCE_DEJA_VIVANTE: number },
  seuilRapideMs: number,
): "instance_deja_vivante" | "echec_rapide" | "sortie" {
  if (code !== null && code === codes.INSTANCE_DEJA_VIVANTE) {
    return "instance_deja_vivante";
  }
  if (elapsedMs < seuilRapideMs) {
    return "echec_rapide";
  }
  return "sortie";
}

/**
 * Lit le contrat JSON des codes de sortie d'organes.
 * En cas d'erreur de lecture ou de parsing, renvoie la valeur de repli (75)
 * sans jamais lever d'exception pouvant faire échouer le superviseur.
 */
export function chargerCodesSortie(chemin: string): CodesSortie {
  try {
    const raw = Deno.readTextFileSync(chemin);
    const parsed = JSON.parse(raw);
    const val = Number(parsed?.INSTANCE_DEJA_VIVANTE);
    if (Number.isInteger(val)) {
      return { INSTANCE_DEJA_VIVANTE: val };
    }
  } catch {
    // Repli silencieux et robuste sur le contrat par défaut
  }
  return { ...CODES_SORTIE_DEFAUT };
}
