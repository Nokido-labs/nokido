# Fenêtre de maintenance du coffre — déroulé (go owner 2026-09-28)

**Statut : PRÊT, non exécuté.** Une seule fenêtre, menée par l'owner. Chaque étape dit
qui agit, sous quel compte, et comment vérifier. Aucune valeur n'est jamais affichée.
Outils (commits locaux du 28/09) : `forge_coffre_rotation.py`, `forge_at_rest_veracrypt.py
--rekey-*`, `forge_coffre_reserve_provision.py`, `forge_vault_seed_agent_tokens.py`,
`forge_secret_rotation_check.py`, bilan du coffre dans `supervisor.ts`.

**Contrainte d'ordre.** La rotation et `--rekey-finaliser` exigent SYSTEM, obtenu PAR LE HUB
(`run sandbox=ps_clm`, mode dev armé) : la rotation se fait donc AVANT l'arrêt (les services
gardent leurs anciennes valeurs en mémoire jusqu'au redémarrage), la finalisation APRÈS.

## 0. Avant la fenêtre (pile en marche)

1. `deno check proxy_deno/core/supervisor.ts` dans la console owner — **doit passer** (le
   type-check n'a pas pu tourner depuis un compte bac à sable). Sinon : on s'arrête là.
2. Un dossier owner-seul pour la sauvegarde d'entête VeraCrypt (ex. `E:\user\vc_entete\`).
3. Aucune tâche en cours dans `sandbox/tasks.db` (sinon attendre).

## 1. Rotation (pile en marche) — owner arme, Claude exécute

1. Owner : `forge_dev_mode.py arm`.
2. SYSTEM (`ps_clm`) : `forge_coffre_rotation.py` (plan) puis `--appliquer` → bilan `N/N
   tournés`, chaque écriture relue ; noms fermés : copie du coffre machine retirée.
3. SYSTEM : `forge_coffre_reserve_provision.py --appliquer --rotation-persona` (clé persona).
4. Owner (console admin) : `forge_vault_seed_agent_tokens.py --generate-missing --overwrite
   --from-registre` (jetons d'agents, coffre machine). **Ne jamais lancer `--verify`** : il
   affiche la fin de chaque jeton.

## 2. Arrêt et changement du fichier-clé — owner (console admin)

1. `nssm stop LaForge-Master` (arrête le superviseur, le hub et les services).
2. `python tools/forge_at_rest_veracrypt.py --unmount` (refuse si une base est ouverte).
3. `--rekey-preparer` → dans VeraCrypt : **d'abord** Outils › Sauvegarder l'en-tête (dossier
   du point 0.2), **puis** Volumes › Ajouter/retirer des fichiers-clés (ancien.kf → nouveau.kf).
4. `--rekey-verifier` → le volume se monte avec la NOUVELLE clé (rangée dans ton magasin
   personnel). En cas d'échec : rien n'a bougé ; refaire l'étape GUI ou `--rekey-abandonner`.

## 3. Registre NSSM — owner (console admin)

1. `nssm reset LaForge-Master AppEnvironmentExtra` (retire maître et secret JWT du registre).
2. Vérifier : la valeur n'existe plus (lecture des NOMS seulement).

## 4. Redémarrage — owner

1. `nssm start LaForge-Master`.
2. Journal du superviseur : `coffre: N secret(s) charge(s) [...]` **sans** `ABSENTS` pour
   `LAFORGE_SUPERVISOR_TOKEN` et **sans** ligne `ALERTE`.
3. Hub : `/health` ok ; services `runAs` : login de leur lanceur au journal d'autorisation.

## 5. Après redémarrage — Claude (SYSTEM via ps_clm, mode dev encore armé) puis owner

1. `forge_at_rest_veracrypt.py --rekey-finaliser` → nouvelle clé au coffre réservé, copie
   du coffre machine retirée, temporaires effacés. **Avant tout redémarrage de la machine.**
2. Owner : `forge_dev_mode.py disarm`.
3. Clients : `forge_mcp_json_sync.py` (jetons propres dans `.mcp.json`), puis `/mcp`
   reconnect dans Claude Code ; mettre à jour le jeton de Claude Desktop ; VS Code
   (`forge_vscode_mcp_sync.py`).
4. `forge_secret_rotation_check.py` : les anciennes valeurs ne servent plus (empreintes).

## 6. Hors Nokido — owner

`E:\user\.ssh\id_rsa` régénérée (et `authorized_keys` mis à jour : VM StackDNS, GitHub) ;
`.ollama\id_ed25519`, `.docker\config.json` ; l'ancien `LaForge.env` sur E: (valeurs mortes
après la rotation).

## Reste après la fenêtre

- `FORGE_ENCRYPT_KEY` : rotation après re-chiffrement des données (migration dédiée).
- Les 6 noms encore en transition : donner à chaque lecteur hors SYSTEM sa voie propre, puis
  fermer et retirer leur copie du coffre machine.

## Retour arrière

- Rotation : les nouvelles valeurs sont au coffre ; aucun retour à l'ancienne (exposée).
- Fichier-clé : sauvegarde d'entête (point 2.3) + `--rekey-abandonner` tant que l'ancienne
  ouvre le volume.
- NSSM : `nssm set LaForge-Master AppEnvironmentExtra ...` restaure l'ancien environnement
  (déconseillé : il remettrait les valeurs dans le registre lisible).
