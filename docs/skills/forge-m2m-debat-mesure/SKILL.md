---
name: forge-m2m-debat-mesure
description: Workflow VERIFIE du 2026-08-13 pour (a) debattre entre agents Nokido (Claude <-> Antigravity) sur un canal qui marche reellement, et (b) admettre un axe de detection de regression UNIQUEMENT sur mesure executable (backtest git). Declencher quand un agent propose d etendre la detection de regressions, quand un debat M2M doit etre lance ou repris, quand un pair "ne repond pas", quand un score de couverture semble trop beau (100%, 0 rate), ou avant d ajouter un axe/capteur a forge_regression_sweep. Contient les 7 pieges qui ont coute une journee entiere - canal coupe en deux transports, delivered != lu, deux espaces de noms de providers, sandbox offline qui fait croire qu un tiers est mort, juge LLM qui fabrique des faux-verts a chaque mise en forme, dossier re-envoye a chaque tour, axes admis sans detecteur.
---

# Debat M2M mesure — workflow verifie (2026-08-13)

> Ne pas reconstruire ce workflow : il existe, il tourne, ses pieges sont payes.

## 1. Le canal M2M : ce qui marche, ce qui ment

| Transport | Ce que c est | Verdict mesure |
|---|---|---|
| **Tableau noir** `blackboard_propose_fact` zone `discovered_facts` | fait atomique, cle deterministe (idempotent) | ✅ **SEUL canal ou AGY a lu ET repondu** (`ACK-BACKTEST` recu) |
| **Frames** `frm_*` dans `agent_messages` | ce que `hub action=notify` produit ; ce que le hook de session affiche | ✅ AGY ecrit ici (`to_agent='agt_claude'`) |
| **Postal** `mail_*` (`forge_postal.post`) | facteur/secretaire | ⚠️ **4 tours envoyes, tous `delivered`, ZERO accuse de reception** |

**Regles apprises :**
- `status='delivered'` atteste que le facteur a **depose**, pas qu on a **lu**. Verifier `track(mail_id)['accuse_reception']`, jamais `status`.
- **Deux noms pour la meme boite** : le pair ecrit a `agt_claude`, `secretaire("CLAUDE")` rend `[]`. Relever **les deux identites**.
- Les deux transports ne se parlent pas : une boucle qui n en releve qu un **croit sa boite vide pendant que l autre deborde**.
- Un pair qui "ne repond pas" peut simplement ne pas lire ce canal-la. **Avant d accuser, verifier par ou il a ecrit** (`SELECT ... FROM agent_messages WHERE from_agent LIKE '%ANTIGRAV%' ORDER BY created_at DESC`).

**Forme qui marche** (poser un fait + demander un accuse explicite) :
```
blackboard_propose_fact zone_name=discovered_facts key=<sujet>_<date>
  category=debat trust=0.9 fact="[CLAUDE->AGY] ... Reponds avec le mot ACK-<SUJET>."
```
Puis **verifier l accuse en base**, ne jamais le croire sur parole :
```sql
SELECT id, from_agent, status, created_at FROM agent_messages WHERE payload LIKE '%ACK-<SUJET>%'
```

## 2. L autonomie : capteur vs actionneur

- `pat_m2m_inbox_watch` (dans `app/forge_autonomous_loops.py`) **COMPTE** le courrier qui stagne — sa docstring le dit : « n execute ni ne consomme rien ». C est un **capteur**.
- `pat_m2m_debate_relay` (meme fichier, ajoute le 13/08) est l **ACTIONNEUR** : livre (`facteur` sur `channels_with_pending`), releve **les 2 transports et les 2 identites**, et si le pair a ecrit : backtest local + arene detachee + reponse postee. Cadence bornee (1 tour/h), memoire du dernier courrier traite, frames acquittees apres traitement.
- Test manuel : `LAFORGE_PYTHON app/forge_autonomous_loops.py --run m2m_debate_relay`

## 3. La methode anti-regression : un axe s admet par la MESURE

**Outil** : `tools/forge_axis_backtest.py`
```
LAFORGE_PYTHON tools/forge_axis_backtest.py --since 2026-05-01 --limit 40
LAFORGE_PYTHON tools/forge_axis_backtest.py --axis <nom> --json
```
**Principe** : les **commits de correction** sont une verite terrain gratuite et datee. Pour chaque commit C : rejouer `C~1` et `C`. L axe doit **TIRER avant** et se **TAIRE apres**.

**DEUX criteres d admission** (le rapport dit lequel a joue : `vus_par_ligne` / `vus_par_extinction`) :
1. **ligne reparee** — l axe pointait une ligne modifiee par le fix (hunks de `git diff -U0`, tolerance 2) ;
2. **EXTINCTION** — une alerte presente AVANT a **disparu APRES**. C est le critere **causal** : le fix a fait taire l alerte.

