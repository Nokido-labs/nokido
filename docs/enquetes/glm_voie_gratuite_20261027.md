# Voie GLM gratuite — enquête et mesure du 27/10/2026

## Objet

`OPENCODE_GLM` échoue avec `Insufficient balance or no resource package` sur
`zai/glm-4.5-flash`. Question posée : existe-t-il une voie **GLM gratuite**,
joignable, et réellement utilisable **avec function-calling** par le chemin
qu'emprunte OpenCode, la passerelle gouvernée `:7777/v1` ?

Réponse courte : **non, aucune voie GLM gratuite durable n'est prouvée au
27/10/2026**. Le seul GLM qui a répondu gratuitement une fois est
`zai/glm-4.5-flash`, puis son paquet a été épuisé ; toutes les autres voies GLM
sont payantes, refusées, ou absentes.

## Méthode

- Réutilisation de `tools/forge_free_tier_census.py` (`SURFACES`, `sonder`,
  `quota`), pas de second census.
- Réseau réel, clés lues au coffre (`forge_secrets.get_secret`) : aucune valeur
  de clé n'est lue ni affichée dans ce document.
- `max_tokens = 384` : à la valeur par défaut 8, un modèle à raisonnement rend
  un texte vide, ce qui produit un faux négatif.
- Un seul outil réel (`nokido_ping`) et une demande qui force son appel ; le
  verdict « outils » exige un `tool_calls` avec arguments JSON.
- La passerelle `:7777` a été testée séparément avec le même outil, car c'est
  le seul chemin d'un client OpenCode.
- La montée en taille (1 k, 6 k, 12 k jetons) a servi à reproduire l'erreur du
  client, pas seulement à sonder un « ping ».

### Deux pièges de mesure payés

1. **Double suffixe `/models`** : plusieurs entrées de `SURFACES` se terminent
   déjà par `/models`, alors que `_lire_catalogue` et `sonder` ajoutent
   `/models` puis `/chat/completions`. Le catalogue et la génération partent
   alors sur `/models/models` et `/models/chat/completions`. Contournement
   appliqué : `base.rstrip("/")`, puis retrait de `/models` final. Le bug du
   census reste à corriger.
2. **Budget de jetons trop bas** : `glm-4.5-flash` est un modèle à raisonnement.
   À 8 jetons de sortie il rend un contenu vide ; à 384 il répond et appelle
   l'outil. Un « vide » n'est pas une preuve d'indisponibilité.

## Résultats mesurés

| Surface | Modèle exact | Déclaré au catalogue | HTTP | Latence | Outils | Statut gratuit | Verdict |
|---|---|---|---:|---:|---|---|---|
| OpenRouter | `z-ai/glm-4.5-air:free` | non | 404 `MODELE_ABSENT` | 102 ms | non testé | route retirée | mort |
| OpenRouter | `z-ai/glm-4.5-air` | oui | 402 `SANS_SOLDE` | 78 ms | non testé | payant | mort |
| OpenRouter | `z-ai/glm-4.7-flash` | oui | 402 | 56 ms | non testé | payant | mort |
| OpenRouter | `z-ai/glm-5.3-flash` | oui | 402 | 72 ms | non testé | payant | mort |
| Ollama Cloud | `glm-5.3-flash` | oui, hors FREE | 402 | 219 ms | non testé | hors palier | mort |
| Ollama Cloud | `glm-5.2` | oui, hors FREE | 402 | 487 ms | non testé | hors palier | mort |
| NVIDIA NIM | `z-ai/glm-5.3` | oui | 403 `Authorization failed` | 129 ms | non testé | clé refusée | mort |
| NVIDIA NIM | `z-ai/glm-5.3-flash` | oui | 403 | 116 ms | non testé | clé refusée | mort |
| NVIDIA (`NVIDIA_API_KEY`) | `z-ai/glm-5.3-flash` | oui | timeout 20 s | 20 129 ms | non testé | illisible | mort |
| z.ai | `glm-4.5-flash` | **non** (caché) | **200** | **2 901 ms** | **OUI** | paquet épuisé après cet appel | **one-shot** |
| z.ai | `glm-4.5-flash` (ping suivant) | non | 429 code `1113` | 420 ms | — | plus de paquet | mort |
| z.ai | `glm-4.5-flash` (1 k / 6 k / 12 k) | non | 429 `1113` | 346–455 ms | — | plus de paquet | mort |
| z.ai | `glm-4.5-air` | oui | 429 `1113` | 468 ms | — | payant | mort |
| z.ai | `glm-4.6` | oui | 429 `1113` | 410 ms | — | payant | mort |
| z.ai | `glm-5.3-flash` | oui | 429 `1113` | 346 ms | — | payant | mort |
| DeepInfra | `zai-org/GLM-5.3-Flash` | oui | 402 solde positif requis | 500 ms | non testé | payant | mort |
| Hugging Face | `zai-org/GLM-5.3-Flash` | oui | 402 crédits épuisés | 153 ms | non testé | payant | mort |
| Cerebras | `zai-glm-4.7` | non (2 modèles, aucun GLM) | 403 `error code: 1010` | 47 ms | non testé | absent | mort |
| Local Ollama | — | 16 modèles, **0 GLM** | 200 | — | — | gratuit | aucun GLM installé |
| LM Studio / llama.cpp / LiteLLM | — | injoignables | — | — | — | — | aucun GLM local |
| Mammouth | — | catalogue 403 | 403 | — | — | illisible | non concluant |
| Together / SiliconFlow | — | 401 | 401 | — | — | clé refusée | non concluant |

