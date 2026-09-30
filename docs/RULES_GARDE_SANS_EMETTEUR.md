<!-- DEPORTE depuis RULES_SHARED.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de RULES_SHARED.md, re-facture a chaque tour. -->

# Un garde branché sur un signal que PERSONNE n'émet (2026-07-30)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## Un garde branché sur un signal que PERSONNE n'émet (2026-07-30)

Le corps a des gardes justes, écrits pour de bonnes raisons, qui ne se sont **jamais
déclenchés** — parce que le signal dont ils dépendent n'a pas d'émetteur. Le code se
relit comme protégé, la mesure dit l'inverse. **Deux instances le même jour**, ce qui
en fait un motif et non un accident :

| Garde | Consommateurs | Émetteur | Coût mesuré |
|---|---|---|---|
| `INSULIN_VECTORIZATION > 0.4 → batch_size / 2` (`forge_rag_warmup`) | 1 récepteur déclaré | **aucun** — hormone lue à `0.0` en permanence | frein jamais déclenché depuis son écriture |
| garde d'intention du reclaimer (`forge_resource_manager` step 2b) | 4 lecteurs (reclaimer, keeper ×2, health) | **1 sur 6 réveilleurs** posait `llama.wanted` | 73 arrêts de `llama-server:8091` en 7,6 j, **312,94 Go** rechargés |

**La règle : avant de brancher un garde sur un signal, vérifier qui l'ÉMET.** Un
récepteur, une hormone déclarée et un `if` correct ne prouvent rien — seule une valeur
non nulle lue en conditions réelles le prouve. Corollaire : quand N chemins produisent
un état et qu'UN SEUL le déclare, l'asymétrie est invisible en lecture de code et
visible dans le journal. Le contraste l'a désigné ici : `docker_wanted: True` revient
sans cesse dans les `pause_skipped` et Docker est épargné ; `llama_wanted` ne l'est
jamais et llama se fait arrêter 73 fois. **Deux organes qui lisent le même vocabulaire
d'intention avec des taux d'armement opposés = un déclarant manquant, pas un garde
défaillant.**

Deux pièges de mesure payés dans la même enquête :

1. **La moyenne all-time MENT sur les rafales.** `stop/llama-server:8091` affichait un
   intervalle médian de 736 s (≈1/h, sous un budget de 6/h) alors que 14 de ses
   intervalles étaient sous 300 s, le plus court à 32 s = 112/h instantané. Un débit se
   mesure sur une fenêtre par **COMPTAGE** (les N derniers tirs). Cf.
   `forge_regulation_efficacy`.
2. **Une abstention n'est pas un acte.** Les `*_skipped` reviennent au rythme du tick du
   sampler (~122 s) : c'est la boucle qui re-décide « non ». Les compter comme des tirs
   fait crier au pompage sur un corps qui se retient exactement comme il faut.

Et un piège d'exécution : **une copie figée dans `C:\tmp\` peut piloter le comportement
réel.** `forge_local_pool_wake` lançait `C:/tmp/wake_llama_native.py` (4 722 o, 18 juin)
quand le dépôt en portait 11 825 o (26 juillet) — la copie est ANTÉRIEURE au mécanisme
d'intention, donc elle allumait un cerveau que la régulation évinçait aussitôt. Six
semaines d'écart entre le code qui tourne et le code qu'on relit. Un lanceur pointe le
DÉPÔT ; une copie hors dépôt est un dernier recours qui le DIT.

Outils : `forge_regulation_efficacy` (débit RÉEL vs budget par gravité, verdicts
POMPE / PROCHE DU POMPAGE / RÉGULE / SANS MESURE) — complémentaire de
`forge_regulation_loops`, qui calcule le débit maximal THÉORIQUE depuis les paramètres
déclarés. Un câblage sain sur le papier peut pomper en vrai.

