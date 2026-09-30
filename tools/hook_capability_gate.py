#!/usr/bin/env python3
"""hook_capability_gate.py — gate de CAPACITÉS : la bonne forme AVANT l'erreur.

Demande owner (02/08, excédé) : « c'est fatigant de te rappeler à chaque fois la bonne
forme ; systématiquement ça devrait être un gate qui te l'indique ». Ce hook lit CHAQUE
appel `run` (shell/python) et, s'il reconnaît une forme qui ÉCHOUE de façon connue, injecte
la forme qui MARCHE — sans bloquer (nudge). Fini les rappels manuels des mêmes pièges.

Source des règles : `docs/RULES_CAPACITES_EXECUTION.md` (section DEPORTEE de
RULES_SHARED le 2026-09-19 pour le budget du noyau resident ; les regles
ci-dessous vivent dans CE code, deporter la prose ne desarme donc rien) +
[[capacites_execution_formes_qui_marchent_2026-07-22]]. Chaque entrée = un échec MESURÉ.
Non bloquant : exit 0 + message ; c'est un rappel, pas un mur (le blocage reste à
bash_guard / hook_recon_first). AJOUTER un piège = une ligne dans REGLES.

Câblé : ~/.claude/settings.json -> PreToolUse matcher `mcp__laforge-sovereign-hub__run`.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

# (regex sur la commande, forme correcte). Ordonné du plus fréquent au moins.
REGLES: list[tuple[str, str]] = [
    (r"git[^\n]{0,160}\badd\s+[\"']?Nokido[\"']?(\s|$)",
     "GESTE BRUT LA OU UN OUTIL GOUVERNE EXISTE (motif `outil_gouverne_saute`). "
     "Reaccrocher le gitlink du superrepo : `run action=trusted_script "
     "path=tools/forge_bump_superrepo.py` — dry-run par defaut, ne stage que les "
     "chemins EN DERIVE (jamais `add -A`), et REFUSE de reaccrocher un pointeur "
     "qu'il n'a pas pu lire : il rend ILLISIBLE, pas 'pas de derive'. Mesure "
     "2026-09-19 : bump fait au git brut apres avoir affirme a tort qu'aucun "
     "compte du hub ne peut ecrire dans le superrepo — `LaForgeTrusted` le fait, "
     "et la carte du 2026-09-09 le disait deja."),
    # Le motif exige une FORME D'INVOCATION, pas la proximite d'un mot-clef.
    # Deux faux positifs payes dans les dix minutes suivant sa pose :
    #   1. `ci_local\.py` nu -> tirait sur `git add tools/ci_local.py` ;
    #   2. `python[^\n]{0,120}?tools/ci_local.py` -> tirait ENCORE, parce que le
    #      chemin du depot contient lui-meme le mot : `.../Script python IA/...`.
    # Le mot-clef doit donc etre l'INTERPRETEUR qui precede IMMEDIATEMENT le
    # script (drapeaux permis), pas un mot present quelque part avant.
    (r"(?:python(?:\.exe)?[\"']?\s+(?:-\S+\s+)*|script\s*=\s*[\"']?"
     r"|run_job[^\n]{0,40}?)tools[\\/]ci_local\.py(?![^\n]*--reference)",
     "UNE CI SUR L'ARBRE PARTAGE NE CERTIFIE RIEN (motif `ci_sans_reference`). "
     "Sans `--reference <sha>`, la suite tourne sur l'arbre VIVANT : le juge rend "
     "`PROOF_ROOT_MISSING`, aucun sha n'est capture, et le `sha=` de la ligne "
     "`[preuve]` est le HEAD de l'INSTANT, pas l'etat teste. Mesure 2026-09-19 : "
     "6 commits pendant un run — verdict vert (11 237 executes, 0 echec) "
     "inattachable a un commit. Pour une CI ITERATIVE c'est acceptable, mais il "
     "faut le DIRE ; avant un push ou une publication dist, `--reference <sha>` "
     "est OBLIGATOIRE. Voir aussi `--impacte` pour ne rejouer que l'impacte."),
    (
        r"Nokido[\s\S]{0,400}?\.read_text\(",
        "LECTURE DU DEPOT HORS VOIE CANONIQUE. Lire un fichier Nokido par "
        "`Path(...).read_text()` dans `action=python` fonctionne, mais rapatrie "
        "le fichier ENTIER dans le contexte -- refacture a chaque tour -- et "
        "echappe aux bornes de `hook_search_guard`. Formes gouvernees : une "
        "fonction precise -> `read_function_body` ; l'architecture d'un fichier "
        "-> `get_file_skeleton` ; une plage -> Read offset/limit (le hub `read` "
        "rend le fichier entier) ; un "
        "balayage multi-fichiers -> `introspect` puis `forge_deep_explore`. "
        "Si la lecture brute est vraiment necessaire, la BORNER et DIRE ce qui "
        "est ecarte (une borne dit COMBIEN, pas seulement TROP).",
    ),
    (r"DELETE\s+FROM\s+rag_fts\s+WHERE\s+chunk_id",
     "`rag_fts` est un FTS5 AUTONOME, `chunk_id` UNINDEXED : ce DELETE balaie 2 M lignes. "
     "Par chunk insere = le disque a 100 % (mesure 2026-09-05 : 5 docs/12 min -> 7 docs/60 s "
     "sans). Ne l'emettre que si l'id EXISTAIT (SELECT 1 ... WHERE id=? avant l'INSERT)."),
    (r"(?<!CROSS\s)JOIN\s+rag_chunks\b",
     "JOIN sur rag_chunks : mesure 2026-09-06 (EXPLAIN QUERY PLAN sur la base reelle), le "
     "planificateur a mis rag_chunks (1,3 M lignes + blobs) en boucle EXTERNE pour 40 lignes "
     "en attente, toutes les 30 s = 112 Mo/s (QdrantSync coupe le 05/09). -> EXPLAIN QUERY "
     "PLAN AVANT de blamer le volume ; `CROSS JOIN` impose la petite table en boucle externe "
     "(SCAN petite, SEARCH rag_chunks par cle) ; NR sur le plan, base fabriquee au meme schema."),
    (r"COUNT\(\*\)\s+FROM\s+rag_chunks\s+WHERE\s+embedding\s+IS\s+NULL",
     "COUNT(*) filtre sur rag_chunks (24,9 Go) = balayage ; en boucle (organ_pulse, 600 s) = "
     "107 Mo/s permanents. Lire le snapshot du PRODUCTEUR (forge_memory_availability / "
     "_backlog_pending_qualifie), jamais reconstruire l'etat (fiche observatoire 04/09)."),
    (r"pytest[^|&]*\|\s*findstr[^&]*&&",
     "`pytest ... | findstr ... && git ...` : le rc est celui de FINDSTR (0 des qu'une "
     "ligne matche, y compris 'error'), pas le verdict de pytest -> le 2026-09-05 un "
     "module casse a l'import (NameError) a ete COMMITE (92136939d). Conditionner sur "
     "pytest lui-meme : `pytest ... -q && git ...` (sans pipe), ou lire le verdict a part."),
    # ── REFLEXES CAPACITIFS (owner, 2026-09-05 : « ton capacitif devrait AUSSI
    # etre un reflexe »). Les regles qui suivent ne decrivent pas un piege
    # d'execution mais une CAPACITE : quel organe sait deja repondre, et sous quel
    # compte. Motif paye toute la journee -- des `findstr` a l'aveugle la ou
    # `introspect` repondait en un appel, et une enquete de vingt minutes sur un
    # cas resolu le 2026-09-01.
    (r"\bfindstr\s+/s\b|\bgrep\b.*-r|\bGet-ChildItem\b.*-Recurse",
     "RECON A L'AVEUGLE sur le depot. `introspect` rend en UN appel : les symboles "
     "qui EXISTENT, ou ils sont definis, si l'attribution est SURE, les enquetes "
     "DEJA menees sur ce symptome, et surtout CE QU'IL N'A PAS PU CONSULTER. Mesure "
     "du 2026-09-05 : trois findstr sous un compte aveugle n'ont rien trouve la ou "
     "deux `introspect` ont rendu la chaine complete. -> `introspect` d'abord, "
     "`forge_deep_explore` pour une recon multi-fichiers, findstr en dernier."),
    (r"forge_symptom_index",
     "L'INDEX D'ENQUETES REND DES FAUX NEGATIFS -- mesure 2026-09-05 : « terrain "
     "neuf » sur un probleme entierement resolu le 01/09, parce que ma formulation "
     "ne matchait pas. Il le DIT lui-meme (« ne couvre que 182 sessions, ce n'est "
     "pas une preuve d'absence ») et je l'ai lu comme un feu vert. -> croiser "
     "SYSTEMATIQUEMENT avec `forge_retrieval_sweep <terme>` (8 surfaces) ET la "
     "lecture des fiches memoire. Une seule surface ne conclut jamais a une absence."),
    # ── MOTIFS RECIDIVANTS DE `forge_recurrence_audit` (cablage 2026-09-05) ──
    #
    # Owner : « il faudrait cabler TOUTES tes erreurs recurrentes ». Le module
    # `forge_recurrence_audit` DECLARE douze motifs, chacun avec son garde formule
    # -- et aucun n'etait servi au moment du geste. Une fiche est atteignable SI on
    # la cherche, ce qui suppose de deja soupconner l'erreur ; une regle ici est
    # SERVIE avant l'action, sans etre demandee.
    #
    # PORTEE HONNETE, deux limites a connaitre pour ne pas se croire couvert :
    #
    # 1. Ce hook ne voit QUE les appels `run` -- sa garde est
    #    `action not in ("shell","python","trusted_script","run_job","")`. Un tool
    #    DISTINCT (`nokido_ensure_service`, `governed_edit`, `query`...) passe a
    #    cote, et c'est un incident deja paye le 2026-09-01 (« le gate ne pouvait
    #    pas voir mon erreur »). Les motifs ci-dessous se declenchent donc sur la
    #    MENTION du geste dans une commande, pas sur l'appel du tool lui-meme.
    # 2. Seuls les motifs qui se manifestent par une COMMANDE reconnaissable sont
    #    cablables ainsi. Quatre le sont et suivent. Les autres
    #    (`capteur_neuf_pris_pour_temoin`, `seuil_invente`,
    #    `sonde_ponctuelle_fait_temporel`, `cause_commune_vs_chemin`) sont des
    #    erreurs de JUGEMENT sur une sortie, qu'aucun regex sur une commande ne
    #    peut voir : ils restent dans MEMORY.md, charge a chaque session.
    #
    # Pretendre les cabler tous ici donnerait un faux sentiment de couverture --
    # exactement le defaut que ces regles combattent.
    (r"job_status|/health|\bsc\s+query\b|Get-Service|docker\s+inspect|already_running",
     "STATUT DECLARE != REEL (motif recidivant `statut_declare_vs_reel`). Mesures : "
     "`job_status` garde `running` apres un kill EXTERNE (cache) ; `/health` a "
     "repondu `ok` avec V: NON MONTE ; `nokido_ensure_service` rend `success:false` "
     "avec `detail.out` = HTTP 200. -> CROISER avec le reel : `tasklist /FI \"PID eq "
     "<pid>\"`, le port en LISTEN, la fraicheur du heartbeat. Le registre ment, le "
     "reel tranche."),
    (r"cpu_percent|cpu_times|\bWorkingSet\b",
     "LE CPU DU WRAPPER N'EST PAS CELUI DE L'ENFANT (motif `wrapper_vs_enfant`). "
     "Mesure 2026-09-03 : le wrapper `run_job` reste a 0 % pendant que son enfant "
     "tient 98 % -- « CPU bas » se lit alors « bloque ». Et un travail I/O-bound a "
     "un CPU quasi nul PAR NATURE. Un job a ete TUE sur cette erreur alors qu'il "
     "travaillait. -> Mesurer l'ENFANT (descendre l'arbre par `ParentProcessId`) et "
     "croiser QUATRE signaux avant de conclure a un blocage : CPU, croissance du "
     "WAL/des fichiers de sortie, pid vivant (`tasklist /FI`), compteur de progres."),
    (r"ensure_service|supervisor/restart|action=drain|/reload\b|--drain\b",
     "REQUESTED != ACCEPTED != ACHIEVED (motif `declare_non_livre`). Mesures : "
     "`POST /supervisor/restart` EXPIRE a 10 s alors qu'il AGIT ; un drain d'embed "
     "a rendu vert sans avoir draine. -> Trancher sur l'EFFET (le port repond, le "
     "heartbeat repart, le compteur bouge), jamais sur l'accuse de reception."),
    # SEUIL A 4 CHIFFRES, et c'est une mesure, pas un choix esthetique : la version
    # a 3 chiffres criait sur `ligne[:150]`, un slice d'AFFICHAGE -- observe des la
    # premiere heure. Les troncatures qui ont coute (`text[:3000]`, `[:4000]`)
    # portent toutes sur des milliers de caracteres ; un slice d'affichage tient
    # en centaines. Un garde qui crie a faux se fait desarmer, et on perd alors
    # les vrais avec.
    (r"\[\s*:\s*\d{4,}\s*\]|\btext\[:\d{3,}\]|truncate\(",
     "UNE BORNE DOIT DIRE COMBIEN, PAS SEULEMENT TROP (motif `borne_trop_serree`). "
     "Mesure : `text[:3000]` a detruit le corps de 377 documents de veille -- le "
     "contenu etait disponible et JETE, en silence. Si une limite est necessaire, "
     "journaliser ce qui est ecarte (`N morceaux -> cap a M, le reste n'est PAS "
     "ingere`) pour qu'un rattrapage reste possible."),
    # ── DEUX CHEMINS PEUVENT ETRE UN SEUL FICHIER (2026-09-18) ──
    # `V:` est un lecteur SUBSTITUE vers `Nokido/RAG/`. Mesure du jour :
    #   %NOKIDO_DATA%\embeddings.db        dev=8967830048855926842 ino=281474976710724
    #   RAG/embeddings.db       dev=8967830048855926842 ino=281474976710724
    #   os.path.samefile() -> True
    # Un seul fichier physique, un seul WAL, un seul verrou d'ecriture. Or une
    # comparaison de CHAINES (`normcase(a) == normcase(b)`) rend False sur ces
    # deux chemins : j'ai conclu « task_queue n'ecrit pas dans la base du RAG »
    # alors que c'est le MEME fichier. Le faux negatif va dans le sens
    # rassurant — il fait conclure a une absence de contention qui existe.
    # Famille des « deux noms d'import = deux instances » (2026-09-10), inversee :
    # ici deux NOMS designent UN seul objet.
    (r"normcase\([^)]*\)\s*==|str\([^)]*path[^)]*\)\s*==\s*str\(|\.lower\(\)\s*==\s*[^=]*path",
     "COMPARER DEUX CHEMINS PAR LEUR TEXTE (motif `deux_chemins_un_fichier`). Mesure "
     "2026-09-18 : `V:` est un lecteur substitue vers `Nokido/RAG/` — meme `dev`, meme "
     "`ino`, meme WAL, meme verrou — et la comparaison de chaines rend False. Le faux "
     "negatif va dans le sens RASSURANT (on conclut a une absence de contention reelle). "
     "-> `os.path.samefile(a, b)`, ou `os.stat().st_dev/st_ino`. Un chemin n'identifie "
     "pas un fichier : jonctions, `subst`, liens et casse produisent des alias."),
    # ── ECRIRE SUR UN TUYAU DEPUIS UNE BOUCLE D'EVENEMENTS (2026-09-18) ──
    # Deux services tues le MEME JOUR par la meme cause, via deux chemins :
    #   - webhub :7400 -> `logging:1144 self.stream.flush()` (log d'acces uvicorn)
    #   - hub :8766     -> `forge_byte_router:133` print(..., flush=True), tue a
    #     18:25:17 par son propre garde (`WEDGE KILL : event-loop gele 60s`)
    # Le stdout des services est un tuyau draine par le superviseur, mesure le
    # meme jour avec 7 MINUTES de retard. Tuyau plein => `flush()` attend => la
    # boucle gele => le garde tue. Une DECORATION ne vaut pas un service.
    (r"print\([^)]*flush\s*=|\.flush\(\)|logging\.StreamHandler\(",
     "ECRITURE SYNCHRONE SUR UN TUYAU (motif `flush_dans_la_boucle`). Si ce code "
     "peut tourner dans une boucle d'evenements, un `flush` sur stdout/stderr BLOQUE "
     "quand le drain du superviseur prend du retard (7 min mesurees le 2026-09-18) : "
     "deux services tues le meme jour. -> `forge_logging.ecrire_sans_bloquer` (file "
     "bornee, fil separe, pertes COMPTEES) pour une decoration, "
     "`installer_logging_non_bloquant` pour le logging d'un service. Hors boucle "
     "(script, job detache, fil dedie), un flush est sans danger."),
    # ── CHERCHER UN FICHIER QUE LE DEPOT SAIT DEJA NOMMER (2026-09-18) ──
    # Owner : « pourquoi un glob recursif ? y a des methodes plus econome mis en
    # place que tu contournes encore ! ». Mesure du jour : un
    # `glob(".../**/tasks.db", recursive=True)` s'est fait TUER par le hub
    # (`TerminateProcess`) alors que la reponse tenait dans une constante de
    # module -- `forge_task_executor.TASKS_DB` -- et que `forge_db_path` etait
    # DEJA importe deux appels plus tot dans la meme session.
    # Le balayage n'est pas seulement couteux : il est le symptome d'avoir
    # DEDUIT un emplacement au lieu de le DEMANDER a l'organe qui le possede.
    (r"rglob\(|glob\.glob\([^)]*recursive\s*=\s*True|dir\s+/b\s+/s|Get-ChildItem[^\n]*-Recurse",
     "BALAYAGE RECURSIF SUR LE DEPOT (motif `chemin_deduit_au_lieu_de_demande`). "
     "Mesures : `dir /b /s` et un `rglob` sur tout le depot se font TUER par le hub "
     "(TerminateProcess) ; un `glob(recursive=True)` cherchait `tasks.db` quand "
     "`forge_task_executor.TASKS_DB` le nommait deja. -> DEMANDER le chemin a "
     "l'organe proprietaire (constante/fonction du module qui possede la ressource), "
     "ou `tools/forge_retrieval_sweep.py <terme>` qui cherche l'OUTIL PAR SON NOM. "
     "Un balayage ne se justifie qu'apres avoir echoue a nommer le proprietaire."),
    # ── LIRE LE LIVRABLE D'UNE TACHE M2M, PAS SON ACCUSE (2026-09-18) ──
    # Owner : « le detail M2M est tronque a ~250 caracteres mais doit y avoir un
    # pointeur pour eviter ce tronquage ! pourquoi tu ne le respecte pas ! ».
    # Le contrat est ECRIT dans `forge_mcp_registry` (mesure du 2026-07-26) :
    # l'enveloppe `detail` est un ACCUSE court et volontairement court ; le
    # LIVRABLE vit dans `tasks.result`, et `pointer_ref` en donne l'adresse.
    # Lire `detail` et conclure que la reponse est tronquee, c'est prendre
    # l'accuse de reception pour le colis.
    # Motif ETROIT, et volontairement : la variante large (`result[:\d+]`, sans
    # plancher de chiffres) criait sur n'importe quel slice d'affichage. C'est le
    # mode d'echec deja documente au-dessus pour `borne_trop_serree` -- un garde
    # qui crie a faux se fait desarmer, et on perd les vrais avec lui. On ne
    # reconnait donc que la LECTURE d'une clef `detail` en tant que clef de
    # dictionnaire, ce qui, dans une commande passee au hub, designe un message M2M.
    (r"""get\(\s*["']detail["']|\[\s*["']detail["']\s*\]""",
     "LE LIVRABLE N'EST PAS L'ACCUSE (motif `accuse_pris_pour_livrable`). Le champ "
     "`detail` d'un message M2M est un RESUME court par construction ; le livrable "
     "complet est a l'adresse donnee par `pointer_ref` (`tasks.db:<task_id>` -> "
     "colonne `result`). -> Suivre `pointer_ref`, jamais conclure sur `detail`. "
     "Et verifier que la cible ne ment pas sur sa completude : une longueur EGALE "
     "au plafond est une borne, pas une longueur."),
    # ── RELEVER UN SERVICE (2026-09-05, l'erreur PROPOSEE DEUX FOIS le meme jour) ──
    # Owner : « mais bordel tu devrais savoir que ca ne fonctionne pas d'ici ». Et le
    # reproche portait moins sur l'oubli que sur la FORME du souvenir : la lecon
    # existait dans une fiche, donc ATTEIGNABLE si on la cherche -- ce qui suppose de
    # deja soupconner l'erreur. Elle n'etait pas SERVIE au moment du geste. C'est
    # precisement ce que fait cette table, et c'est pour cela qu'elle existe.
    (r"nssm\s+(restart|start|stop|status)",
     "nssm depuis ici = `OpenService(): Acces refuse`, DES DEUX COTES -- mesure du "
     "2026-09-05 : l'owner tapant `! nssm restart laforge-master` obtient la MEME "
     "erreur que moi. Corollaire a retenir : `!` n'est PAS un canal privilegie, "
     "c'est MON shell avec MES droits, donc lui demander une commande elevee "
     "n'aboutira jamais. -> Le geste qui marche : demander « relance par ton "
     "LANCEUR DU BUREAU ». Ne jamais reproposer une commande nssm."),
    (r"hub_restart\.trigger",
     "`trigger consomme` != `trigger efficace` : le fichier disparait quand le "
     "superviseur le LIT, pas quand il aboutit. Mesure 2026-09-05 : consomme, aucun "
     "effet, et j'ai attribue a mon trigger un redemarrage fait par l'owner. "
     "Verifier l'EFFET (le hub repond) et la FILIATION (`nssm.exe` parent d'un "
     "`deno.exe` neuf = restart owner), jamais la disparition du fichier."),
    # ── JOINTURE SUR TABLE VIRTUELLE FTS5 (2026-09-03, 2 195 Go lus pour rien) ──
    # Regex ETROITE a dessein : elle exige le mot JOIN suivi d'une table _fts.
    # Une requete ordinaire (`... FROM rag_fts WHERE rag_fts MATCH ?`) ne la
    # declenche pas — une premiere version large avait ete prise en faux positif
    # par test_capability_gate_sondes_nr le meme jour, et retiree.
    (r"JOIN\s+\w*_fts\b|JOIN\s+\w+\s+\w*\s*ON\s+\w*\.?chunk_id",
     "jointure sur une table VIRTUELLE FTS5 : `rag_fts.chunk_id` n'a AUCUN "
     "B-tree et SQLite refuse CREATE INDEX dessus, donc le moteur rescanne tout "
     "le FTS pour CHAQUE ligne. Mesure 2026-09-03 : 41 min a 98 % de CPU, "
     "**2 195 Go lus**, zero resultat, job tue a la main. Forme correcte = DEUX "
     "PASSES : `ids = {r[0] for r in conn.execute('SELECT chunk_id FROM "
     "rag_fts')}` (~80 Mo en RAM) puis streaming de rag_chunks avec test "
     "d'appartenance O(1). Un GROUP BY sur cette jointure fait pire."),
    # RETRIEVAL MONO-SURFACE : regle RETIREE le 2026-09-03, le jour meme de son
    # ajout. `test_capability_gate_sondes_nr` l'a prise en faux positif sur une
    # requete ORDINAIRE (`SELECT source FROM rag_fts WHERE rag_fts MATCH ...`) :
    # interroger un index n'est pas une faute, seule l'est la CONCLUSION d'absence
    # tiree d'une seule surface -- et ca, une regex sur la commande ne le voit pas.
    # Le garde avait raison, mon diagnostic etait faux : on ne desarme pas le test.
    # Le reflexe vit donc dans `tools/forge_retrieval_sweep.py` (verdict INDETERMINE
    # tant qu'une surface est illisible), pas dans un nudge qui crierait a tort.
    # ── SONDES DE CAPACITE (ajout 2026-08-30, 10 erreurs du meme motif en un jour) ──
    # Motif unique : sonder la forme qu'on IMAGINE au lieu de lire ce que le systeme
    # DECLARE. A chaque fois la declaration existait — services.toml, le compose,
    # RULES_SHARED, ou un SKILL.md jamais ouvert.
    (r"find_spec|importlib\.util|pip\s+show|ModuleNotFoundError",
     "sonder un MODULE Python ne prouve rien sur une capacite SERVICE. Mesure "
     "2026-08-30 : `crawl4ai` cherche par find_spec dans 3 envs -> 'ABSENT', alors "
     "qu'il est CONTENEURISE. Avant de conclure a une absence, lire les sources qui "
     "DECLARENT : docker/nokido/docker-compose.yml, proxy_deno/core/services.toml, "
     "et .agents/skills/*/SKILL.md."),
    (r"LIKE\s+['\"]%|LIKE\s+\?.*rag_chunks|rag_chunks.*LIKE",
     "LIKE '%motif%' sur rag_chunks = scan de 1,3 M lignes -> timeout 120 s (mesure "
     "2026-08-30). Regle d'or n1 du projet : rag_fts (FTS5/BM25) ou RAGEngine.search, "
     "jamais de LIKE primitif. `SELECT ... FROM rag_fts WHERE rag_fts MATCH '...'`."),
    (r"expanduser|os\.path\.expanduser|Path\.home\(\)",
     "`~` se resout sur le profil du compte QUI LANCE : en job detache c'est "
     "C:\\Users\\Default et les envs deviennent introuvables (mesure 2026-08-30 : le "
     "wheel probe a ecrase 14 417 o de mesures par 581 o d'erreurs). Les chemins "
     "absolus sont declares dans proxy_deno/core/services.toml [vars] — les lire la."),
    (r"\$args\b",
     "`$args` est une variable RESERVEE de PowerShell : la reassigner casse "
     "silencieusement l'appel (mesure 2026-08-30 : python lance SANS argument, donc "
     "en interactif, jusqu'au timeout de 120 s). Utiliser un autre nom : $arguments."),
    # Resserree apres mesure : la version large criait sur tout `run_job`, y compris
    # ceux qui portent deja leur lane — 1 faux positif sur 4 cas legitimes. Un garde
    # qui crie a faux se fait desarmer, donc il ne parle QUE d'un job SANS lane.
    (r"run_job(?!(?:.|\n)*lane)",
     "job lance SANS `lane` : c'est ainsi que la machine a sature le 2026-08-30 "
     "(hub bloque, 4 appels en timeout). Passer `lane=<nom>`. Et se rappeler que "
     "`ok:true` ne prouve que le SPAWN, jamais l'execution — un job a affiche CPU "
     "0 s pendant 45 min sans rien faire : exiger une preuve qu'il PRODUIT."),
    # Mesure 2026-08-31 : un digest voulu `--provider ollama --limit 20` est parti
    # en defaut `limit 400` sur le MAUVAIS provider — `args=` est ignore en
    # silence, le wrapper concatene `+ []`. Le nom accepte est `script_args`,
    # comme pour trusted_script.
    (r"run_job(?:.|\n)*(?<!script_)\bargs\s*[=:]",
     "run_job : le parametre `args` est IGNORE en silence (wrapper `+ []`, script "
     "lance SANS arguments — mesure 2026-08-31). Le nom accepte est `script_args`. "
     "Verifier au besoin le `_wrap.py` du job (`Popen([...] + [...])`)."),
    # Mesure 2026-08-31 : 2 lots de suite en timeout MUET a 120 s pile vers
    # 127.0.0.1:11434 depuis un run_job online=true, pendant que /api/ps repondait
    # en 280 ms du shell online. `online` ne donne que l'egress, jamais le loopback.
    (r"run_job(?:.|\n)*(?:127\.0\.0\.1|localhost)",
     "run_job : le compte des jobs ne voit PAS le loopback, MEME online=true "
     "(timeouts muets 120 s mesures 2026-08-31). Loopback longue duree = console "
     "owner ou daemon owner ; shell sandbox=\"online\" pour les appels courts."),
    # UN PUSH NE SE JUGE PAS SUR SON CODE DE RETOUR. Mesure 2026-08-29 :
    # forge_push_sovereign --push sort en rc=1 (le credential store wincredman ne
    # peut pas persister le jeton : "unable to get credential storage lock") APRES
    # avoir publie. Le tip distant etait bien le nouveau. Relancer sur ce rc, c'est
    # re-pousser dans le vide en croyant reparer -- meme famille que job_status
    # apres un kill externe : le registre ment, le REEL dit vrai.
    (r"forge_push_sovereign|forge_anon_push",
     "push : le rc de git MENT ici (rc=1 alors que la publication a REUSSI, "
     "credential store wincredman). Verdict = le DISTANT : "
     "`git ls-remote origin refs/heads/<branche>`. Ne jamais relancer sur le rc."),

    # ── OU FAIRE TOURNER UN GIT QUI TOUCHE LE RESEAU (mesure 2026-09-16) ───────
    # Erreur reproduite plusieurs fois : lancer `git ls-remote` / `push` / `fetch`
    # par le hub, constater un echec, et en conclure « le compte n'a pas le
    # reseau, il faut passer par run_job online=true ».
    # MESURE DU JOUR, les deux chemins essayes cote a cote sur la MEME commande :
    #   run action=shell (defaut)          -> fatal: unable to access ...
    #                                         Failed to connect to github.com:443
    #   run action=shell network=true      -> SORTIE VIDE, aucune erreur  <-- pire
    #   Bash (compte de la session)        -> les 18 refs, dont refs/heads/alpha
    # La sortie VIDE est le vrai piege : elle ne se distingue pas d'un depot sans
    # branches, et elle fait conclure a une capacite absente alors qu'elle existe.
    # `git` est un PASSTHROUGH de bash_guard, precisement pour ca.
    (r"git\b[^|&\n]*\b(ls-remote|push|fetch|clone|pull)\b",
     "GIT RESEAU PAR LE MAUVAIS CANAL. Le compte du hub ne joint pas GitHub : le "
     "defaut rend `Failed to connect`, et `network=true` rend une SORTIE VIDE sans "
     "erreur -- donc indistinguable d'un depot sans branches. -> forme qui MARCHE : "
     "l'outil **Bash** (git y est passthrough de bash_guard, le compte de session a "
     "l'egress), ou `run action=trusted_script` pour un script git-tracke. "
     "Ne pas conclure d'une sortie vide que la capacite n'existe pas."),
    # LE COMPTE D'EXECUTION EST UN CHOIX, PAS UNE FATALITE. Trois comptes existent —
    # LaForgeSbxOffline (defaut), LaForgeSbxOnline, LaForgeTrusted — et `run` les
    # selectionne par `sandbox=`. Mesure 2026-08-26 : Playwright expire en 180 s sous le
    # defaut, SANS erreur franche (il pilote le navigateur par le loopback, que ce compte
    # bloque), et se lance en 1,3 s sous `sandbox="online"`. Le timeout muet envoie
    # chercher la cause partout ailleurs — profil, chemin des navigateurs, mode headed :
    # trois fausses pistes payees le meme jour avant d'essayer simplement l'autre compte.
    (r"\b(playwright|forge_ui_campaign|launch_persistent_context|chromium|firefox\.exe)\b",
     "navigateur/Playwright : IMPOSSIBLE sous LaForgeSbxOffline (defaut) — timeout muet, "
     "pas d'erreur. -> `run action=shell sandbox=\"online\"` (mesure : 1,3 s au lieu de "
     "180 s de timeout). Comptes disponibles : offline (defaut) | online | trusted. "
     "ATTENTION : sandbox=\"online\" passe par POWERSHELL (le defaut est cmd.exe) — "
     "`start \"\" /B cmd /c ...` n'y produit RIEN. Forme qui marche : "
     "`& 'python.exe' 'script.py' *> 'C:\\tmp\\sortie.txt'`. Ecrire la sortie sous "
     "C:\\tmp (le scratchpad de session n'est pas accessible a ce compte)."),
    (r"(?<!_)\bdocker\s+(ps|images|inspect|logs|start|stop|rm|run|exec|version|restart)\b",
     "docker BRUT echoue sous le compte PAR DEFAUT (LaForgeSbxOffline, hors "
     "docker-users) : 'permission denied'. Mais LaForgeSbxOnline et LaForgeTrusted "
     "SONT dans docker-users (corrige 2026-09-02, owner) -> `network=true` ou "
     "`action=trusted_script` marchent en direct. Voie gouvernee : outil "
     "`docker_action`, argv sans le mot 'docker'. NB : une erreur 500 du moteur "
     "n'est PAS un refus d'ACL -- c'est Docker qui redemarre."),
    (r"\bcd\b[^&|]*&&[^&|]*\bgit\b|\bcd\b[^&|]*\bgit\b",
     "`cd <repo> && git` -> 'dubious ownership' (le sandbox n'est pas l'owner). "
     "-> `git -c safe.directory=* -C \"<path>\"`, JAMAIS de cd."),
    (r'\bfind\s+/c\s+"(?:")?\s*$|\bfind\s+/c\s+""(?!\s*/v)|\|\s*find\s+/c\s+""',
     "`find /c \"\"` rend TOUJOURS 0 (find ne matche pas la chaîne vide). "
     "-> `find /c /v \"\"` pour compter des lignes."),
    (r"\bsubprocess\.(Popen|run|call|check_output)\b",
     "action=python INTERDIT subprocess (WORKSPACE_GUARD). "
     "-> action=shell ; ou pilote main() in-process avec sys.stdin=io.StringIO(...)."),
    (r"\bwmic\b",
     "`wmic` déprécié/absent. -> `tasklist` (ou `tasklist /FI`)."),
    # (la regle « cmdlets PowerShell » vit desormais dans REGLES_CMD_SEULEMENT :
    #  elle ne vaut QUE sous le compte par defaut, cf. _regles_du_shell)
    (r"\bos\.access\([^)]*W_OK",
     "`os.access(path, W_OK)` MENT sous Windows (ne teste pas les ACL). "
     "-> tenter l'écriture avec sauvegarde, c'est le seul test honnête."),
    (r'\bfindstr\s+"[^"/]+\s+[^"/]+"',
     "`findstr \"a b\"` cherche a OU b (espaces = littéraux séparés). "
     "-> phrase exacte : `findstr /c:\"a b\"`."),
    (r"\bpy_compile\.compile\(",
     "`py_compile.compile()` -> PermissionError sur __pycache__ (sandbox). "
     "-> `compile(open(f).read(), f, 'exec')` en mémoire."),
    (r"\bpip\s+install\b",
     "`pip install` dans un env owner échoue (HOME=Default -> user-site refusé). "
     "-> action OWNER (`!`), et un CLI tiers va dans un env DÉDIÉ, pas LAFORGE_PYTHON."),
    (r"\bgh\s+run\s+watch\b[^|]*\|\s*tail",
     "`gh run watch | tail` rend le code de tail (un run ROUGE se lit exit 0). "
     "-> `gh run view <id> --json conclusion`."),
]

