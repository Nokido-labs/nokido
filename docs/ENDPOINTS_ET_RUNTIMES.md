# Endpoints, LLM et runtimes — mode d'emploi mesuré

**État au 2026-08-18.** Tout ce qui suit a été MESURÉ, jamais déduit d'une
documentation ou d'une métadonnée de catalogue. Chaque affirmation renvoie à
l'outil qui la produit, pour qu'on puisse la contester par une nouvelle mesure
plutôt que par une intuition.

Sondes : `forge_provider_catalogue`, `forge_endpoint_profiling`,
`forge_tool_call_probe`, `forge_agentic_roles_probe`, `forge_free_tier_census`,
`forge_local_llm_bringup`, `forge_router_slots_probe`.

---

## 1. Ce qui répond, et à quel prix

| endpoint | modèles | latence | débit | outils | palier gratuit |
|---|---|---|---|---|---|
| `groq` | 13 | **0,15 s** | **572 tok/s** (allam) | selon modèle | oui, non chiffré |
| `openrouter` | 400 | 0,29–0,55 s | 58–205 tok/s | selon modèle | **17 modèles `:free`** |
| `mistral` | 48 | 0,34 s | 112–162 tok/s | oui | prix non publié |
| `lmstudio` (local) | 5 | 0,96 s | 15 tok/s | oui | illimité |
| `ollama` (local) | 16 | 4,3 s (1.5B) | — | à mesurer | illimité |
| `litellm` (local) | proxy | — | — | hérité | illimité |
| `cerebras`, `deepinfra`, `deepseek`, `hf` | 2–185 | — | — | — | **crédit épuisé (402)** |
| `zai`, `mammouth` | 9 / 83 | — | — | — | **quota saturé (429)** |
| `xai` | — | — | — | — | **aucun palier gratuit** |
| `github models` | — | — | — | — | **service retiré (410)** |

Chiffres du recensement : **945 modèles déclarés**, **34 gratuits annoncés**,
**7 prouvés joignables** sur l'échantillon testé. « Déclaré » n'est pas
« gratuit », et « gratuit » n'est pas « joignable » — 288 modèles ne publient
aucun prix et ne sont donc comptés dans aucune des deux colonnes.

## 2. Pièges d'usage, chacun payé une fois

* **LM Studio rend `401` sans jeton.** `LMSTUDIO_TOKEN` est au coffre. Sans lui,
  un serveur parfaitement vivant passe pour mort.
* **Le port de llama.cpp est 8091**, pas 8080 : il est déclaré dans
  `PROVIDERS["llamacpp_local"]`. Ne jamais le deviner — un lancement sur un port
  occupé provoque `Errno 10048` et **tue le service qui tournait**.
* **Ne pas lancer `llama-server` à la main** : le service Nokido est un wrapper
  uvicorn qui possède déjà le port.
* **Prouver la vie demande le modèle le plus LÉGER.** Un 7B à froid ne répond
  pas en 240 s ; le même service répond en 4,3 s avec un 1.5B.
* **Les modèles de raisonnement laissent `content` vide** sur un budget court
  (`deepseek-r1`, `openai/gpt-oss`). Ils ne servent pas à surveiller, ils
  servent à planifier.
* **`GEMINI_MODEL` prime sur le modèle de chaque classe** (`forge_agent_proxy`).
  Un seul nom périmé y éteint les quatre slots Gemini d'un coup.
* **Chez Gemini, le quota se compte PAR MODÈLE** : la famille `pro` rend 429
  pendant que `flash-lite` répond. Un 429 n'est pas un verdict sur le compte.
* **Une clé écartée par la rotation n'est pas une clé morte** : un `403` visant
  un MODÈLE retiré fait mettre la clé en quarantaine six heures.
  `forge_provider_catalogue --rearmer` lève la peine sur preuve (`/models` 200).

## 2 bis. Piloter les runtimes locaux (et rendre leur RAM)

`nokido_ensure_service{service, desired_state}` est le seul chemin. Deux gestes
distincts, à ne pas confondre :

| geste | effet | quand |
|---|---|---|
| `stopped` | arrête le serveur | libérer franchement, accepter de perdre le slot |
| reclaimer `lmstudio_models` | décharge les **modèles**, serveur vivant | pression RAM : le slot de routage survit, rechargement à la demande |

Garde-fous en place : `lmstudio` est dans `_COUTEUX`, donc un démarrage est
refusé au-dessus de **85 %** de RAM et une seconde demande dans les **180 s** est
refusée comme réfractaire. `stopped` n'est **jamais** refusé — refuser le seul
geste qui rend de la mémoire quand elle manque serait un interblocage.

* **LM Studio n'a pas de service Windows.** `SVC_MAP` le mappait sur
  `NokidoLMStudio`, qui n'existe pas (`sc query` → 1060) : il n'était ni
  démarrable ni arrêtable, alors qu'il tenait 5,7 Go.
