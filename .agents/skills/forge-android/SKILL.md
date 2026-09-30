---
name: forge-android
description: >
  Connecteur Android pour Nokido — intégration de CursorTouch/Android-MCP
  (10 tools UI/shell sur device Android via ADB) dans l'écosystème hub.
  Triggers : utilisateur veut piloter un device Android (test app,
  automation UI, capture d'écran, debug d'app, scroll/tap/swipe), évoque
  "device Android", "émulateur", "ADB", "scrcpy", "app mobile",
  installation/uninstall APK, lecture notifications, exécution shell sur
  device, parle d'un projet Expo/React Native/Flutter, demande "clique sur
  X dans l'app", "tape ce texte sur le téléphone", "screenshot du device",
  "swipe up", "ouvre les paramètres Android", "lance l'app YouTube sur
  l'émulateur". Le skill route vers Android-MCP en stdio (uvx
  --python 3.13 android-mcp), avec préfixe android_* pour distinguer du
  netcfg-agent. Soumis aux Règles d'Or Nokido : SovereignMembrane wrap
  pour les paths/credentials, SemanticFirewall pre_flight avant tout
  appel, anchor_solution après chaque interaction validée.
---

# forge-android — Bras prosthétique Android

## Cartographie anatomique

Dans la grille biomimétique de Nokido :

| Élément humain | Composant Android-MCP | Module/Tool |
|---|---|---|
| **Cortex moteur primaire** | Décision d'action UI | `forge_cognitive_router` → choix tool android_* |
| **Cervelet (coordination)** | Séquence multi-tap | `forge_spike_router` → réflexes appris |
| **Bras prosthétique** | Le device Android lui-même | `Android-MCP` stdio process |
| **Doigts (effecteurs fins)** | `Click-Tool` / `Long-Click-Tool` | `android_click`, `android_long_click` |
| **Main (manipulation)** | `Type-Tool` / `Press-Tool` | `android_type`, `android_press` |
| **Bras (gestes amples)** | `Swipe-Tool` / `Drag-Tool` | `android_swipe`, `android_drag` |
| **Œil (vision périphérique)** | `State-Tool` (snapshot UI) | `android_state` |
| **Tympan (notifications)** | `Notification-Tool` | `android_notifications` |
| **Système nerveux profond** | `Shell-Tool` (adb shell) | `android_shell` (privilégié, ring élevé) |
| **Période réfractaire** | `Wait-Tool` | `android_wait` (anti-cascade) |

C'est un **effecteur externe distant** — comme un bras prosthétique
robotique connecté au SNC. Soumis aux mêmes garde-fous que tout organe
externe : barrière hémato-encéphalique (`SemanticFirewall`), membrane
souveraine pour les données device.

## Statut

LIVE. Capacité native Nokido = `tools/forge_adb.py` (ADB souverain : reverse,
screenshot, shell device). Pour le contrôle UI fin (click/swipe/type), Android-MCP
externe en option via Claude Desktop (config stdio). La fédération hub :8768 est une
extension OPTIONNELLE (exposer les tools UI à tous les clients) — pas un prérequis,
à ouvrir seulement avec un device de test connecté.

## Pré-requis

| Composant | Statut local | Action si absent |
|---|---|---|
| `uv` / `uvx` | ✅ présent (`miniforge3/Scripts/uv`) | — |
| Python 3.13 | géré par uvx à la volée (`--python 3.13`) | — |
| ADB | ❌ absent du PATH | `choco install adb` OU installer Android Studio Platform Tools |
| Device Android 10+ | à fournir | USB debugging activé (Settings → Developer options) |
| Émulateur (alternative) | optionnel | Android Studio AVD ou `scrcpy` + `genymotion` |

## Quand se déclencher

- L'utilisateur **nomme** un device, émulateur, ADB, APK, scrcpy.
- L'utilisateur veut **tester une app mobile** (Expo, React Native,
  Flutter, native Java/Kotlin).
- L'utilisateur demande **automation UI** (smoke test, monkey test
  guidé, scénario E2E).
- L'utilisateur veut **capture/screenshot** ou **lecture d'écran** d'un
  device.
- L'utilisateur veut **lire les notifications** d'un device.
- L'utilisateur cite un projet **Expo Skills** (vu dans
  awesome-claude-skills).