# SELECTION PAR CLASSE D'ACTION, pas par texte. Ces regles ne valent que pour un
# TRAVAIL DEPORTE (`run_job`, `trusted_script`). Mesure 2026-09-07, trois minutes
# apres leur ecriture : placees dans REGLES, elles tiraient sur un simple
# `git add tools/ci_local.py` -- le chemin apparait, la regle croit a un
# lancement. Un garde qui crie a faux se fait desarmer, et le fichier le dit deja
# pour les regles de shell. Le sélecteur lexical reste le repli ; la CLASSE
# d'action est ce qui doit trancher.
REGLES_JOB_SEULEMENT: list[tuple[str, str]] = [
    (r"tools[/\\]ci_local\.py",
     "TRAVAIL LONG lance : ne le surveille PAS en pollant le log. Un notifieur "
     "existe -- `run action=run_job script=tools/forge_job_watch_notify.py "
     "script_args=\"--progress sandbox/jobs/<job>.progress.json --rc "
     "sandbox/jobs/<job>.rc --to CLAUDE\"` (--progress et --to sont OBLIGATOIRES). "
     "Et le `.rc` est un SIGNAL, pas le verdict : conclure sur le temoin STRUCTURE "
     "(sandbox/ci_<compte>/pytest_pur_junit.xml), jamais sur la progression. "
     "Recidive mesuree le 2026-09-03 PUIS le 2026-09-07."),
    # Lookahead ancre en DEBUT DE TEXTE, pas apres le nom de fichier : l'extracteur
    # ajoute `script` APRES `script_args`, donc un `--to` correct se retrouve AVANT
    # le nom dans la chaine concatenee. Un lookahead vers l'avant criait alors sur
    # la forme JUSTE -- faux positif attrape par le NR a son premier passage.
    (r"\A(?![\s\S]*--to\b)[\s\S]*forge_job_watch_notify\.py",
     "forge_job_watch_notify EXIGE `--progress <fichier>` et `--to <AGENT>` : sans "
     "eux il sort en rc=2 avec son usage dans le `.err`, DES LE LANCEMENT et SANS "
     "rien te signaler -- tu attends alors une notification qui ne viendra jamais. "
     "`--agent` n'existe pas, c'est `--to`. Mesure 2026-09-07, mort en 1 s."),
]