* **Il est per-user, et aucun compte de service n'atteint le profil owner.**
  `%USERPROFILE%\.lmstudio\bin\lms.exe` existe (120 Mo, mesuré) mais rend
  « Accès refusé » à `LaForgeTrusted`. ⚠️ « chemin introuvable » = absent ;
  « accès refusé » = **présent, ACL fermée**. Les lire pareil fabrique un absent.
* **Le pont `forge_owner_bridge` donne la SESSION, pas l'IDENTITÉ** : son child
  rend `laforgetrusted` et `USERPROFILE=C:\Users\Default`. Le canal qui porte
  l'identité owner est le **planificateur** — tâches `Nokido-LMStudio-Start` /
  `-Stop` / `-Unload`, sur le modèle de `Nokido-ConvIndex` qui tourne déjà « en
  tant que user ». `bash_guard` autorise `schtasks Nokido-*`.
* **Le verdict vient du port, jamais du `rc`.** `schtasks /run` et
  `lms server start` rendent aussitôt ; un `stop` peut rendre 0 sans rien
  libérer. On attend le port (30 s au démarrage) — sinon un serveur qui monte
  passe pour mort, et un arrêt sans effet s'annonce comme 5,7 Go rendus.
* **Un timeout interne doit rester STRICTEMENT sous celui de l'appelant** : réglé
  à 120 s, égal au cap de l'appel MCP, le dépassement était certain.

## 3. Ce que dit le catalogue, et ce qu'il vaut

**La métadonnée `supported_parameters` s'est trompée 7 fois sur 8.** Six modèles
appellent un outil **sans l'annoncer** ; un l'annonce **sans l'honorer**
(`qwen3.6-35b`, qui rend « ni outil ni texte »). Le plus rapide du parc,
`allam-2-7b`, **refuse** explicitement les outils.

Conséquence de méthode : pour toute capacité qui décide d'un routage, **mesurer
l'exécution**, jamais lire la déclaration.

## 4. Rôles agentiques tenus (épreuves d'exécution)

| rôle | épreuve | qui le tient |
|---|---|---|
| `REVIEWER` | verdict JSON parsable, champs attendus | mistral `ministral-3b`, lmstudio `qwen2.5-*` |
| `PLANNER` | plan en 3 étapes exploitables | groq `allam`, groq `gpt-oss-20b`, lmstudio `qwen2.5-*` |
| `ROUTER` | étiquette EXACTE d'un ensemble fermé | groq `allam`, lmstudio `qwen2.5-coder` |
| `SENTINEL` / `MONITOR` | idem + réponse ≤ 2 s | groq `allam`, lmstudio `qwen2.5-coder` |
| `EXECUTOR` | appel d'outil conforme | mistral, groq `gpt-oss-20b`, lmstudio |
| `SUMMARIZER` | fenêtre ≥ 100 k | openrouter `qwen3.6-35b` (262 144) |

## 5. CLI agentiques en mode non interactif — état réel

La doctrine interne « bannir le CLI headless » reposait sur l'idée que `-p`
serait bientôt restreint. **La documentation officielle dit l'inverse.**

* **Claude Code** : `-p` **EST** l'Agent SDK, positionné pour CI/CD, GitHub
  Actions et GitLab. Développement actif — `--bare` *« will become the default
  for `-p` in a future release »*, correctifs documentés jusqu'à v2.1.223.
  Sorties structurées (`--output-format json`, `--json-schema`), streaming,
  reprise de session.
* **La vraie contrainte est de FACTURATION, pas de dépréciation** : *« bare mode
  doesn't use your subscription login »* — `--bare` ignore OAuth et keychain et
  exige `ANTHROPIC_API_KEY`. Automatiser par abonnement n'est pas le chemin
  prévu ; automatiser par API l'est.
* **GitHub Copilot CLI** : `-p` supporté, *« AI credits are consumed based on
  the number of tokens processed »*, aucune restriction propre au palier Free
  dans la documentation.
* ⚠️ Sous `-p` **sans `--bare`**, Claude Code exécute les hooks de
  `.claude/settings.json` et connecte les serveurs de `.mcp.json` **sans dialogue
  de confiance** — il n'y a pas d'interface pour le poser. Dans un dépôt non
  audité, c'est le risque à connaître ; `--bare` le supprime.

## 6. Ce que ces sondes ne mesurent pas

* Le **quota** n'est rapporté que si le fournisseur l'expose (en-têtes
  `x-ratelimit`, endpoint `/key` d'OpenRouter). Ailleurs : NON MESURÉ, jamais
  estimé.
* La **qualité** des réponses n'est pas évaluée : ces sondes disent qui répond,
  pas qui répond bien.
* Les catalogues **bougent sans prévenir**. `forge_free_tier_census` compare deux
  passes datées et nomme ce qui a changé — c'est le seul mécanisme d'adaptation
  qui ne suppose rien.