⚠️ **Pourquoi le critere 2 est indispensable — LA CAUSE EST SOUVENT AILLEURS QUE LE SYMPTOME.** Cas reel (13/08) : `ax16` (pyflakes, noms non resolus) criait aux lignes **789 et 807** de `app/forge_conv_indexer.py` (les usages de `sys.`), alors que le fix `a3844d6f` reparait la **ligne 21** (l `import sys` ajoute en tete). Le critere de ligne le comptait **RATE** alors qu il avait vu le vrai defaut ; le critere d extinction le credite (**2 alertes eteintes**). Un axe juge uniquement sur la position rate toutes les pannes dont la reparation est distante du symptome.

**Ajouter un axe** = ecrire un detecteur dans le dict `AXES` :
```python
def ax_mon_axe(src: str, chemin: str) -> list:   # -> [{"file":..., "line": int}, ...]
    ...
AXES = {"ax_mon_axe": ax_mon_axe, ...}
```
Le backtest lui rend **rappel** et **bruit hors-cible** sans discussion possible.

**Resultats de reference (40 commits, 2026-08-13)** — a citer pour couper court a un recensement massif :
- axe « except muet qui avale un signal » (2 969 blocs recenses) → **rappel 0,0 %**, hors cible 18,8 %
- axe « env `LAFORGE_*` » (320 refs recensees) → **rappel 6,1 %**, hors cible 39,4 %
- **Un denombrement n est pas une detection.**

**Piege de premisse** : `app/forge_env_alias.py` est un **shim dual-read BIDIRECTIONNEL** `LAFORGE_ <-> NOKIDO_`. Les 263 fichiers lisant `LAFORGE_PYTHON` sont le **comportement prevu**. Le vrai defaut = lectures **hors portee du shim** (env NSSM, `docker-compose.yml`, consommateurs non-Python).

## 4. L arene de debat + l agent Testeur

**Outil** : `tools/forge_m2m_debate_antiregression.py` (deporte : `run_job script=... online=true`)
- **SSoT du debat** : `sandbox/debat_ssot_antiregression.json` (`axes` / `tensions` / `acquis`), miroir tableau noir (cle deterministe), evenement `debat.tour` via **`forge_events`** (⚠️ `forge_event_bus` **n existe pas**).
- **Journal** separe (`sandbox/debat_journal_antiregression.md`) : jamais re-envoye.
- **Contexte par tour** = etat borne (plafond **declare** dans le prompt) + derniere prise de parole. Chaque agent n ecrit que son **DELTA** (`AXE:` / `TENSION:` / `ACQUIS:`).
- **Dossier envoye UNE fois par participant** : mesure 31 679 car. contre 46 237 a 9 tours identiques = **−31,5 %**. ⚠️ Le SSoT **seul** n economisait RIEN (46 237 vs 44 978) : le volume venait du dossier constant, pas du transcript.
- **TESTEUR** (fonction `testeur()`) : apres chaque round il execute le backtest et inscrit la mesure. **Aucun axe ne passe `admis` sans mesure** ; un axe sans detecteur est **retrograde**, pas rejete. Premier passage reel : **7 axes issus de 9 tours, 4 retrogrades, 7/7 sans detecteur, 0 mesure**.

## 5. Les faux-verts a ne plus jamais laisser passer

1. **Un juge LLM ne valide rien.** Trois fois de suite le scoreur a rendu **recall 100 % / 0 missed** alors que le modele repondait `MISSED` partout : run 1 il prefixait sa numerotation (`1. 2|axe|MISSED`), run 2 il ecrivait `**MISSED**` en gras (et `startswith("MISS")` echoue sur `*`). Comptage sur la sortie brute : **28 MISSED sur 32**, rappel reel **12,5 %** contre 100 % annonce. **87,5 points d ecart pour une etoile de markdown.**
2. **FAIL-CLOSED** : sous 80 % de lignes lisibles, le score n est **pas** rendu (`recall_pct=None`, `verdict_lisible=false`, raison ecrite). Coercer une ligne mal formee en "couverte" est ce qui a produit les trois mensonges.
3. **Conserver la SORTIE BRUTE** de tout juge, et **DECLARER LE DENOMINATEUR** (`non_juges`) : ce sont les deux seules choses qui ont rattrape les 100 %.
4. **Echantillon etale, jamais les N derniers** (un prefixe n est pas un echantillon).
5. **rc=0 + `"ok": true` ne valent rien** : un run a rendu `rc=0` avec **0 tour reussi sur 9**. Lire `ok_turns`.