# SELECTION PAR UN CHAMP DE L'ENTREE, PAS PAR LE TEXTE. `online` / `network` sont
# des booleens : ils n'apparaissent NULLE PART dans `_texte_commande`, donc aucune
# regex de REGLES ne pourrait les voir -- une regle posee la-bas serait branchee
# sur un signal que personne n'emet. La selection se fait donc sur l'entree, comme
# `_regles_du_shell` le fait deja pour `sandbox`.
REGLES_JOB_ONLINE_SEULEMENT: list[tuple[str, str]] = [
    (r"tools[/\\]ci_local\.py",
     "la CI lancee avec `online`/`network` ne change pas que l'egress : elle change "
     "le COMPTE d'execution (LaForgeSbxOnline au lieu de LaForgeSbxOffline), donc "
     "les ACL. Mesure 2026-09-11, MEME depot a quelques heures d'ecart : "
     "9293 tests / 0 failure sous le compte par defaut, 9297 / 11 failures sous "
     "online -- et les 11 sont TOUTES des operations git (`git init` rc=1, "
     "`.git/index.lock: Permission denied`, historique introuvable). La CI n'a AUCUN "
     "besoin de reseau, elle a besoin des droits git. -> relancer SANS le drapeau. "
     "Et ne jamais comparer deux JUnit ecrits dans des `sandbox/ci_<compte>/` "
     "differents : ce sont deux mesures distinctes, pas une evolution."),
]
# LE SHELL CHANGE AVEC LE COMPTE. `action=shell` est cmd.exe sous le defaut
# (offline) et POWERSHELL sous `sandbox="trusted"` / `"online"`. Une regle qui
# ignore `sandbox` conseille donc l'inverse de la bonne forme une fois sur deux :
# mesure 2026-08-28, ce gate a repondu « action=shell est cmd.exe » a une commande
# lancee en trusted, ou la vraie cause etait qu'un `if exist` de cmd n'est pas du
# PowerShell. Un garde qui se trompe de SENS est pire qu'un garde muet.
REGLES_CMD_SEULEMENT: list[tuple[str, str]] = [
    (r"\b(Measure-Object|Select-Object|Group-Object|Where-Object|ForEach-Object)\b",
     "sous le compte par defaut (offline), action=shell est cmd.exe : ces cmdlets "
     "PowerShell n'y sont pas reconnues. -> `powershell -NoProfile -Command \"...\"`, "
     "`find`/`findstr`, ou passer en `sandbox=\"trusted\"` (qui EST du PowerShell)."),
]

