<!-- DEPORTE depuis RULES_SHARED.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de RULES_SHARED.md, re-facture a chaque tour. -->

# Une sonde unique ne décide pas — contradiction par les observateurs (2026-09-01)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## Une sonde unique ne décide pas — contradiction par les observateurs (2026-09-01)

Symétrique des deux sections précédentes : celles-ci protègent de la source qui SE TAIT,
celle-ci protège de la source qui PARLE et qu'on croit sur parole parce qu'elle nous
arrange. Trois erreurs mesurées le même soir, toutes de la même forme :

    hypothèse → sonde CONFIRMATOIRE → conclusion
    …pendant qu'un autre observateur, disponible, disait l'inverse.

| Erreur payée | La sonde crue | L'observateur ignoré |
|---|---|---|
| « le job est bloqué » → job TUÉ alors qu'il travaillait | CPU 0,9 s en 6 min | le **WAL à 982 Mo**, horodaté APRÈS le lancement = des écritures |
| « la veille est absente de l'index des agents » | comparaison de `rowid` entre deux FTS | les deux tables n'ont pas le même espace de rowid (`content=` externe vs autonome) — la mesure par `MATCH` disait l'inverse |
| « ces chunks attendent un vecteur » | `embedding IS NULL` | le trigger `forge_tier_guard`, qui en REFUSE 81 % — ils n'attendent rien |

**INVARIANT.** Aucune décision automatique coûteuse ou irréversible ne se fonde sur un
signal UNIQUE quand plusieurs observateurs indépendants existent. Et le premier réflexe
n'est pas de chercher une confirmation, c'est de chercher **ce qui contredirait**.

Formes concrètes, à appliquer telles quelles :

- **Un job « ne fait rien »** ne se conclut pas du CPU : un travail I/O-bound a un CPU
  quasi nul. Croiser CPU · croissance du WAL/des fichiers · PID vivant · compteur de
  progrès. Un rebuild FTS de 700 k documents est I/O-bound, pas CPU-bound.
- **`embedding IS NULL` n'est JAMAIS `FAILED`.** Sans événement d'échec émis par le
  producteur, les états honnêtes sont `PENDING` / `REFUSED_BY_POLICY` / `UNKNOWN`.
  `FAILED` deviendra une mesure le jour où la chaîne émettra `embedding_attempted` /
  `_succeeded` / `_failed` / `_deferred`, et pas avant.
- **Deux index ne se comparent pas par leurs identifiants internes** mais par leur
  CONTENU (`MATCH` sur un terme témoin). Un `rowid` n'a de sens que dans sa table.
- **Deux `COUNT` en autocommit sont deux snapshots.** Un écart se mesure dans UNE
  transaction, sinon l'écart mesuré est l'activité concurrente.

Corollaire de conception : quand une couche expose l'état d'un canal, elle expose aussi
**pourquoi** le signal manque. Un score absent traité en score NUL fait conclure à la
non-pertinence de ce qu'on n'a pas pu voir (cf. `forge_memory_availability`).

**Ce que vaut un garde — et ce qu'il ne prouve pas.** Un garde n'est utile que s'il a
(a) un signal FIABLE, (b) une portée DÉFINIE, (c) un effet OBSERVABLE. Un mécanisme
présent mais non câblé est une **dette de câblage**, jamais une sécurité : même famille
que `FAILED` sans émetteur ou qu'un `structure_status` pour un canal qui n'est branché
nulle part. **Ne jamais confondre l'existence d'un mécanisme avec son effet réel.**

**Et la discipline symétrique, côté agent : détecté ≠ prioritaire ≠ autorisé à modifier.**
Qu'un garde SIGNALE quelque chose ne fait pas de cette chose le prochain chantier, et
encore moins une autorisation d'y toucher. Un signalement qui « ressemble » au problème
du jour est précisément celui qu'on traite par réflexe, hors périmètre et sans mandat.

Validation en conditions réelles (2026-09-01) : un agent a posé un fait de session
préfixé `CURRENT:` dans le SSoT roadmap — or `current_milestone` est un SINGLETON, le
fait allait donc **écraser le jalon du projet**. Exactement l'incident du 2026-08-10
(« mon arbitrage Qdrant a écrasé `current_milestone` »). `hook_recon_first` a arrêté
l'appel, `forge_symptom_index` a ressorti l'incident, le fait a été requalifié en `P1:`
AVANT mutation. **Un travail de session est un item P1/P2 ; `CURRENT:` et `NEXT:` disent
l'état global du projet et n'appartiennent à aucune session.**