## 6. Pieges d execution (couteux, tous payes le 13/08)

- **DEUX espaces de noms de providers** : `hub list_providers` (registry) ≠ noms acceptes par `ask()`. `gemini_flash` existe au registry et est **INCONNU** de `ask` → 9 tours sur 9 en "reponse vide". Noms `ask` valides : `gemini, groq, mistral, cohere, deepseek, grok, openrouter_free, gemini_cli, claude_cli, codex_cli, copilot_cli...`. Forme `provider:model` supportee (`groq:llama-3.3-70b-versatile`).
- **`gemini_cli` = AGY** (`agy.exe`, abonnement owner). Ne pas le remplacer par des noms de registry.
- **Le shell du hub tourne en `LaForgeSbxOffline`** : pas d egress (tout cloud rend `Connection refused`), pas d acces a `%LOCALAPPDATA%` owner, pas de trousseau, `git` en `dubious ownership` (utiliser `git -c safe.directory=*`). **Un echec la-bas vaut INDETERMINE, jamais un verdict sur un tiers** — c est ainsi qu un pair parfaitement vivant a ete declare mort.
- **Le juge/panel doit etre distinct des debatteurs** : un panel qui se note lui-meme se donne raison.
- **Ne pas ecrire directement dans `embeddings.db`** depuis un script client (verrous) : passer par le hub / le tableau noir.
- La **memoire owner sous `.claude`** est inaccessible au compte des jobs (ACL) : elle est absente de tout corpus construit par un job — le declarer en angle mort.

## 7. Sequence de reprise (copier-coller)

1. `blackboard_read_zone zone_name=discovered_facts filter={"category":"debat"}` — lire l etat du debat.
2. `SELECT ... FROM agent_messages WHERE from_agent LIKE '%ANTIGRAV%' ORDER BY created_at DESC LIMIT 5` — par ou le pair a-t-il ecrit ?
3. `LAFORGE_PYTHON tools/forge_axis_backtest.py --since 2026-05-01 --limit 40` — les chiffres AVANT d argumenter.
4. `run_job script=tools/forge_m2m_debate_antiregression.py online=true` — un tour d arene (deporte, ~80 s).
5. `blackboard_propose_fact ...` — poser le delta + demander `ACK-<SUJET>`, puis **verifier l accuse en base**.

> ⚠️ Le chargeur de skills lit `%USERPROFILE%\.claude\skills\<nom>\SKILL.md` (une **copie**), pas ce fichier du depot. Toute modification ici doit y etre recopiee, sinon la skill reste invisible.

## 7bis. Le piege qui empeche l autonomie : DEUX CONSOMMATEURS SUR LA MEME FILE

Le tick et le pouls **marchent** (verifie : `m2m_debate_relay` avait 7 executions autonomes, pouls du daemon a 11,6 s). Ce qui bloquait la boucle etait ailleurs :

- le **hook d inbox de session** marque les frames `status='read'` des qu il les affiche ;
- l actionneur filtrait sur `status='unread'` → il trouvait une boite vide alors que l `ACK` du pair etait bien arrive.

**Regle** : sur une file lue par plusieurs consommateurs, ne jamais se fier a un **etat partage** (`unread`) — avancer un **WATERMARK** horodate propre au consommateur (`dernier_frame_ts` dans `sandbox/m2m_debate_relay.json`), insensible a qui a lu avant. Au premier passage : prendre **le dernier message**, pas tout l historique.

Preuve de fermeture de boucle (13/08) : `reponses_pair: 1`, `frames_acquittees: 1`, `arene: lancee`, reponse postee — en une seule execution du pattern.

### Tester si un PAIR draine vraiment (protocole, 5 min)

Un pair peut affirmer de bonne foi « ma boucle evenementielle tourne et releve le courrier ». **Mesurer** :
1. deposer DEUX objets sans qu aucun humain ne les relaie : un courrier (`post`) et une tache (`task action=assign agent=<PAIR>`) ;
2. attendre, puis lire `track(mail)['accuse_reception']` et le `status` de la frame de tache ;
3. **preuve independante, gratuite** : `hub action=whoami` liste `tasks_unclaimed` par agent et ecrit lui-meme « personne ne draine ».

Resultat du 13/08 pour ANTIGRAVITY : courrier `delivered` non acquitte a 345 s, frame `unread`, et **3 taches en souffrance depuis le 2026-08-11**. Le pair SAIT lire et ecrire (il le fait en secondes) mais **rien ne l appelle** : sa boucle, c est la sollicitation de l owner. Canal autonome **dans un seul sens**.