REGLES_POWERSHELL_SEULEMENT: list[tuple[str, str]] = [
    (r"(?i)\bif\s+(not\s+)?exist\b|%\w+%|\b2>nul\b|\bdir\s+/[bs]\b",
     "sous `sandbox=\"trusted\"`/`\"online\"` le shell est POWERSHELL, pas cmd.exe : "
     "`if exist`, `%VAR%`, `2>nul`, `dir /b` y sont des erreurs de PARSE. -> "
     "`Test-Path`, `$env:VAR`, `2>$null`, `Get-ChildItem`. Et ne PAS relancer "
     "`powershell -NoProfile -Command` depuis ce compte : c'est deja PowerShell, "
     "le double lancement expire au cap de 120 s (mesure du jour)."),
    (r"[^&|]&(?!&)[^&|]",
     "sous `sandbox=\"trusted\"`/`\"online\"` (PowerShell), `a & b` n'enchaine PAS : "
     "`&` y lance un JOB EN ARRIERE-PLAN et rend une table Id/Name/State, si bien "
     "que la sortie parait vide. -> `commands=[...]` (une entree par commande) ou `;`."),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), msg) for p, msg in REGLES]
_COMPILED_JOB = [(re.compile(p, re.IGNORECASE), msg) for p, msg in REGLES_JOB_SEULEMENT]
_COMPILED_JOB_ONLINE = [(re.compile(p, re.IGNORECASE), msg)
                        for p, msg in REGLES_JOB_ONLINE_SEULEMENT]
