# Audit — licences des poids de modeles cites par la config

Brief « session cloud C », 2026-09-29. Branche `claude/licences-modeles`, creee depuis `alpha`
a `ea3c441`.

## Statut : MESURE en local le 2026-09-29 -- le recensement cloud est conserve tel quel

Le proxy d'egress de la session cloud a REFUSE `huggingface.co` (`CONNECT huggingface.co:443` ->
403, refus de politique, 2026-09-29 vers 20:43 UTC) : 14 tentatives anonymes, aucune reponse.
La session a donc livre le recensement hors reseau (sections « Perimetre » et « Inventaire »,
inchangees). La mesure a ete faite en LOCAL le meme soir (job `job_d55c94712c42`, 23:01,
compte sandbox online du poste owner), par quatre observateurs :

- **Hugging Face** `/api/models/<id>` pour les seuls identifiants PROUVES (fiches de
  l'inventaire, `hugging_face_id` du catalogue OpenRouter, ids du routeur HF et de deepinfra,
  `base_model` des GGUF installes) : 355 demandees, **265 lues**, 90 en 404 (dont 86 ids
  deepinfra qui ne sont pas des depots HF). Jeton HF du coffre (`get_secret`, jamais affiche)
  pour le debit ; lecture seule, aucun poids telecharge.
- **Manifestes Ollama installes** (`D:/ollama/models`) : premiere ligne du blob de licence que
  chaque modele embarque, et cles `general.*` de l'en-tete GGUF du blob modele.
- **Fichiers GGUF** de `data/llm_models` (2). `~/.lmstudio/models` lu VIDE : les modeles LM
  Studio vivent ailleurs ou ne sont pas lisibles par ce compte -- **NON MESURE**.
- **Catalogues `/models`** de 12 surfaces API, par `tools/forge_free_tier_census.py` (reutilise,
  cles du coffre). LM Studio et LiteLLM etaient eteints : **NON MESURE**, non reveilles.

Ce qui est mesure est le NOM de la licence (champ de la fiche, ou premiere ligne du texte
embarque). Le TEXTE des licences `other` / propres n'a pas ete lu : leurs conditions restent
**A LIRE**, jamais deduites du nom. Aucune licence n'est ecrite de memoire.

## Perimetre et methode

**Perimetre (brief).** Poids cites par `proxy_deno/core/services.toml`, par les entrees
`local` de `app/forge_provider_specs.py`, et par les noms de fichiers GGUF du code
(`app/`, `tools/`, `proxy_deno/`, scripts).

**Distribution.** Le depot ne contient aucun poids de tiers : les seuls fichiers de poids
suivis par git sont `config/pca_64.npz` et `tools/forge_embed_bridge.npz`, deux projections
calculees localement (`forge_epistemic_veille`, `forge_embed_bridge`). Aucun Dockerfile ni
compose ne telecharge de poids a la construction. `app/forge_install_prerequis.py:305` le dit : « Ils ne sont
dans aucun paquet : ils se telechargent ». La question AGPLv3 porte donc sur ce que Nokido
pourrait redistribuer (image, pack), pas sur ce qu'il redistribue aujourd'hui.

**Interrogation prevue (a rejouer).** Pour chaque ligne du tableau, un seul
`GET https://huggingface.co/api/models/<fiche>` anonyme : aucun jeton, variables `HF_*`
retirees, requetes sequentielles, 4 s de pause. Sur 429 : attente selon `Retry-After`, 2
reprises au plus. Champs lus : `cardData.license`, `cardData.license_name`,
`cardData.license_link`, tags `license:*`, `gated`, `sha`. Le README de la fiche n'est lu
que si la licence vaut `other` ou si elle est absente. Jamais de telechargement de poids.
La fiche interrogee est celle du modele de BASE : un GGUF quantifie par un tiers
(gpustack, unsloth...) reste lie par la licence de sa base, et la source GGUF citee est
notee a part.

## Inventaire

