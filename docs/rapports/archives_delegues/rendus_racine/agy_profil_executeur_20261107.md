# Profil OAuth AGY de l'executeur (7/11)
1. Lancement (forge_task_executor L3190-3194) : HOME/USERPROFILE/LOCALAPPDATA/APPDATA = LAFORGE_AGY_HOME, defaut %USERPROFILE% = profil de l'owner. Meme profil que l'interactif aujourd'hui.
2. Separation POSSIBLE sans code : LAFORGE_AGY_HOME vers un autre dossier (le controle L1663 le suit). Aucun reglage change ici.
3. Jetons MCP : agy range sa conf sous %LOCALAPPDATA%\agy et ~/.gemini (mcp_config.json partage, d'apres la doc RAG) : tout est sous ce HOME. Aucun secret lu.
4. Sessions a 00:11 : non mesurable ici (pas de journal agy lu). L'executeur lance 1 agy par tache, au meme profil ; verrou de workdir seulement, pas de verrou de profil. Taches paralleles = processus qui renouvellent la meme famille : course plausible.
5. Journal : forge_oauth_clients n'en tient pas (empreintes + familles revoquees, alerte oauth:famille_revoquee:<client> a la chute). Course/vol non tranchable sans horodatage par renouvellement.
6. Une famille ne suffit pas pour N agy paralleles du meme profil : chacun rejoue le jeton tourne.
Livre : NR tests/nr/test_agy_profil_executeur_distinct_nr.py + PURE_TESTS. GRACE_REJEU_S intact. Pas de changement de code : la separation est de la config.
GESTE OWNER (unique) : 1) creer %USERPROFILE%\agy_exec ; 2) y lancer agy une fois avec HOME/USERPROFILE/LOCALAPPDATA/APPDATA pointes dessus et se connecter (OAuth Google) ; 3) definir LAFORGE_AGY_HOME=ce dossier cote executeur, restart.
Limite : le profil executeur reste partage entre taches paralleles ; limiter a 1 agy a la fois, sinon la collision se reproduit.
Tests non lances (Bash limite, non essayes).
{"intent":"OK_DONE","pointer_ref":"agy_profil_executeur_20261107.md"}