_COMPILED_CMD = [(re.compile(p, re.IGNORECASE), msg) for p, msg in REGLES_CMD_SEULEMENT]
_COMPILED_PS = [(re.compile(p, re.IGNORECASE), msg) for p, msg in REGLES_POWERSHELL_SEULEMENT]


def _regles_du_shell(entree: dict) -> list:
    """Regles communes + celles du shell REELLEMENT vise par cet appel.

    `sandbox` absent ou "local" = cmd.exe (defaut) ; "trusted"/"online" =
    PowerShell. Sur autre chose qu'un `action=shell` la question ne se pose pas :
    seules les regles communes s'appliquent.
    """
    action = str(entree.get("action") or "")
    # Classe d'action AVANT le texte : un travail deporte a ses propres pieges, et
    # ils ne doivent pas se declencher parce qu'un chemin de fichier passe dans un
    # `git add`. C'est le premier etage d'un selecteur par CLASSE ; le lexical
    # (REGLES) reste le repli pour tout ce qui n'est pas encore classe.
    if action in ("run_job", "trusted_script"):
        regles = _COMPILED + _COMPILED_JOB
        # Le drapeau d'egress change AUSSI le compte, donc les ACL : c'est un
        # champ BOOLEEN, invisible au texte, d'ou cette lecture de l'entree.
        # Verrouille par tests/nr/test_gate_ci_online_change_de_compte_nr.py.
        if entree.get("online") or entree.get("network"):
            regles = regles + _COMPILED_JOB_ONLINE
        return regles
    if action not in ("shell", ""):
        return _COMPILED
    sbx = str(entree.get("sandbox") or "local").lower()
    if sbx in ("trusted", "online"):
        return _COMPILED + _COMPILED_PS
    return _COMPILED + _COMPILED_CMD