- L'utilisateur veut **debugger une app** mobile en prod.
- L'utilisateur demande "**clique sur**", "**tape ce texte**",
  "**swipe**", "**screenshot**" sur un téléphone.

## Voie A — intégration directe (V1, recommandée pour démarrer)

Android-MCP s'enregistre comme MCP server **stdio** dans la config
Claude Desktop. Le hub Nokido gère cette config via `/api/mcp/toggle`.

### Étape 1 : installer ADB

```bash
# Option Chocolatey (rapide)
choco install adb

# OU Android Studio Platform Tools depuis :
#   https://developer.android.com/tools/releases/platform-tools

# Vérifier
adb --version
adb devices  # liste les devices connectés
```

### Étape 2 : ajouter Android-MCP à la config Claude Desktop

Patcher `claude_desktop_config.json` avec :

```json
{
  "mcpServers": {
    "Android": {
      "command": "uvx",
      "args": ["--python", "3.13", "android-mcp"],
      "env": {
        "ANDROID_MCP_CONNECTION": "auto",
        "SCREENSHOT_QUANTIZED": "true"
      }
    }
  }
}
```

Ou via le hub Nokido (qui gère cette config) :

```bash
# Activer le serveur (à coupler avec un edit manuel pour ajouter l'entrée)
curl -s -X POST http://127.0.0.1:8766/api/mcp/toggle \
  -H 'Content-Type: application/json' \
  -d '{"name":"Android","enabled":true}'
```

### Étape 3 : redémarrer Claude Desktop

Les 10 tools Android apparaîtront dans le picker (préfixe variable
selon Claude Desktop, mais conventionnellement les noms exposés sont
`State`, `Click`, etc.).

## Voie B — fédération hub (extension optionnelle)

Pour que **TOUS les clients** parlant au hub :8766 voient les tools
Android (Cline, Roo, Continue, Copilot, etc.) sans config par client,
créer un **proxy stdio→HTTP** :

```
tools/android_mcp_proxy.py  (Starlette :8768)
    │
    ├─ spawn `uvx --python 3.13 android-mcp` en sous-process stdio
    ├─ expose /mcp HTTP qui forward JSON-RPC vers le sub-process
    └─ tools préfixés android_* (state, click, long_click, type,
       swipe, drag, press, wait, notifications, shell)

forge_mcp_registry.UPSTREAM_MCP["android"] = {
    "url":          "http://127.0.0.1:8768/mcp",
    "ring":         3,                # TRUSTED — shell device requires
    "trust":        0.5,              # initial, monte avec usage validé
    "tools_prefix": "android_",
    "guards":       ["semantic_firewall.pre_flight",
                     "sovereign_membrane.wrap_paths"],
}
```

**Code à écrire (V2 next-step)** :
- `tools/android_mcp_proxy.py` (~150 lignes)
- `app/forge_mcp_registry.py` : ajouter section `UPSTREAM_MCP` et
  fonction `_forward_upstream(name, args)`
- Ajout SQLite : `INSERT INTO forge_tools` pour les 10 tools
  android_* avec leur `min_ring` (shell=4, autres=3)

**Pourquoi pas tout de suite** : pas de device Android pour tester,
risque de coder à l'aveugle. À faire quand tu as un émulateur ou un
téléphone connecté.

## Workflow utilisateur (voie A)

### Cas 1 : test smoke d'une app

```
Utilisateur : "lance l'app YouTube sur l'émulateur et teste la home"
```

1. **Verify device** : `android_state` → confirmer qu'au moins un
   device est connecté.