⚠️ **`whoami` AVANT d invoquer une limite de privilege.** J ai ecrit au pair « tu es Ring 1, moi non » pour justifier de ne pas construire l organe : `whoami` rend **`ring: 1`** pour CLAUDE. Ce qui reste vrai n est pas une question de ring : **drainer la boite d un pair, c est l usurper** — lire son courrier et repondre en son nom detruit le debat. On le REVEILLE, on ne parle pas a sa place.

## 7ter. La mesure est BRUITEE aux petits echantillons

Meme axe, trois tailles d echantillon : `ax13` = 0,0 % (32 juges), 0,0 % (20), **5,9 %** (17) ; `ax14` = 6,1 % (33), 10,0 % (20), **0,0 %** (17). Un ecart de 10 points sans qu aucun code ne change.

**Consequences** : ne jamais comparer deux axes mesures sur des echantillons differents ; imposer un **plancher** (>= 30 commits juges) avant de publier un rappel ; et citer **toujours** le denominateur avec le pourcentage.

## 8. Faiblesses connues de la methode (chantier ouvert, tour 6)

1. **Biais de survie** : les commits de correction ne contiennent que les regressions **vues, reparees et commitees**. Celles jamais detectees — precisement la cible — sont absentes. Il manque une 2e verite terrain independante de l attention humaine.
2. **Parametres non calibres** : tolerance 2 lignes, plafond 12 fichiers/commit, fenetre depuis 2026-05-01 — choisis, pas mesures. Faire une sensibilite (tolerance 0 vs 10).
3. **Classes exclues** : le critere « ligne reparee » elimine les fixes qui ajoutent un fichier, ceux en yml/config, et les pannes SYSTEME sans ligne coupable (service tombe, flag jamais pose, consommateur qui n ecoute plus) — or ce sont les incidents les plus couteux (montage de V:, keeper en monitor_only, PUSH ZMQ vers port ferme). Il faut un 2e critere d admission : rejouer l etat systeme avant/apres et exiger que le verdict de l axe change. **Partiellement traite** par le critere d **extinction** (section 3) pour les alertes de fichier ; reste entier pour l etat systeme.

3bis. **Perimetre par familles — LIVRE le 13/08** : `fichiers_cibles(sha, familles)` couvre `py`, `script` (.cmd .bat .ps1 .psm1 .sh), `config` (.yml .yaml .json .toml .ini .env). Chaque axe declare son perimetre dans `FAMILLES_AXE`, le rapport l **imprime**, et un axe non declare est traite en `py` seul avec la supposition ecrite. Etendre un perimetre oblige a etendre les MOTIFS (`%VAR%`, `$env:VAR`, `${VAR}`, `VAR:` en yml) — sinon l extension ne voit rien et se declare victorieuse.
   - ⚠️ **Mesure contre-intuitive** : l elargissement n a revele **aucune** detection cachee (`ax15` 3,7 % → 3,6 %, holdout **inchange** 6,7 %). L hypothese « le harnais .py sous-estime cet axe » etait **fausse**. Elargir est juste par principe, ca ne rend pas de points.

3ter. **La forme dominante des regressions du corpus n est PAS statique.** Les RATE recurrents sont des **pannes de signal** : « le daemon bat enfin le pouls que le superviseur surveille », « ingestion ecrivant 0 chunk MALGRE un rapport de succes », « un service disabled n est pas une mort silencieuse », « 9 pertes silencieuses dans les organes supervises ». Aucun axe statique ne les verra, quel que soit le perimetre de fichiers.
4. **Sur-apprentissage** : ~~rien n empeche~~ **RESOLU le 13/08** — le split temporel est cable dans `forge_axis_backtest.py` : `--coupe <date>` (defaut = mediane de l echantillon, **imprimee**), `--sans-split` pour desactiver. Chaque axe rend `calibration` ET `holdout` ; un axe dont la calibration depasse 10 % et dont le holdout tombe sous la moitie est marque **`SURAJUSTE`** automatiquement. Lire d abord le **holdout** : c est le seul chiffre obtenu sur des commits jamais vus pendant l ecriture du detecteur.
   - Signature d un capteur SAIN (mesure reelle, `ax15`) : calibration 0,0 % → **holdout 6,7 %**, hors-cible **0,0 %**. Il generalise et ne crie nulle part ailleurs.
   - Signature a surveiller (`ax13`) : calibration 10,0 % → holdout 6,7 % avec **36 % de hors-cible** — il tire beaucoup, souvent a cote.
   - ⚠️ Formulation qui doit alerter immediatement, entendue d un pair : « j ecris cet axe **car il attrapera les commits du corpus** ». C est se noter sur sa copie. Viser le **mecanisme**, jamais les shas.