# Un message de commit CITE des commandes ; il n'en exécute aucune. Mesuré
# 2026-08-28, premier commit apres l'extension du gate a Bash : un message
# decrivant « docker ps -a » et « cd <repo> && git » a declenche deux nudges sur
# un `git commit` parfaitement correct. Un garde qui crie a faux se fait
# desarmer -- on retire donc la charge utile des `-m`/`-F` avant de matcher.
_ARG_TEXTE = re.compile(
    r"""-(?:m|F|message)\s+(?:"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|@?\S+)""",
    re.DOTALL,
)


def _texte_commande(entree: dict) -> str:
    """Concatène ce qui sera exécuté : code + commands (le run tool)."""
    parts = []
    for k in ("code", "command"):
        v = entree.get(k)
        if isinstance(v, str):
            parts.append(v)
    cmds = entree.get("commands")
    if isinstance(cmds, list):
        parts.extend(str(c) for c in cmds)
    sa = entree.get("script_args")
    if isinstance(sa, str):
        parts.append(sa)
    # `script` (run_job) et `path` (trusted_script). SANS EUX, DEUX CLASSES
    # D'APPEL ENTIERES SONT INVISIBLES AU GATE. Mesure 2026-09-07 :
    #   run_job{script: "tools/ci_local.py"}             -> 0 caractere extrait
    #   trusted_script{path: "tools/forge_npu_bench.py"} -> 0 caractere
    # Aucune regle ne pouvait donc s'y declencher, quelle qu'elle soit -- et ce
    # sont EXACTEMENT les routes gouvernees que les regles prescrivent
    # (« deporter le long en run_job », « trusted_script pour le privilegie »).
    # Le garde etait aveugle la ou il devait le plus voir. Le meme soir, une CI a
    # ete suivie par polling client alors qu'un notifieur existait : recidive deja
    # consignee le 2026-09-03, et que rien ne pouvait rappeler.
    for cle in ("script", "path"):
        v = entree.get(cle)
        if isinstance(v, str):
            parts.append(v)
    return _ARG_TEXTE.sub(" ", "\n".join(parts))


def _messages_de_commit(entree: dict) -> list:
    """Les arguments -m/-F, que `_texte_commande` ecarte VOLONTAIREMENT.

    Le gate ignore le contenu d'un `-m` pour ne pas crier sur une commande
    seulement CITEE dans un message. Mais un message a ses propres pieges : sous
    bash, un backtick y ouvre une SUBSTITUTION DE COMMANDE. Le shell execute le
    mot, echoue, et il DISPARAIT du commit — sans que rien n'echoue visiblement,
    puisque le commit passe.

    Paye QUATRE fois le 2026-08-29, dont deux le meme soir : `argv` et `cible()`
    avales d'un message qui les expliquait justement. On ne scanne donc pas ces
    arguments avec les regles generales (faux positifs assures) — seulement pour
    ce piege-la, qui leur est propre."""
    brut = []
    for cle in ("code", "command"):
        val = entree.get(cle)
        if isinstance(val, str):
            brut.append(val)
    cmds = entree.get("commands")
    if isinstance(cmds, list):
        brut.extend(str(c) for c in cmds)
    joint = "\n".join(brut)
    if "commit" not in joint:
        return []
    return _ARG_TEXTE.findall(joint)


# ---------------------------------------------------------------------------
# DISCIPLINE DE DEPENSE -- le seul garde BLOQUANT de ce fichier, et c'est voulu.
#
# Mesure du 2026-09-11 : 15 % du quota en 1h30. Poste principal, les snapshots
# navigateur rendus INTEGRALEMENT dans la reponse (/forge/feed ~500 lignes de
# YAML, /postal ~200) -- et re-factures a CHAQUE tour, puisque chaque tour
# renvoie tout l'historique. Un dump de 500 lignes ne se paie pas une fois : il
# se paie N fois.
#
# Les outils exposaient DEJA la sortie bornee, et leur description avait ete
# lue. C'etait la TROISIEME fois de la session qu'une option documentee etait
# ratee (--storage-state, --secrets, puis filename). Une discipline qui echoue
# trois fois en trois heures ne tient pas par la volonte : elle devient un mur.
#
# Tout le reste de ce fichier reste en nudge (return 0). ICI seulement on
# REFUSE -- et on dit par ou passer : un mur sans issue se contourne ou se
# desarme, et ne garde alors plus rien.
# ---------------------------------------------------------------------------

# outil -> bornes qui rendent sa sortie acceptable (une seule suffit)
_DUMPS_A_BORNER = {
    "browser_snapshot": ("filename", "depth", "target", "max_chars"),
    "browser_network_requests": ("filename",),
    "browser_console_messages": ("filename",),
}


# Second volet, paye MOINS D'UNE HEURE apres la livraison du premier, et par
# celui qui venait de l'ecrire : un `type` sur le log de la CI locale a
# rapatrie 2 725 696 caracteres. Le mur navigateur etait en place ; il ne voit
# pas ce canal-la. Le poste n'est donc pas << les snapshots >>, c'est
# << rapatrier une sortie non bornee >>, quelle qu'en soit la source -- et un
# garde qu'on franchit en changeant d'outil ne garde rien (2026-09-06).
DUMP_FICHIER_SEUIL_OCTETS = 60_000  # ~15 000 tokens, deja enorme pour un tour
_OUTILS_SHELL = ("run", "Bash", "PowerShell")

# Ce qui rapatrie un fichier ENTIER.
# `\n` est un separateur a part entiere : `commands=[...]` est joint par des
# sauts de ligne, et un `^` sans re.M ne voit que la PREMIERE commande de la
# liste. Un garde qui ne couvre qu'un des deux champs d'entree du meme outil
# se franchit en changeant de champ.
_LECTEURS_ENTIERS = re.compile(
    r"(?:^|[\n|&;(]\s*)(?:type|cat|more)\s|\bGet-Content\b", re.I)

# Ce qui borne, filtre, ou ne ramene rien du tout.
# `>` seulement s'il n'est PAS precede d'un chiffre : `2>nul` redirige les
# erreurs et laisse passer tout le fichier -- c'est la forme exacte de la
# faute, elle ne doit surtout pas compter comme une borne.
_BORNES_SHELL = re.compile(
    r"\bfindstr\b|\bfind\s+[\"/]|-Tail\b|-TotalCount\b|-First\b|-Last\b"
    r"|\bSelect-(?:Object|String)\b|\bhead\b|(?<![0-9])>", re.I)

_CHEMIN_RX = re.compile(
    r'"([A-Za-z]:[\\/][^"]+)"'
    r"|'([A-Za-z]:[\\/][^']+)'"
    r'|([A-Za-z]:[\\/][^\s"\'|&<>]+)')


def _texte_brut(entree):
    """`code` + `command` + `commands`, SANS normalisation.

    Pourquoi pas `_texte_commande` : elle passe le tout dans `_ARG_TEXTE.sub`,
    qui neutralise les litteraux entre guillemets -- c'est ce qu'il FAUT pour
    les regles de forme (ne pas crier sur un nom de fichier cite dans un
    message), et c'est exactement l'inverse de ce qu'il faut ici, ou la cible
    du garde EST le chemin entre guillemets. Mesure : `type "C:\\...\\ci.log"`
    en ressortait comme `type`, et le garde ne voyait plus aucun fichier.

    Reutiliser un helper est le bon reflexe ; verifier ce qu'il NORMALISE
    avant de s'en servir en fait partie.
    """
    parts = []
    for cle in ("code", "command"):
        v = (entree or {}).get(cle)
        if isinstance(v, str):
            parts.append(v)
    cmds = (entree or {}).get("commands")
    if isinstance(cmds, list):
        parts.extend(str(c) for c in cmds)
    return "\n".join(parts)