### Preuves de catalogue
- **OpenRouter** : 20 identifiants GLM, **0 `:free`, 0 à prix nul**. Les ids
  incluent `z-ai/glm-4.5`, `-4.5-air`, `-4.5v`, `-4.6`, `-4.6v`, `-4.7`,
  `-4.7-flash`, `-5`, `-5-turbo`, `-5.1`, `-5.2`, `-5.3`, `-5.3-flash`,
  `-5.3-flash:batch`, `-5.3-flashx`, `-5.3-prime`, `-5.3:batch`, `-5v-turbo`,
  `~z-ai/glm-flash-latest`, `~z-ai/glm-latest`. Le préfixe `~` n'est pas une
  gratuité.
- **Quota OpenRouter** (`/key`) : `usage = 0.005560111`, `limite = None`,
  `restant = None`, `palier_gratuit = True`, débit `-1/10s`. Le palier gratuit
  est actif ; ce sont les modèles GLM qui ne sont pas gratuits.
- **Ollama Cloud** : 23 modèles. Palier FREE = `nemotron-3-super`,
  `nemotron-3-ultra`, `nemotron-3-nano:30b`, `gpt-oss:20b`, `gemma4:31b`,
  `gpt-oss:120b`, `beam`. **Aucun GLM** dans le FREE ; `glm-5.3`,
  `glm-5.3-flash` et `glm-5.2` sont déclarés mais hors palier.
- **z.ai** : 11 modèles déclarés, **`glm-4.5-flash` n'y figure plus**. Il
  répond encore quand on l'appelle directement, ce qui en fait un id legacy
  caché, pas une offre publiée.
- **Groq, Mistral, SambaNova, DeepSeek, xAI, Cohere, Voyage, Jina** : aucun GLM
  au catalogue. Hors sujet pour cette enquête.
- **Cloudflare Workers AI** : hors périmètre du catalogue OpenAI-compat
  (`HORS_PERIMETRE`), non mesuré. **GitHub Models** : backend retiré (410).

## Le chemin réel d'OpenCode : la passerelle `:7777`

`GET /v1/models` rend 67 modèles. Les seules entrées GLM annoncées sont
`openrouter/z-ai/glm-4.5-air:free` et `glm5`. Les trois essais avec outils :

| Modèle demandé à la passerelle | HTTP | Erreur |
|---|---:|---|
| `openrouter/z-ai/glm-4.5-air:free` | 400 | `tool_calling_non_prouve` — le probe l'a mesuré REFUSE, et le modèle est 404 chez OpenRouter |
| `glm5` | 400 | `tool_calling_non_prouve` — alias jamais mesuré (forme attendue `<fournisseur>/<modele>`) |
| `zai/glm-4.5-flash` | 400 | `tool_calling_non_prouve` — `zai` est absent des surfaces du probe |

Le probe `tools/forge_tool_call_probe.py` ne mesure que `groq`, `openrouter`,
`mistral`, `lmstudio` et `ollama`. **`zai` n'y est pas.** La passerelle ne sert
que les modèles mesurés `APPELLE`. Donc, même si le compte z.ai avait du crédit,
la passerelle refuserait `zai/glm-4.5-flash` pour le function-calling. Les
modèles qu'elle accepte aujourd'hui sont, entre autres,
`openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` et
`groq/openai/gpt-oss-20b` ; les deux ont été vérifiés en 200 avec `tool_calls`
sur `:7777` (3,8 s et 0,5 s).

