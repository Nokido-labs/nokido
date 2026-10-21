// Tir circadien par FENETRE (19/10, P0 circadien). Pur : aucune E/S, aucun etat.
//
// Mesure 19/10 02:06 : NREM3 n'a pas tire dans sa fenetre 02-04 h. Son dernier tir etait un RATTRAPAGE (CATCHUP)
// de la veille vers 10:27, et la boucle exigeait « dernier tir >= 20 h » : 15,6 h, rien. Le rattrapage suivant
// aurait de nouveau tire a contretemps -- cycle decale pour toujours, NightTrainer/OfflineTrainer jamais reveilles
// la nuit. La bonne question n'est pas « depuis combien d'heures » mais « a-t-elle deja tire dans CETTE fenetre ».

export type PhaseCirc = "AURORE" | "JOUR" | "CREPUSCULE" | "NREM1" | "NREM3" | "REM";

// Debut de chaque fenetre (heure locale) -- meme decoupage que currentPhase() du superviseur.
const DEBUT_H: Record<PhaseCirc, number> = {
  AURORE: 6, JOUR: 9, CREPUSCULE: 18, NREM1: 22, NREM3: 2, REM: 4,
};

/** Debut de la DERNIERE occurrence de la fenetre de `phase` a `maintenant` (NREM1 traverse minuit). */
export function debutFenetre(phase: PhaseCirc, maintenant: Date = new Date()): Date {
  const d = new Date(maintenant.getFullYear(), maintenant.getMonth(), maintenant.getDate(), DEBUT_H[phase], 0, 0, 0);
  if (d.getTime() > maintenant.getTime()) d.setDate(d.getDate() - 1);
  return d;
}

/** Vrai si `phase` (la phase COURANTE) n'a pas encore tire depuis le debut de sa fenetre. Jamais tiree -> vrai. */
export function doitTirer(phase: PhaseCirc, dernierTirS: number | undefined, maintenant: Date = new Date()): boolean {
  if (!dernierTirS) return true;
  return dernierTirS * 1000 < debutFenetre(phase, maintenant).getTime();
}