def _gros_fichiers_cites(txt):
    """Chemins cites par la commande dont la taille DEPASSE le seuil.

    Trois etats, jamais deux : un chemin qu'on ne peut pas mesurer (absent,
    variable non resolue, ACL) n'est PAS repute gros. Refuser sur une absence
    de mesure serait la faute exactement symetrique -- et un garde qui crie a
    faux se fait desarmer.
    """
    gros = []
    for m in _CHEMIN_RX.finditer(txt):
        chemin = m.group(1) or m.group(2) or m.group(3)
        try:
            taille = os.path.getsize(chemin)
        except OSError:  # muet-ok
            # muet-ok : ILLISIBLE au sens du SYSTEME DE FICHIERS (absent, ACL,
            # chemin invalide). On ne bloque pas ce qu'on n'a pas pu voir.
            #
            # `except OSError` et NON `except Exception` : la premiere version
            # attrapait tout, et le garde est reste INERTE parce que `os`
            # n'etait pas importe -- le `NameError` se rangeait silencieusement
            # du cote << fichier illisible >>. Toutes les briques mordaient,
            # la fonction rendait une liste vide, et rien ne le disait. Un
            # chemin d'erreur trop large ne rate pas bruyamment : il transforme
            # un bug en mesure absente, qui est precisement l'etat le plus
            # rassurant. C'est le motif << conclure d'une source qui se tait >>,
            # paye ici sur mon propre garde, une heure apres l'avoir ecrit.
            continue
        if taille > DUMP_FICHIER_SEUIL_OCTETS:
            gros.append((chemin, taille))
    return gros


# ── FORME DE L'APPEL : ce que le TEXTE ne peut pas dire ─────────────────────
# Deux fautes mesurées le 2026-09-17, qu'aucune règle lexicale ne pouvait voir
# parce qu'elles ne sont pas DANS le texte — elles sont dans la STRUCTURE de
# l'appel. Le gate scannait le contenu ; ici on regarde les clés et le canal.
#
# Au-delà de ce seuil et SANS pointer_ref, un message M2M est une lettre. Le
# contrat est `{intent, pointer_ref}` vers le SSoT. Chiffre pris sur la mesure
# du jour : cinq envois à 601, 860, 1388, 1456 et 1544 caractères de substance
# inline, quand la forme correcte en faisait 115.
_SEUIL_LETTRE_M2M = 400

# Liste POSITIVE, comme `_CHAMPS_PROSE` du validateur M2M : on ne signale qu'une
# clé dont on CONNAIT le nom correct. Une clé inconnue est présumée légitime —
# un garde qui crie à faux se fait désarmer.
_CLES_FAUTIVES = {
    "run": {"command": "code", "cmd": "code", "args": "script_args",
            "commandes": "commands"},
}


def verdict_forme(tool_name, entree):
    """(touche, message). Fonction PURE : tout le NR passe par elle.

    Verrouillée par tests/nr/test_gate_forme_m2m_et_cles_nr.py.
    """
    court = str(tool_name or "").rsplit("__", 1)[-1]
    entree = entree or {}
    action = str(entree.get("action") or "")

    # 1. Un message M2M écrit comme une lettre. Le gate ne voyait JAMAIS ce cas :
    #    `main()` sortait avant, `action="notify"` n'étant pas une exécution.
    if court in ("hub", "notify") and action in ("notify", "postal", ""):
        m = entree.get("message")
        if isinstance(m, str) and len(m) > _SEUIL_LETTRE_M2M and "pointer_ref" not in m:
            return True, (
                "[forme M2M] ce message fait %d caracteres SANS `pointer_ref` : "
                "c'est une LETTRE, et le contrat M2M est un POINTEUR vers le "
                "SSoT.\n"
                "  -> forme qui MARCHE : poser le contenu "
                "(`blackboard_propose_fact`, un commit, un chunk RAG) puis "
                "envoyer `{\"intent\": ..., \"pointer_ref\": \"bb:<zone>/<cle>\", "
                "\"text\": \"<15 mots max>\"}`.\n"
                "  La limite vise la LETTRE, pas le VOLUME : un gros payload qui "
                "porte un `pointer_ref` passe sans rappel.\n"
                "  Mesure 2026-09-17 : 5 envois de 601 a 1544 caracteres inline, "
                "la forme correcte en faisait 115." % len(m))

    # 2. Une clé de paramètre qui n'existe pas. Le hub l'IGNORE en silence et
    #    exécute du vide : sortie vide, aucune erreur, indistinguable d'un
    #    script sans sortie. C'est la mauvaise moitié de `UNKNOWN != NO`.
    for fautive, bonne in (_CLES_FAUTIVES.get(court) or {}).items():
        if fautive in entree and bonne not in entree:
            return True, (
                "[forme] `%s=` n'est pas un parametre de `%s` : il est IGNORE "
                "EN SILENCE, l'appel part VIDE et tu ne verras aucune erreur.\n"
                "  -> le nom accepte est `%s=`.\n"
                "  Mesures : `command` au lieu de `code` (2026-09-17), `args` au "
                "lieu de `script_args` (2026-08-31, un digest parti sur le "
                "mauvais provider avec la limite par defaut)."
                % (fautive, court, bonne))

    return False, ""