## Cause du message « Insufficient balance » d'OPENCODE_GLM

1. Le premier appel direct z.ai `glm-4.5-flash` avec outils passe : HTTP 200,
   2,9 s, un `tool_calls` observé.
2. Tous les appels suivants, y compris un simple `ping` sans outil, renvoient
   **429 code 1113** `Insufficient balance or no resource package`.
3. Le 429 persiste après plusieurs minutes et sur 1 k, 6 k et 12 k jetons. Ce
   n'est donc pas un débit par minute : le paquet gratuit est épuisé.
4. C'est exactement le message remonté par `OPENCODE_GLM`. La ligne
   `zai/glm-4.5-flash` est sémantiquement correcte ; c'est la ressource z.ai qui
   manque, pas le nom du modèle.

Le census du 26/10 avait conclu « joignable + outils » sur **un seul** essai.
Ce résultat n'est pas reproductible en série : un `joignable = true` ponctuel ne
prouve pas un palier gratuit durable.

## Conclusion

- **Aucune voie GLM gratuite, durable et utilisable avec outils** n'existe dans
  le périmètre mesuré au 27/10/2026.
- Les voies GLM existantes sont payantes (OpenRouter 402, Ollama Cloud hors FREE
  402, DeepInfra 402, HF 402, z.ai 429/1113), refusées (NVIDIA 403), absentes
  (Cerebras, OpenRouter free 404), ou illisibles (Mammouth/Together 401–403).
- `zai/glm-4.5-flash` est un cas particulier : caché du catalogue, gratuit une
  fois, puis épuisé. Ce n'est pas une base d'exploitation pour un agent.
- La passerelle `:7777` ne sait pas servir z.ai pour le function-calling ; elle
  annonce en plus une route GLM free (`openrouter/z-ai/glm-4.5-air:free`) qui
  est morte.

## Ligne de configuration proposée (NON appliquée)

Deux options, aucune n'est appliquée dans ce commit.

### Option A — garder GLM, bloquée tant que le paquet z.ai et le probe n'existent pas

```json
"OPENCODE_GLM": {
  "modele": "zai/glm-4.5-flash",
  "repli_modele": "",
  "repli_ollama_cloud": "gpt-oss:20b",
  "statut_modele": "BLOQUE 27/10 : z.ai 429/1113 sans paquet ; modele non declare au catalogue ; zai absent du probe function-calling de la passerelle"
}
```

Cette option ne change pas le modèle actuel. Elle documente pourquoi il échoue.
Pour qu'elle devienne utilisable il faudrait, dans cet ordre : (1) un paquet
gratuit z.ai réellement actif, (2) ajouter `zai` aux surfaces de
`forge_tool_call_probe.py` et le mesurer `APPELLE`, (3) vérifier que la
passerelle sert bien `zai/glm-4.5-flash` avec outils. Aucune de ces trois
étapes n'est faite ici.

### Option B — route gratuite réellement mesurée `APPELLE` (recommandée pour ne pas laisser l'instance sans exécuteur)

```json
"OPENCODE_GLM": {
  "modele": "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
  "repli_modele": "groq/openai/gpt-oss-20b",
  "repli_ollama_cloud": "gpt-oss:20b",
  "statut_modele": "27/10 : aucun GLM gratuit durable ; repli sur un modele gratuit MESURE APPELLE par la passerelle"
}
```

Ce n'est plus du GLM, mais c'est la seule voie gratuite prouvée de bout en bout
avec outils à travers `:7777` au moment de l'enquête. Si l'owner exige GLM, il
faut rouvrir z.ai (paquet + probe) ; sinon, l'option B est la ligne à appliquer.

## Fichiers et portée

- Mesures : `tools/forge_free_tier_census.py` (réutilisé), `tools/forge_provider_catalogue.py`,
  passerelle `:7777/v1`.
- Aucune modification de `config/opencode_instances.json`, de
  `config/clients/opencode/opencode.jsonc`, ni de `tools/forge_tool_call_probe.py`.
- Aucune clé affichée. Aucun balayage de `%NOKIDO_DATA%\embeddings.db`.
