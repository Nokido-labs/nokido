# Avant d'AGIR sur un diagnostic — 5 questions (2026-07-16)

Déportée VERBATIM de `RULES_SHARED.md` le 2026-11-04 (owner : « 16 % de contexte au démarrage ») ;
le résumé d'une ligne par règle reste dans `RULES_SHARED.md`.

Symétrique de l'anti-dup : celui-ci protège l'ÉDITION, celle-ci protège l'ACTION.
Cause UNIQUE des 3 régressions mesurées ce jour-là : **traiter sa propre sortie comme
vérifiée** — un capteur qu'on vient d'écrire, une sonde ponctuelle, une impression.
Chaque point ci-dessous porte un fait mesuré, pas un conseil.

1. **Capteur neuf = SUSPECT, pas témoin.** La sortie d'un module qu'on vient d'écrire
   se croise avec le LOG DE L'ORGANE **avant** d'agir. Coût du saut : un service SAIN
   arrêté sur un faux positif maison, puis respawn refusé 11× derrière.
2. **Sonde de même DIMENSION que l'affirmation.** Un fait TEMPOREL (« par
   intermittence », « chronique ») se réfute par un LOG, JAMAIS par une lecture à
   l'instant t : un signal qui OSCILLE rend `False` la moitié du temps. Coût : une
   mémoire JUSTE rayée sur une lecture unique, quand le log disait l'inverse.
3. **Le coût des 2 erreurs n'est JAMAIS symétrique.** Rater une dérive = capteur muet.
   En INVENTER une = service sain arrêté. Doute, filiation illisible, mesure
   douteuse → **S'ABSTENIR**. Ne pas accuser.
4. **La propriété se DEMANDE à l'organe, jamais ne se déduit.** Mentent, tous mesurés :
   le RSS (orphelin 665 Mo vs légitime 303 Mo) · l'ÉGALITÉ de pid (`runAs=interactive`
   passe par un LAUNCHER — le registre note le launcher, son ENFANT bind le port) · un
   snapshot à froid (défauts = zéros = « charge nulle » = garde ouvert en silence).
5. **Un garde-fou peut être BON et son diagnostic FAUX.** Corriger le diagnostic,
   jamais contourner le garde. Mesuré : un commentaire interdisait d'amorcer un
   échantillonneur en accusant un subprocess GPU (0.42 ms — hors de cause) ; le vrai
   glouton tenait le GIL 47 % du temps et n'avait jamais été soupçonné.

**Origine d'un processus PROUVÉE, systématiquement (owner 2026-10-28).** Tout gros processus cité dans un
bilan (RAM, CPU, arrêt proposé) porte son origine PROUVÉE : chaîne des parents → pid du superviseur →
service ; un enfant (runner Ollama `llama-server`, worker) est rattaché à son service ; modèle et heure par le
journal du service ; appelant par son journal. Maillon manquant = ILLISIBLE, dit, puis réparé — jamais un arrêt
sur origine supposée. Payé le 28/10 : llama-server 5,69 Go cité « origine non prouvée » (runner NokidoOllama,
deepseek-coder:6.7b, appelant sans trace).

**Geste de l'owner = commande déposée AU TRAY (owner 2026-10-28).** Toute commande que l'owner doit lancer
lui-même part au tray par `demander_ordre ordre=commande-deposer texte=<commande>` — la commande PowerShell
exécutable seule, une par dépôt — en plus d'être citée dans le chat ; jamais seulement dans le chat.

**Décision owner = CHOIX MULTIPLE (owner 2026-10-31, récidive du 18-19/10).** Toute décision qui revient à l'owner
(accord, option A/B, geste irréversible, priorité) se pose en choix multiple — outil de question à options du CLI
(Claude Code : `AskUserQuestion`), une question par décision, la recommandée en premier — jamais une liste en prose
à laquelle il devrait répondre à la main. Le compte rendu reste en prose ; il ne pose pas la question.

**Commande du tray passée = retirée aussitôt (owner 2026-10-28, récidive du 18/10).** Dès qu'une sortie de
l'owner prouve qu'une commande déposée (`demander_ordre commande-deposer`) a tourné :
`demander_ordre ordre=commande-faite cible=<cmd-id> texte=<extrait de la sortie>`, sans attendre qu'il le
redemande. À chaque retour de l'owner, lister `commandes-en-attente` ; avant de déposer, vérifier qu'une
commande équivalente n'attend pas déjà.

**Une délégation se cadre à l'ENTRÉE (owner 2026-10-28).** Toute enquête déléguée suit
[`docs/gabarits/CONSIGNE_DELEGATION_ENQUETE.md`](gabarits/CONSIGNE_DELEGATION_ENQUETE.md) : question
fermée, environnement (Windows), déjà établi / déjà réfuté, sources et ce qui est HORS de portée du bac
(→ ILLISIBLE), livrable en tableau Affirmation | Preuve | État, critères de rejet. Rubrique vide = ne pas
déléguer. Payé le 28/10 : comptes inventés, commandes Linux, cause contredite par le journal.

**Hygiène systématique : ce qu'on réveille, on le rend (owner 2026-10-30).** Tout agent laisse le corps comme il l'a
trouvé, sans qu'on le lui demande : un service réveillé pour SON besoin (Docker, SearXNG, LM Studio, un modèle) est
relâché à la fin, réussite comme échec (réclamation nommée + `release_claim`, jamais un `docker.wanted` orphelin) ;
une tâche qu'il a déposée et qui n'a plus d'objet est CLOSE (`task action=result`, motif + pointeur), jamais laissée
`pending` ; une commande du tray passée est retirée ; un worktree de tâche fini est retiré. Avant de rendre la main :
`tasks.db` (ses tâches non closes), `docker.wanted`, ses services réveillés. Payé le 30/10 : Docker resté allumé
après une recherche ratée, une tâche OPENCODE orpheline 2 h 30 en « délégation ».

**Pas de constat d'échec sans réparation (owner 2026-10-28).** Tout échec, limite ou trou signalé
vient AVEC sa réparation : faite, en cours (job/tâche nommé), ou proposée concrètement (quoi, où,
quel test la prouve, quel accord owner elle demande). Une liste de limites nue renvoie le travail
à l'owner.

**Réflexe : le LOG de l'organe AVANT toute sonde client.** Il porte la dimension TEMPS
que `psutil`/`netstat`/un `print()` n'ont pas. Corollaire : `rag_fts` (étape 1 de
l'anti-dup) n'est PAS redondant avec `forge_deep_explore` — 3 primitives existantes
sorties par le premier, ratées par le second, le même soir.
