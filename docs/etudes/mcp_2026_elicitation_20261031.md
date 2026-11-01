# Étude MCP révision 2026-07-28 : Élicitation et Validation Sans Session

Date : 2026-10-31
Auteur : agt_antigravity (Nokido Hub Task)
Statut : Livrable d'étude

---

## 1. Contexte et Problématique

Dans la révision du protocole Model Context Protocol (MCP) `2026-07-28`, le modèle de transport HTTP devient par défaut sans état (*stateless-first*). Les clients comme Claude Code (mesure au 31/10/2026, version 2.1.314) émettent des requêtes POST directes avec l'en-tête `MCP-Protocol-Version: 2026-07-28`, sans négociation préalable (`initialize`), sans `Mcp-Session-Id` et sans métadonnées de session (`_meta`).

L'objectif de cette étude est d'examiner formellement dans les sources de la spécification MCP ingérées au RAG :
1. Comment un client déclare qu'il supporte l'élicitation (`elicitation/create`).
2. Comment un serveur peut demander une validation utilisateur ou émettre une élicitation de manière synchrone sans session (`Mcp-Session-Id` absent).

---

## 2. Tableau de Synthèse des Affirmations et Preuves RAG

| Affirmation | Extrait copié mot pour mot + Identifiant réel [chunk:<hex>] | Source | État |
| :--- | :--- | :--- | :--- |
| **1. Déclaration de capacité Client (Elicitation)** : Le client déclare son support via l'objet `capabilities.elicitation` (modes `form` et/ou `url`). | `ts that support elicitation **MUST** declare the \`elicitation\` capability during`<br>`[initialization](../basic/lifecycle#initialization):`<br><br>```json`<br>`{`<br>`  "capabilities": {`<br>`    "elicitation": {`<br>`      "form": {},`<br>`      "url": {}`<br>`    }`<br>`  }`<br>`}`<br>```<br>`For backwards compatibility, an empty capabilities object is equivalent to declaring support for \`form\` mode only:` | [chunk:61ed4d4fe2ab0d30] | **PROUVÉ** (Spécification officielle MCP `client/elicitation.mdx`) |
| **2. Exclusions d'élicitation en mode Stateless / 2026-07-28** : Les requêtes initiées par le serveur (`server-initiated-request` telles que `elicitation/create`, sampling, etc.) sont explicitement exclues pour le transport `streamable-http-stateless` et la version de spécification `2026-07-28`. | `arm_exclusions=(` <br>`    ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless"),`<br>`    ArmExclusion(reason="server-initiated-request", spec_version="2026-07-28"),`<br>`)` | [chunk:1394252099ff80b0]<br>[chunk:7cc63fb43541e9a1]<br>[chunk:f41411f179a2f340] | **PROUVÉ** (`modelcontextprotocol_python_sdk/tests/interaction/_requirements.py`) |
| **3. Suppression du routage par `Mcp-Session-Id`** : Le routage basé sur `Mcp-Session-Id` a été formellement supprimé dans la version `2026-07-28` (SEP-2567). | `behavior="A POST carrying a valid Mcp-Session-Id routes to that session's transport with state preserved.",`<br>`transports=("streamable-http",),`<br>`removed_in="2026-07-28",`<br>`note="removed in 2026-07-28 (SEP-2567); Mcp-Session-Id routing removed, no replacement.",` | [chunk:3c12b9a316d02584] | **PROUVÉ** (Suite de tests & exigences SEP-2567) |
| **4. Architecture des requêtes modernes sans session** : Les requêtes 2026-07-28 sont des requêtes POST auto-contenues sans handshake préalable ni en-tête `Mcp-Session-Id`. | `四个进程，一个套接字。接下来是每个部署都必须回答的问题：**一个请求是否必须到达处理了上一个请求的那个 worker？**`<br>`对使用 **2026-07-28** 协议的客户端来说，不需要。现代请求是一个自包含的 POST：前面没有 \`initialize\` 握手，响应上没有 \`Mcp-Session-Id\`，第二个请求没有任何东西需要"回到"。路由到任意 worker 即可。` | [chunk:82b1dbe32a8b4803]<br>[chunk:931ef4af8ab7923e] | **PROUVÉ** (Documentation déploiement SDK Python) |
| **5. Elicitation synchrone / Erreur bloquante (`url:required-error`)** : Lorsqu'un gestionnaire ne peut pas continuer sans élicitation, il rejette la requête avec le code d'erreur -32042. | `behavior=(`<br>`    "A handler that cannot proceed without a URL elicitation rejects the request with error "`<br>`    "-32042, carrying the pending elicitations in the error data."`<br>`)` | [chunk:a036ecda9a8aa34d] | **PROUVÉ** (`client/elicitation#url-elicitation-required-error`) |
| **6. Mécanisme de validation utilisateur synchrone sans session / multi-round-trip custom** : L'existence d'en-têtes HTTP de négociation de validation inventés (`MCP-Validation-Required`, `MCP-Client-Capability`, etc.). | *Aucune occurrence dans la spécification MCP 2026-07-28 ingérée. Les interactions serveur->client inversées sont proscrites en stateless.* | RAG (aucun chunk valide ne supporte ces en-têtes) | **ILLISIBLE** (Non spécifié par le protocole standard / Absence de protocole multi-round-trip HTTP stateless natif) |

---

## 3. Ce que le Hub doit faire (Recommandations architecturales en 3 points)

1. **Reconnaître l'absence structurelle de session et de push serveur en 2026-07-28**
   En conformité avec le chunk `[chunk:3c12b9a316d02584]` (SEP-2567 supprimant `Mcp-Session-Id`) et `[chunk:82b1dbe32a8b4803]`, le hub ne doit pas tenter de maintenir une session étatique ou d'attendre un identifiant de session sur les requêtes modernes portant l'en-tête `MCP-Protocol-Version: 2026-07-28`. Tout appel d'outil entrant sur `/tools/call` doit être traité comme un POST indépendant et auto-contenu.

2. **Ne pas tenter d'émettre des requêtes serveur inversées (`server-initiated-request`) en mode Stateless HTTP**
   Comme le stipulent formellement les clauses d'exclusion `[chunk:1394252099ff80b0]` et `[chunk:f41411f179a2f340]` (`ArmExclusion(reason="server-initiated-request", transport="streamable-http-stateless")`, `ArmExclusion(reason="server-initiated-request", spec_version="2026-07-28")`), un serveur MCP ne peut pas initier un appel `elicitation/create` vers le client via la même connexion HTTP sans état. Le modèle de push serveur est incompatible avec le transport stateless 2026-07-28 standard.

3. **Gérer les besoins d'élicitation / validation par retour d'erreur synchrone standard (-32042)**
   Conformément au chunk `[chunk:a036ecda9a8aa34d]`, lorsqu'une action gouvernée requiert obligatoirement une validation ou une élicitation utilisateur avant d'être exécutée et qu'aucune session persistante bidirectionnelle n'est établie, le hub doit rejeter la requête avec l'erreur JSON-RPC standard `-32042` (`url-elicitation-required-error`) en fournissant les données de la demande d'élicitation dans le champ `data` de l'erreur, au lieu d'inventer des en-têtes HTTP non standards.
