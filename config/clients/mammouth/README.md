# Client `mammouth` (mammouth-ai/code) — gouvernance Nokido

Le CLI de Mammouth branché sur le hub souverain, outils natifs d'exécution et d'écriture
refusés. Config **versionnée ici** plutôt que dans `~/.config/mammouth/`, pour qu'elle
soit relue et vue par la CI.

## Ce qu'il est vraiment

**Un fork d'opencode.** Son `package.json` porte `"name": "opencode"`, son schéma de
configuration vient de `@opencode-ai/core`, et le dépôt contient un dossier `.opencode/`.
Le fork remplace le fournisseur par défaut ; tout le reste est opencode. C'est ce qui
détermine le montage — il fallait le vérifier avant d'écrire quoi que ce soit.

## Pourquoi ce client est gouvernable

`RULES_SHARED.md` distingue les clients selon ce qui peut les contraindre. Antigravity
n'a pas de hooks et tient par la seule discipline. mammouth, lui, expose le **modèle de
permissions le plus fin du parc** :

- valeurs `ask | allow | deny` ;
- sur `read`, `edit`, `glob`, `grep`, `list`, `bash`, `task`, `external_directory`,
  `todowrite`, `question`, `webfetch`, `websearch`, `lsp`, `skill` ;
- avec des règles **par pattern** (`"bash": {"*.sh": "allow", "*": "deny"}`).

Il n'existe pas de clé `write` distincte : **`edit` couvre l'écriture de fichiers**.

## Installation

1. **Pointer `OPENCODE_CONFIG_DIR` sur ce dossier** — c'est ce qui rend la config
   versionnée effective :

   ```
   setx OPENCODE_CONFIG_DIR "%NOKIDO_ROOT%\config\clients\mammouth"
   ```

   ⚠️ `setx` écrit dans le registre mais **ne recharge pas la session courante** : ouvre
   un NOUVEAU terminal, ou `$env:OPENCODE_CONFIG_DIR = [Environment]::GetEnvironmentVariable("OPENCODE_CONFIG_DIR","User")`.
   Piège payé sur vibe le même jour — le MCP paraissait absent alors que tout était juste.

2. **Exposer le token du hub dans l'environnement** : `FORGE_MCP_TOKEN`. La config
   l'interpole par `{env:FORGE_MCP_TOKEN}`, substitué AVANT le parsing, donc il n'est
   écrit nulle part. Sans lui : 401, donc aucun outil — état voulu.

3. **Ou tout faire d'un coup** — chemin recommandé, aucun secret sur disque :

   ```
   LAFORGE_PYTHON tools/forge_cli_route.py launch mammouth
   ```

   Le routeur pose `OPENCODE_CONFIG_DIR` et résout `FORGE_MCP_TOKEN` depuis le coffre
   DPAPI au lancement : le secret ne vit que dans la mémoire du process.

4. **Vérifier** — les trois critères qui conditionnent le passage en ring 2 :
   - le nombre d'outils vus correspond à celui que le RBAC réserve à `MAMMOUTH`, et non
     à un agent par défaut (c'est une preuve d'IDENTITÉ, pas seulement de connexion) ;
   - demander une commande shell → doit être **refusé** ;
   - demander une écriture de fichier → doit être **refusée**, l'écriture passant par
     `governed_edit`.

## Le piège de format — symétrique de celui de vibe

```jsonc
"mcp": { "laforge": { "type": "remote", ... } }   // RECORD keyé par nom  ← ici
```
```toml
[[mcp_servers]]                                    # TABLEAU de tables    ← vibe
```

Les deux clients ont été branchés le même jour, avec des formats **inverses**. Recopier
l'un sur l'autre casse le démarrage — chez vibe, le symptôme était
`UNION requires list operands, got list and dict`, sans nom de champ. Vérifier le schéma
plutôt que supposer par analogie : `packages/core/src/v1/config/mcp.ts`.

## Résolution de la configuration

Le résolveur cherche `<name>.json` / `<name>.jsonc` dans le dossier de config global,
puis dans `.opencode/` et `.mammouth/` en **remontant l'arborescence** depuis le
répertoire courant. D'où le nom `mammouth.jsonc`, confirmé par l'installeur qui crée
`~/.config/mammouth/mammouth.jsonc`. `OPENCODE_DISABLE_PROJECT_CONFIG` désactive la
recherche projet si besoin.

`AGENTS.md` à la racine du dépôt est lu nativement (convention opencode) : il porte le
socle `RULES_SHARED.md` et la section « Spécifique Mammouth ». Rien n'est recopié ici.
