# Gabarit — consigne d'enquête déléguée (owner 2026-10-28)

> « Il faut qu'en entrée la tâche soit bien définie pour éviter les dérives. » Mesure 28/10 : deux enquêtes
> déléguées ont conclu FAUX — l'une a inventé des comptes (« nokido-keeper », « nokido-watch ») et proposé des
> commandes Linux sur une machine Windows ; l'autre a accusé `startService` alors que le journal du
> superviseur montrait l'inverse. Les consignes ne disaient ni ce qui était déjà établi, ni ce que
> l'exécuteur ne pouvait pas lire, ni qu'une affirmation sans preuve serait rejetée.

Copier ce gabarit dans la description de la tâche (`task assign`) et remplir CHAQUE rubrique. Une rubrique
vide = consigne non prête : ne pas déléguer.

```
[taille S|M] Enquête LECTURE SEULE — <question FERMÉE : réponse attendue PROUVÉ / RÉFUTÉ / ILLISIBLE>

ENVIRONNEMENT : Windows 11 (PowerShell / chemins C:\...), PAS Linux. Comptes : ne nommer un compte que s'il
est LU dans proxy_deno/core/services.toml (runAs) ou dans un journal — jamais déduit.

DÉJÀ ÉTABLI (ne pas re-déduire, citer) :
- <fait mesuré + sa source : fichier:ligne ou ligne de journal avec horodatage>

DÉJÀ RÉFUTÉ (ne pas reproposer) :
- <hypothèse écartée + ce qui la contredit>

SOURCES À LIRE (chemins exacts) : <liste>
HORS DE PORTÉE de ton bac (écrire ILLISIBLE, ne pas supposer) : dossier utilisateur C:\Users\<owner>\,
pipes Docker de la session owner, journaux d'autres comptes, <autre>.

LIVRABLE : <chemin du doc>, structuré ainsi :
| Affirmation | Preuve (fichier:ligne OU ligne de journal recopiée avec son horodatage) | État |
État ∈ {PROUVÉ, RÉFUTÉ, ILLISIBLE}. Puis « Cause » (seulement si PROUVÉE) et « Correctif proposé + NR »
(non appliqué).

REJET AUTOMATIQUE si : une affirmation sans preuve citée ; un compte, chemin ou commande non lu dans une
source ; « cause prouvée » contredite par une source déjà citée ci-dessus ; une conclusion tirée d'une
source muette (absence de ligne ≠ preuve).

INTERDIT : <gestes interdits : redémarrer, lancer Docker, requête sur la base RAG, …>. Claim tree_locks
du doc, commit petit.
```

## Pourquoi chaque rubrique

| Rubrique | Dérive qu'elle bloque (mesurée) |
|---|---|
| Question fermée | une enquête qui « analyse » sans conclure, ou conclut sur autre chose |
| Environnement | `ps -eo`, `/var/run` proposés sur Windows (28/10) |
| Déjà établi | re-déduire faux ce qui était mesuré (« NokidoWatchAgent pas lancé » alors que son journal tournait) |
| Déjà réfuté | reproposer la piste écartée |
| Hors de portée | « existe = non » partout faute de pouvoir lire le dossier utilisateur (6bb0700dc) : ILLISIBLE ≠ NON |
| Tableau Affirmation / Preuve / État | comptes inventés présentés comme « cause prouvée » (5bd04ac61) |
| Rejet automatique | le juge (et moi) rejetons sur la forme avant même le fond |
| Consigne COMPLÈTE en ligne | « voir tasks.db, id job_X, champ description » : inatteignable pour l'agent (sandbox/ hors du worktree de tâche, bash refusé, SQLite illisible par read) — DEFAUT3/5 ont passé leurs tours à chercher tasks.db, RIEN_PRODUIT (29/10, journal OpenCode runs 519ef053, 6707ce61). L'exécuteur résout désormais ce pointeur (`_resoudre_pointeurs_consigne`, c107545a1), mais la consigne s'écrit d'abord en entier |