Colonnes « Licence », « Usage commercial », « Compat. AGPLv3 » : remplies dans la section
« Licences mesurees » ci-dessous (le tableau du recensement reste tel que la session l'a ecrit).

| # | Fiche HF (modele de base) | Identite etablie par | Source des poids citee | Cite par | Etat dans la config |
|---|---|---|---|---|---|
| 1 | `Qwen/Qwen2.5-Coder-7B-Instruct` | `--override-kv general.name=...Qwen2.5-Coder-7B-Instruct-Q4_K_M` (services.toml:1070) ; `tools/SERVICES.md:80` « qwen2.5-coder:7b-instruct-q4_K_M » | blob Ollama `sha256-60e05f21...` (services.toml:86) | services.toml:86, :1061, :1554 ; forge_provider_specs.py:52, :60 ; nokido_llamacpp_symlinks.bat:9 ; forge_local_llm_bringup.py:226 ; forge_ghost_router.py:50 | `NokidoLlamaNative`, `NokidoLlamaPython` : disabled (a la demande) ; Ollama local |
| 2 | `Qwen/Qwen2.5-Coder-1.5B-Instruct` | `nokido_llamacpp_native.bat:6` et `SERVICES.md:80` « qwen2.5-coder:1.5b-Q4_K_M » ; variante *instruct* = tag Ollama par defaut, **a confirmer** | blob Ollama `sha256-29d8c98f...` (services.toml:87) | services.toml:87, :1061 (`DRAFT_1B`) ; symlinks.bat:10 ; symlinks.bat:11 (`laforge-qwen-1b` = MEME blob) | brouillon du decodage speculatif de `NokidoLlamaNative` |
| 3 | `BAAI/bge-m3` | nom du GGUF ; `"BAAI/bge-m3"` en clair (brain_worker.py:73, forge_bge_m3_shared.py:161) | `data/llm_models/bge-m3-Q8_0.gguf` ; depot GGUF d'origine NON cite | services.toml:1122 ; forge_install_prerequis.py:308 ; worker ONNX services.toml:787 | `NokidoLlamaEmbed` : PERMANENT (pilier embedding) |
| 4 | `BAAI/bge-reranker-v2-m3` | nom du GGUF | `gpustack/bge-reranker-v2-m3-GGUF` (forge_bench_get_reranker.py:16) | services.toml:1155 ; forge_install_prerequis.py:309 | `NokidoLlamaReranker` : disabled, reveil `rerank.wanted` |
| 5 | `microsoft/bitnet-b1.58-2B-4T` | commande de telechargement documentee (forge_bitnet_loader.py:23, :117 ; docs/bitnet_integration.md:25) ; le nom `bitnet_b1_58.gguf` seul ne l'identifie PAS | Hugging Face (meme commande) | services.toml:1139 ; forge_install_prerequis.py:310 | `NokidoLlamaBitnet` : disabled |
| 6 | `1bitLLM/bitnet_b1_58-3B` | cite comme variante testee (forge_bitnet_loader.py:19 ; docs/bitnet_integration.md:30) | non precisee | idem | variante alternative de #5 |
| 7 | `Qwen/Qwen3-8B` | nom du GGUF `qwen3-8b-q4_K_M` | blob Ollama `sha256-a3de86cd...` | symlinks.bat:12 ; nokido_llamacpp_router.bat:15 | `NokidoLlamaRouter` : disabled |
| 8 | `deepseek-ai/deepseek-coder-6.7b-instruct` | nom du GGUF `deepseek-coder-6.7b-q4_0` ; base ou instruct **non precise** | blob Ollama `sha256-59bb50d8...` | symlinks.bat:13 ; router.bat:14 | `NokidoLlamaRouter` : disabled |
| 9 | `google/gemma-4-E4B-it` | nom du GGUF `gemma-4-E4B-it-Q4_K_M` ; identifiant de fiche **deduit** du nom de fichier, a confirmer | blob Ollama `sha256-4c27e0f5...` ; `~/models/gemma4/` | symlinks.bat:14 ; forge_local_llm_bringup.py:227 ; forge_task_router.py:55 ; forge_openai_proxy.py:387 | `NokidoLlamaRouter` : disabled ; Ollama local |
| 10 | `Qwen/Qwen3-0.6B` | nom du GGUF `Qwen3-0.6B-Q4_0` | `unsloth/Qwen3-0.6B-GGUF` (chemin de cache, forge_ghost_router.py:42) | forge_ghost_router.py:37-42 ; forge_llamacpp.py:9 | hors services.toml (llama-cpp-python en processus) |
| 11 | `Qwen/Qwen2.5-1.5B-Instruct` | URL de telechargement | `Qwen/Qwen2.5-1.5B-Instruct-GGUF` (forge_llamaedge_bringup.py:22) | forge_llamaedge_bringup.py:22-23 | hors services.toml (LlamaEdge) |
| 12 | `nomic-ai/nomic-embed-text-v1.5` | chemin du GGUF | `nomic-ai/nomic-embed-text-v1.5-GGUF` fourni par LM Studio | setup_wasmedge_srv.sh:3 ; start_wasmedge_cervelet.sh:2 | hors services.toml (WasmEdge, Linux) |
| 13 | `meta-llama/Llama-3.3-70B-Instruct` | mention « llama 3.3 » ; taille et variante **non precisees** par la config | `ollama pull` | forge_provider_specs.py:52 (`ollama_local`) | Ollama local, a la demande |
| 14 | `deepseek-ai/DeepSeek-R1` | mention « deepseek-r1 » ; variante **non precisee** : un tag Ollama de petite taille peut etre une distillation dont la base (Qwen, Llama) a sa propre licence, **a verifier** | `ollama pull` | forge_provider_specs.py:52 (`ollama_local`) | Ollama local, a la demande |

**Non identifiable, non interroge :** Xiaomi « MiMo v2 Omni », `ollama_mimo_v2`
(forge_provider_specs.py:223, forge_agent_proxy.py:1805, modele `mimo-v2-omni`). Aucune fiche
HF n'est citee par le depot et l'entree est marquee DEPRECATED. Licence : **INCONNUE** (motif :
identifiant de fiche introuvable dans le depot ; le deviner est exclu).

## Licences mesurees -- fiches de l'inventaire

| # | Licence mesuree (fiche HF) | Confirmation sur le poste | Usage commercial | Redistribution avec la distribution AGPLv3 |
|---|---|---|---|---|
| 1 | apache-2.0 | GGUF installe `general.license=apache-2.0`, base `Qwen/Qwen2.5-Coder-7B` ; blob Ollama « Apache License » | oui | oui, notice Apache conservee |
| 2 | apache-2.0 | `qwen2.5-coder:1.5b` et `laforge-qwen` : `general.name` « Qwen2.5 Coder 1.5B **Instruct** » -- variante instruct CONFIRMEE | oui | oui, notice conservee |
| 3 | mit | `data/llm_models/bge-m3-Q8_0.gguf` et Ollama `bge-m3` : mit | oui | oui, notice conservee |
| 4 | apache-2.0 (base et `gpustack/...-GGUF`) | `data/llm_models/bge-reranker-v2-m3-Q8_0.gguf` : apache-2.0 | oui | oui, notice conservee |
| 5 | mit | poids non trouves dans les dossiers lus (service disabled) | oui | oui, notice conservee |
| 6 | mit | idem | oui | oui, notice conservee |
| 7 | apache-2.0 | Ollama `qwen3:8b` : GGUF apache-2.0 | oui | oui, notice conservee |
| 8 | **other -- `deepseek`** (base : `deepseek-license`) | Ollama `deepseek-coder:6.7b` : blob « DEEPSEEK LICENSE AGREEMENT » ; base ou instruct : non tranche par l'en-tete | **A LIRE** (licence propre) | **ses propres termes**, jamais sous AGPLv3 |
| 9 | apache-2.0 | Ollama `gemma4:e4b-it-q4_K_M` : blob « Apache License » ; fiche `google/gemma-4-E4B-it` CONFIRMEE (200) | oui | oui, notice conservee |
| 10 | apache-2.0 (base et `unsloth/...-GGUF`) | non trouve dans les dossiers lus | oui | oui, notice conservee |
| 11 | apache-2.0 | non trouve dans les dossiers lus | oui | oui, notice conservee |
| 12 | apache-2.0 | Ollama `nomic-embed-text` : blob « Apache License » | oui | oui, notice conservee |
| 13 | **llama3.3** (fiche `gated=manual`) | **aucun Llama installe** (aucun manifeste) : cite, pas present | **A LIRE** (licence communautaire) | ses propres termes |
| 14 | mit (`DeepSeek-R1`) | Ollama `deepseek-r1:14b` = **DeepSeek R1 Distill Qwen 14B** (`general.name`), blob MIT ; fiche `deepseek-ai/DeepSeek-R1-Distill-Qwen-14B` : mit | oui | oui, notice conservee |

Hors config (brief elargi) : `Phi-3.5-mini-instruct-onnx` mit ; **`Qwen/Qwen2.5-Coder-3B-Instruct` :
other -- `qwen-research`** ; `unsloth/Qwen2.5-7B-Instruct-bnb-4bit` apache-2.0 ; `Qwen3-Embedding-0.6B`
apache-2.0 ; `Qwen2.5-0.5B-Instruct` apache-2.0 ; `bge-small-en-v1.5` mit ; `MiniLM-L12-H384-uncased` mit ;
`all-MiniLM-L12-v2` apache-2.0 ; `ms-marco-MiniLM-L-6-v2` apache-2.0 ; **`microsoft/graphcodebert-base` :
aucune licence declaree sur la fiche -- INCONNUE**.

**A retenir.**
- `Qwen2.5-Coder-3B-Instruct` est la base de `forge_sft_train.py:40` et `forge_sft_eval.py:47` : un
  adaptateur LoRA entraine dessus herite de la licence `qwen-research`. A LIRE avant toute
  distribution d'un adaptateur. Les tailles 1.5B et 7B de la meme famille sont apache-2.0.
- `deepseek-coder:6.7b` (routeur, disabled) est le seul poids INSTALLE sous licence propre.

## Poids installes sur le poste (Ollama, 16 manifestes)

| Manifeste | Blob de licence (1re ligne) | En-tete GGUF (`general.*`) |
|---|---|---|
| `bge-m3:latest` | MIT License | license mit |
| `deepseek-coder:6.7b` | DEEPSEEK LICENSE AGREEMENT | name deepseek-ai |
| `deepseek-r1:14b` | MIT License | name DeepSeek R1 Distill Qwen 14B |
| `gemma4:e4b-it-q4_K_M` | Apache License | (aucune cle general.license) |
| `laforge-qwen:latest` | Apache License | apache-2.0, base Qwen/Qwen2.5-Coder-1.5B |
| `llava:7b` | Apache License | name liuhaotian ; base de langage NON declaree -- **A VERIFIER** |
| `moondream:latest` | Apache License | name moondream2 |
| `nomic-embed-text:latest` | Apache License | name nomic-embed-text-v1.5 |
| `qwen2.5:latest` | Apache License | apache-2.0, base Qwen/Qwen2.5-7B |
| `qwen2.5-coder:1.5b` | Apache License | apache-2.0, base Qwen/Qwen2.5-Coder-1.5B |
| `qwen2.5-coder:7b`, `:7b-instruct-q4_K_M`, `:latest` | Apache License | apache-2.0, base Qwen/Qwen2.5-Coder-7B |
| `qwen2.5-coder:32b-instruct-q4_K_M` | Apache License | apache-2.0, base Qwen/Qwen2.5-Coder-32B |
| `qwen3:8b` | Apache License | apache-2.0 |
| `huihui_ai/deepseek-r1-abliterated:8b` | MIT License | mit, base deepseek-ai/DeepSeek-R1-0528-Qwen3-8B |

`abliterated` : un tiers a retire les refus du modele. Pas un sujet de licence (MIT), un sujet de
politique d'usage -- a garder hors de toute chaine exposee.

## Modeles accessibles par API (catalogues du 2026-09-29)

Par une API, Nokido ne detient ni ne redistribue aucun poids : ce sont les CONDITIONS DU
FOURNISSEUR qui s'appliquent (non lues par ce job). La licence d'un poids ouvert reste un signal :
elle dit ce que Nokido pourrait auto-heberger, et ce qu'un usage commercial peut exclure.

| Surface | Modeles | Licence mesuree (id HF prouve) | Sans id HF : famille deduite du NOM |
|---|---|---|---|
| openrouter | 464 (20 gratuits annonces) | apache-2.0 76, mit 34, other 40 | openai 104, claude 33, gemini 33, qwen 18, mistral 12, grok 9, autres 55 |
| hf (routeur) | 135 | apache-2.0 49, mit 42, other 23, **cc-by-nc-4.0 12**, gemma 4, llama3.x 4 | -- |
| deepinfra | 187 | apache-2.0 50, mit 28, other 13, gemma 4, llama3 2, cc-by-nc-4.0 1 ; 86 ids hors HF (404) | -- |
| groq | 11 | apache-2.0 4, mit 1 ; 1 en 404 | llama 2, qwen 1, autres 2 |
| nvidia | 81 | -- | llama 15, nemotron 11, gemma 8, mistral 8, granite 4, autres |
| mammouth | 105 | -- | openai 25, gemini 16, claude 15, qwen 10, mistral 7, deepseek 7, autres |
| mistral | 46 | -- | mistral 44 |
| zai | 11 | -- | glm 11 |
| sambanova | 7 | -- | deepseek 2, minimax 2, llama, gemma, gpt-oss |
| cerebras | 2 | -- | qwen, gpt-oss |
| deepseek | 2 | -- | deepseek 2 |
| ollama | 16 | voir « Poids installes » | -- |
| lmstudio, litellm | NON MESURE | services eteints, non reveilles | -- |

« Famille deduite du nom » est un rapprochement LEXICAL, jamais une licence.

**Non commercial (mesure : `cc-by-nc-4.0` ou nom de licence explicite).** Cohere `c4ai-command-a`,
`command-r`, `command-r7b`, `command-a-reasoning`, `command-a-translate`, `aya-expanse-32b`,
`aya-vision-32b`, `tiny-aya-*` ; finetunes `Sao10K/L3-8B-Stheno-v3.2`, `Sao10K/L3.1-70B-Euryale-v2.2`,
`Undi95/ReMM-SLERP-L2-13B` ; images `FLUX-2-klein-9b`, `FLUX.1-Kontext-dev`, `sdxl-turbo`. A garder hors
de toute chaine a usage commercial, sauf conditions contraires du fournisseur (a lire).
`PROVIDER_SPECS` declare `cohere_command_r` et `cohere_command_r_plus` : poids CC-BY-NC-4.0 sur HF ;
leur usage par l'API Cohere releve des conditions de Cohere (non lues).

**Licences propres servies par ces surfaces (`other`, texte non lu).** llama4 ; NVIDIA open model
license / agreement ; openmdw-1.1 ; modified-mit (Kimi K2.x, MiniMax M2.x) ; minimax-community ;
kimi-k3 ; qwen, qwen-research, qwen-community-1.0, qwen3.8-max ; glm-5.3 ; tencent-hunyuan-a13b ;
reka-edge ; lfm1.0 ; deepseek.

**Modeles listes par opencode** (`config/clients/opencode/opencode.jsonc`, tous via la passerelle
:7777 ; le fournisseur `opencode` y est desactive) : `mistral/codestral-latest` et
`mistral/ministral-8b-2512` (API Mistral : conditions du fournisseur) ; `groq/openai/gpt-oss-20b` ;
`openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (**nvidia-open-model-agreement**, a
lire) ; `lmstudio/qwen2.5-coder-7b-instruct` (apache-2.0, ligne 1).

**Providers declares dans `PROVIDER_SPECS` sans catalogue interroge** (hors des surfaces du
recensement) : claude, claude_agent_sdk, claude_cli, cohere_command_r, cohere_command_r_plus,
gemini_cli, gemini_flash, gemini_flash_lite, github_codestral, github_gpt41_mini, github_gpt4o_mini,
github_llama_70b, github_deepseek_v3 (range a tort sous `deepseek` par un rapprochement de nom),
glm4, glm5, kimi_k2, kimi_thinking, llamacpp_local (= poids locaux ci-dessus), openai, perplexity,
xai_grok3, xai_grok3_mini. Modeles proprietaires ou servis par un tiers : conditions NON LUES.

## Hors perimetre, non interroge

- **Modeles cloud en API** (groq, gemini, openrouter, cerebras, sambanova, kimi, glm,
  claude, openai, mistral, xai, deepseek, perplexity...). Nokido n'en manipule jamais les
  poids. Ce sont les conditions d'usage de chaque fournisseur qui s'appliquent, pas une
  licence de poids.
- **Modeles nommes dans le code hors config**, telecharges par un script ou utilises en
  entrainement ou en banc : `microsoft/Phi-3.5-mini-instruct-onnx` (tools/download_phi35.py:18),
  `Qwen/Qwen2.5-Coder-3B-Instruct` (forge_sft_train.py:40, forge_sft_eval.py:47),
  `unsloth/Qwen2.5-7B-Instruct-bnb-4bit` (forge_night_trainer.py:134),
  `Qwen/Qwen3-Embedding-0.6B` (forge_espace_vectoriel_preuve.py:84),
  `Qwen/Qwen2.5-0.5B-Instruct` (forge_recursive_link.py:29), `BAAI/bge-small-en-v1.5`
  (forge_task_router.py:433), `microsoft/MiniLM-L12-H384-uncased`, `microsoft/graphcodebert-base`
  (forge_npu_embedder.py), `sentence-transformers/all-MiniLM-L12-v2` (forge_npu_direct.py:52),
  `cross-encoder/ms-marco-MiniLM-L-6-v2` (forge_cascade_oracle.py:54). A inclure si le
  perimetre est elargi.
- **Poids propres** (AMI/JEPA `.npz`, `pca_64.npz`, `forge_embed_bridge.npz`) : entraines ou
  calcules localement, sans licence de tiers.

## Ce qui reste

1. Lire le TEXTE des licences propres en jeu : `deepseek` (poids installe), `qwen-research` (base
   LoRA SFT), `nvidia-open-model-agreement` (liste opencode), `llama3.3` (cite), et les conditions
   des fournisseurs API utilises (Mistral, Groq, OpenRouter, Cohere...).
2. LM Studio : inventaire depuis la session owner (`lms ls`) ; ce compte lit `~/.lmstudio/models` vide.
3. `llava:7b` : l'en-tete ne declare pas sa base de langage -- a verifier avant toute redistribution.
4. `graphcodebert-base` : aucune licence declaree sur sa fiche -- INCONNUE.
5. Rejouer la mesure : `C:/tmp/corrections/licences_modeles_hf.py` (hors depot, artefact
   `licences_modeles_resultat.json`) ; a promouvoir en outil gouverne si l'inventaire doit etre
   periodique.
6. Pour « Compat. AGPLv3 », la regle appliquee ci-dessus : dire si le poids peut
   etre redistribue avec la distribution AGPLv3 (une licence permissive impose de garder sa
   notice ; une licence a conditions d'usage garde ses propres termes et ne passe jamais
   sous AGPLv3). Aucune licence de poids ne change la licence du code de Nokido, qui charge
   ces poids comme des donnees.
