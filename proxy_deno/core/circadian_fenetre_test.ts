// Test du tir circadien par FENETRE (19/10). Lancer : deno test proxy_deno/core/circadian_fenetre_test.ts
// Mesure 19/10 02:06 : NREM3 n'a pas tire dans sa fenetre 02-04 h -- son dernier tir etait un RATTRAPAGE de la
// veille a ~10:27, et la regle « dernier tir >= 20 h » le bloquait (15,6 h). Le cycle restait decale pour toujours.
import { debutFenetre, doitTirer } from "./circadian_fenetre.ts";

function verifie(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

const s = (d: Date) => d.getTime() / 1000;

Deno.test("un rattrapage hors fenetre ne bloque plus la fenetre de la nuit", () => {
  const maintenant = new Date(2026, 9, 19, 2, 7);
  const rattrapage = new Date(2026, 9, 18, 10, 27);
  verifie(doitTirer("NREM3", s(rattrapage), maintenant), "NREM3 doit tirer a 02:07 apres un rattrapage a 10:27");
});

Deno.test("une phase deja tiree dans sa fenetre ne tire pas deux fois", () => {
  const maintenant = new Date(2026, 9, 19, 2, 30);
  verifie(!doitTirer("NREM3", s(new Date(2026, 9, 19, 2, 1)), maintenant), "deja tiree a 02:01");
});

Deno.test("NREM1 traverse minuit : la fenetre a commence la veille a 22 h", () => {
  const maintenant = new Date(2026, 9, 19, 1, 0);
  verifie(debutFenetre("NREM1", maintenant).getTime() === new Date(2026, 9, 18, 22, 0).getTime(), "debut 22 h veille");
  verifie(!doitTirer("NREM1", s(new Date(2026, 9, 18, 22, 5)), maintenant), "tiree a 22:05 : pas de second tir");
  verifie(doitTirer("NREM1", s(new Date(2026, 9, 17, 23, 0)), maintenant), "tiree l'avant-veille : tire");
});

Deno.test("jamais tiree : tire", () => {
  verifie(doitTirer("REM", undefined, new Date(2026, 9, 19, 4, 10)), "etat vierge");
});