2. **Lancer l'app** : `android_shell` avec `monkey -p
   com.google.android.youtube -c android.intent.category.LAUNCHER 1`
3. **Attendre chargement** : `android_wait 3000`
4. **Screenshot état initial** : `android_state` (UI tree + screenshot)
5. **Vérifier UI** : analyser le snapshot pour détecter les éléments
   attendus (search bar, recommended videos).
6. **Interagir** : `android_click` sur la search bar.
7. **anchor_solution** dans le RAG :
   ```python
   anchor_solution(
       problem="Test smoke YouTube Android",
       solution="Workflow android_shell → wait → state → click validé",
       example="...", domain="android",
   )
   ```

### Cas 2 : automation Expo dev

```
Utilisateur : "j'ai un projet Expo, valide que le screen Login s'affiche"
```

1. `android_shell` → `am start -n <package>.MainActivity` ou rely sur
   Expo Go.
2. `android_state` → snapshot UI tree.
3. Vérification présence des labels "Login", "Email", "Password".
4. Si absent → `forge-systematic-debugging` Phase 1 (pourquoi le
   screen ne s'affiche pas ?).

### Cas 3 : screenshot pour ticket bug

```
Utilisateur : "screenshot du device, je veux ouvrir un ticket bug"
```

1. `android_state` (inclut un screenshot quantized base64).
2. Décoder + écrire dans `evidence/<ticket>/screenshot.png`.
3. POST vers `/api/ingest` du hub avec `kind=evidence` pour persistance.

## Sécurité — Règles d'Or Nokido appliquées

| Règle CLAUDE.md | Application Android |
|---|---|
| 4. Ne jamais cloud sans pre_flight + post_flight | `android_state` peut contenir des PII (notifications, contenu écran) → `SemanticFirewall.pre_flight` AVANT envoi vers cloud LLM |
| Sovereign Membrane sur données techniques | `android_shell` output → `SovereignMembrane.wrap` (paths, package names, IPs) |
| Ring de sécurité | `android_shell` ring=4 (TRUSTED), autres tools ring=3 (COLLAB) |
| anchor_solution après bloc validé | Chaque scénario d'automation reproductible → anchor avec domain="android" |

## Pathologies prévisibles (grille anatomique)

| Pathologie | Signal Android | Remède |
|---|---|---|
| **Tétanie** (spasme tonique) | Boucle infinie de `android_click` qui rate sa cible | Circuit breaker dans le proxy : max 5 clicks identiques consécutifs |
| **Cécité corticale** | `android_state` retourne un UI tree vide (app crashed) | Vérifier `adb logcat` via `android_shell` AVANT replay |
| **Hypoesthésie** (perte sens du toucher) | ADB déconnecte le device pendant la session | Lazy reconnect (déjà implémenté côté Android-MCP) |
| **Hallucinations sensorielles** | Le LLM décrit un bouton qui n'existe pas dans l'UI tree | `forge_rag_truth.py` vérification factuelle obligatoire |
| **Septicémie** (infection systémique) | Une commande shell Android exfiltre vers un C2 distant | `SemanticFirewall.post_flight` détecte SSRF beacon |

## Anti-patterns

1. **Ne jamais exécuter `android_shell` sans review humain** si la
   commande contient `su`, `mount`, `dd`, `chmod`, `pm uninstall`, ou
   tout pattern de la BLOCK_PATTERNS de SkillGuardian.
2. **Ne pas envoyer de `android_state` brut au cloud** — le snapshot
   peut contenir des notifications (SMS, WhatsApp) avec PII.
3. **Ne pas hardcoder un device serial** dans un script — passer par
   `ANDROID_MCP_DEVICE` env var ou flag `--device` à l'invocation.
4. **Ne pas utiliser `monkey` (Android stress test)** sans isolation
   — peut faire des appels téléphoniques accidentels, modifier des
   réglages.
5. **Ne pas `android_drag` sur un écran de paiement** sans
   confirmation explicite — comportement irréversible.
6. **Ne pas dupliquer ce skill** vers iOS — il existe `ios-simulator-skill`
   (cf. awesome-claude-skills) pour cet usage. Référencer plutôt.

## Capacité native (existante) + extension optionnelle

- Natif LIVE : `tools/forge_adb.py` (reverse / screenshot / shell ADB) = baseline souverain.
- Extension UI OPTIONNELLE (non requise) : pour fédérer click/swipe/type à tous les clients
  hub, un proxy stdio→HTTP :8768 + entrée `forge_mcp_registry` est possible. À ouvrir seulement
  avec un device de test connecté (sinon code à l'aveugle = on s'abstient, par discipline).

## Liens

- Source : https://github.com/CursorTouch/Android-MCP
- ADB Platform Tools :
  https://developer.android.com/tools/releases/platform-tools
- Skill ios jumeau (référence, pas câblé) :
  https://github.com/conorluddy/ios-simulator-skill
- Nokido — port voisin : `netcfg-agent-mcp` :8767 (modèle d'intégration)
- Skill `forge-systematic-debugging` (utilisé pour debug d'apps qui crashent)
- Skill `forge-tdd` (pour automation E2E des apps mobiles)