def verdict_depense(tool_name, entree):
    """(bloque, message). Fonction PURE : tout le NR passe par elle.

    Le nom d'outil arrive prefixe par le serveur MCP
    (`mcp__playwright__browser_snapshot`) : on juge sur le dernier segment,
    sinon la regle ne mord que sur un serveur nomme.
    """
    court = str(tool_name or "").rsplit("__", 1)[-1]
    entree = entree or {}

    if court in _OUTILS_SHELL:
        txt = _texte_brut(entree)
        if txt and _LECTEURS_ENTIERS.search(txt) and not _BORNES_SHELL.search(txt):
            gros = _gros_fichiers_cites(txt)
            if gros:
                chemin, taille = gros[0]
                return True, (
                    "[depense] cette commande rapatrie %s (%d Ko) EN ENTIER dans "
                    "le contexte -- qui est re-facture a chaque tour suivant.\n"
                    "  -> forme qui MARCHE : `findstr /c:\"<motif>\" \"<fichier>\"` "
                    "pour les seules lignes utiles, ou "
                    "`powershell -NoProfile -Command \"Get-Content -LiteralPath "
                    "'<fichier>' -Tail 40\"`, ou une redirection `> fichier.out`.\n"
                    "  Note : `2>nul` ne borne RIEN, il ne redirige que les erreurs.\n"
                    "  Mesure 2026-09-11 : 2 725 696 caracteres ramenes par un "
                    "`type` sur un log de CI, une heure apres la fermeture de "
                    "l'autre porte." % (os.path.basename(chemin), taille // 1024))
        return False, ""

    bornes = _DUMPS_A_BORNER.get(court)
    if not bornes:
        return False, ""
    entree = entree or {}
    # Une borne VIDE n'est pas une borne : `filename=""` ne detourne rien.
    # Une borne VIDE n'est pas une borne : `filename=""` ne detourne rien.
    if any(entree.get(b) not in (None, "", False) for b in bornes):
        return False, ""
    autres = ", ".join("`%s`" % b for b in bornes[1:])
    return True, (
        "[depense] `%s` sans borne rapatrie la sortie ENTIERE dans le contexte, "
        "et le contexte est re-facture a CHAQUE tour suivant : un dump de 500 "
        "lignes se paie N fois, pas une.\n"
        "  -> forme qui MARCHE : `filename=...` ecrit la sortie dans un FICHIER "
        "au lieu de repondre (puis lecture ciblee)%s.\n"
        "  Mesure 2026-09-11 : 15%% du quota en 1h30, ce poste en tete."
        % (court, (", ou " + autres + " pour borner la reponse") if autres else ""))


# ---------------------------------------------------------------------------
# SENSIBILISATION — un rappel qui revient abaisse son propre seuil (2026-09-13)
#
# Directive owner, par analogie du corps : « un enfant se brule, il l'assimile
# et ne le refait plus ; et le signal de chaleur lui fait retirer la main tout
# de suite ». Trois proprietes du reflexe nociceptif :
#   1. le retrait PRECEDE la conscience (arc spinal ~25 ms contre ~300 ms pour
#      la douleur corticale) -> un garde qui laisse l'agent decider arrive trop
#      tard, par construction ;
#   2. l'apprentissage est ONE-SHOT -- une brulure suffit ;
#   3. un stimulus repete SANS consequence produit l'HABITUATION : le nudge
#      permanent n'echoue pas seulement, il ENTRAINE a l'ignorer.
#
# Mesure du 2026-09-13, un agent, une session : gates BLOQUANTS (bash_guard,
# forge_tool_gate, CRITICAL_FILES) suivis a 100 % ; nudges suivis a 0 %, dont
# l'avertissement de `governed_edit` emis 4 fois et ignore 4 fois. A l'echelle du
# corps : 2 886 editions depuis le 31/08, 13,2 % avec consultation prealable.
#
# Le precedent est dans ce fichier meme (mur des dumps) : « une discipline qui
# echoue trois fois en trois heures ne tient pas par la volonte : elle devient un
# mur ». Ce qui suit ne fait que rendre ce passage AUTOMATIQUE, au lieu de
# dependre d'un agent qui y pense -- donc d'une session, donc perdu au reboot.
#
# Le corps fait l'inverse aussi : ce qui ne fait plus mal cesse d'etre surveille.
# D'ou OUBLI_S, sans quoi on accumule des peages morts.
# ---------------------------------------------------------------------------
PROMOTION_SEUIL = 3            # le seuil du precedent : 3 echecs -> mur
PROMOTION_FENETRE_S = 7 * 86400
OUBLI_S = 90 * 86400           # habituation : au-dela, le rappel est oublie
# Ni `ROOT` ni `pathlib` n'existent dans ce module -- suppose, et paye : le hook
# levait NameError A L'IMPORT, donc il ne gardait plus RIEN. Un garde casse ne
# crie pas, il se tait : c'est le NR qui l'a dit, pas le runtime.
JOURNAL_RAPPELS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "sandbox", "capability_gate_rappels.json")


def empreinte_rappel(message: str) -> str:
    """Cle stable d'un rappel. Pas le message entier : sa forme change."""
    import hashlib

    return hashlib.sha1(message.strip().encode("utf-8", "replace")).hexdigest()[:12]


def _journal_charger() -> dict | None:
    """Rend None si ILLISIBLE — trois etats, jamais un dict vide par defaut.

    Un journal absent et un journal qu'on n'a pas pu lire ne disent pas la meme
    chose, et aucun des deux ne justifie un mur.
    """
    try:
        if not os.path.exists(JOURNAL_RAPPELS):
            return {}
        with open(JOURNAL_RAPPELS, encoding="utf-8") as _f:
            return json.load(_f)
    except Exception:  # noqa: BLE001
        return None


def _journal_noter(empreintes: list, maintenant: float) -> None:
    """Enregistre les rappels emis. Ne leve JAMAIS : un garde ne meurt pas sur
    son propre journal (mesure 2026-09-06, garde RSS tue en ecrivant le sien)."""
    journal = _journal_charger()
    if journal is None:
        return
    try:
        for cle in empreintes:
            serie = [float(t) for t in journal.get(cle, [])
                     if maintenant - float(t) < OUBLI_S]
            serie.append(maintenant)
            journal[cle] = serie[-20:]  # borne : un journal n'est pas une archive
        os.makedirs(os.path.dirname(JOURNAL_RAPPELS), exist_ok=True)
        with open(JOURNAL_RAPPELS, "w", encoding="utf-8") as _f:
            json.dump(journal, _f)
    except Exception:  # noqa: BLE001 - muet-ok, cf. ci-dessus
        pass


def promotion_verdict(empreintes: list, journal, maintenant: float) -> dict:
    """Ce rappel a-t-il assez recidive pour devenir un mur ?

    Chaque defaut a SON compteur : deux rappels differents ne s'additionnent pas,
    sinon un agent actif se ferait murer au hasard.
    """
    if not journal:
        return {"promu": False, "cle": None, "n": 0, "depuis_j": 0.0}
    for cle in empreintes:
        serie = [float(t) for t in (journal.get(cle) or [])
                 if maintenant - float(t) < OUBLI_S]
        recents = [t for t in serie if maintenant - t < PROMOTION_FENETRE_S]
        if len(recents) >= PROMOTION_SEUIL:
            return {"promu": True, "cle": cle, "n": len(recents),
                    "depuis_j": round((maintenant - min(recents)) / 86400.0, 1)}
    return {"promu": False, "cle": None, "n": 0, "depuis_j": 0.0}


def main() -> int:
    try:
        ev = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - entrée illisible : ne jamais bloquer
        return 0
    entree = ev.get("tool_input") or {}

    # --- MUR de depense, AVANT le filtre sur `action` : les outils navigateur
    # n'ont pas d'`action`, donc le filtre ci-dessous ne les voit jamais.
    bloque, pourquoi = verdict_depense(ev.get("tool_name") or "", entree)
    if bloque:
        print(pourquoi, file=sys.stderr)
        try:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": pourquoi,
                }
            }))
        except Exception:  # noqa: BLE001 - muet-ok
            # muet-ok : le refus est DEJA sorti sur stderr et le code de retour
            # ne depend pas de ce canal. Journaliser ici ne servirait qu'a
            # faire echouer le garde sur sa propre trace -- exactement le
            # defaut paye le 2026-09-06 (garde RSS mort en ecrivant son journal).
            pass
        return 0

    # --- FORME de l'appel, AVANT le filtre sur `action` : un message M2M a
    # `action="notify"` et n'aurait jamais ete vu autrement. Nudge, pas mur.
    touche_forme, pourquoi_forme = verdict_forme(ev.get("tool_name") or "", entree)
    if touche_forme:
        print(pourquoi_forme, file=sys.stderr)
        try:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": pourquoi_forme,
                }
            }))
        except Exception:  # noqa: BLE001 - un nudge ne casse jamais l'appel
            pass
        return 0

    action = str(entree.get("action") or "")
    # Ne s'applique qu'aux exécutions réelles (shell/python/trusted_script), pas au reste.
    if action not in ("shell", "python", "trusted_script", "run_job", ""):
        return 0
    txt = _texte_commande(entree)
    if not txt.strip():
        return 0
    touches = []
    for rx, msg in _regles_du_shell(entree):
        if rx.search(txt):
            touches.append(msg)
    if any("`" in m for m in _messages_de_commit(entree)):
        touches.append(
            "un backtick dans un message de commit ouvre une SUBSTITUTION sous "
            "bash : le shell EXECUTE le mot, et il disparait du message alors que "
            "le commit passe. Paye 4x le 2026-08-29. -> pas de backtick dans un "
            "-m ; ecrire le nom sans le citer.")
    if touches:
        # Le nudge doit ATTEINDRE l'agent. Mesure 2026-08-16 : ce garde connaissait
        # deja « os.access(W_OK) MENT sous Windows » — et l'agent a quand meme
        # conclu qu'un fichier critique etait ecrivable, puis s'est pris un
        # PermissionError. Motif : un PreToolUse qui sort en 0 ecrit sur stderr
        # dans le vide (seul un hook BLOQUANT voit son stderr remonte). Le savoir
        # etait la, le canal n'y etait pas.
        # `additionalContext` (meme mecanisme que hook_bash_compact) remonte le
        # message SANS bloquer : nudge, toujours pas mur.
        msg = "[capability-gate] forme qui MARCHE (avant que tu te trompes) :\n" + "\n".join(
            "  - " + m for m in touches[:3]
        )
        # SENSIBILISATION. Le meme rappel, servi PROMOTION_SEUIL fois dans la
        # fenetre, cesse d'etre un conseil : il devient un mur. On mesure AVANT
        # de noter, sinon l'emission courante ferait elle-meme basculer le seuil.
        _maintenant = time.time()
        _empreintes = [empreinte_rappel(m) for m in touches[:3]]
        _verdict = promotion_verdict(_empreintes, _journal_charger(), _maintenant)
        _journal_noter(_empreintes, _maintenant)

        if _verdict["promu"]:
            mur = (
                "[capability-gate] MUR — ce rappel t'a deja ete servi %d fois en "
                "%s jours, sans effet.\n%s\n"
                "  Il ne bloquera plus quand tu auras pris la forme ci-dessus : "
                "l'issue est dans le message, pas dans un contournement.\n"
                "  (Un avertissement repete sans consequence n'apprend rien — il "
                "entraine a l'ignorer. Mesure du 2026-09-13 : nudges suivis a "
                "0 %%, gardes bloquants a 100 %%.)"
                % (_verdict["n"], _verdict["depuis_j"], msg)
            )
            print(mur, file=sys.stderr)
            try:
                print(json.dumps({
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": mur,
                    }
                }))
            except Exception:  # noqa: BLE001 - le refus est deja sur stderr
                pass
            return 0

        print(msg, file=sys.stderr)
        try:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": msg,
                }
            }))
        except Exception:  # noqa: BLE001 - un nudge ne casse jamais l'appel
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
