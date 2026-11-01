# Enquête — traduire FR→EN pour économiser les tokens (28/10/2026)

**Question de l'owner.** Peut-on traduire à la volée, en local (0 token), les entrées et sorties en anglais pour
payer moins de tokens, puisque l'owner travaille en français ? Et en chinois pour un modèle chinois ?

**Décision de l'owner (28/10, clôture).** « On en reste là pour le moment, il ne faut pas casser la qualité de la
réflexion. » Aucune traduction branchée. Venv du banc supprimé ; cette trace conservée.

## Ce qui a été réfuté d'emblée

| Affirmation | Preuve | État |
|---|---|---|
| Les chiffres et projets cités par Gemini web (SelenaCore, TokenTranslation, arXiv 2604.14210, gains annoncés) | aucun vérifiable ; seul LLMLingua-2 est connu | NON VÉRIFIÉ, non repris |
| Le chinois coûterait moins de tokens | tokenizers BPE : chaque sinogramme pèse 3 octets en UTF-8 | RÉFUTÉ (sens de l'écart) |
| Traduire « à la volée » dans Claude Code | aucun hook ne réécrit le prompt ni la sortie du modèle (`UserPromptSubmit` ajoute du contexte ou bloque) | IMPOSSIBLE ; seulement sur les appels LLM de Nokido (`pre_flight`/`post_flight`) |

## Protocole

`tools/forge_bench_traduction.py` (100 % local : CTranslate2 int8, Helsinki-NLP opus-mt fr-en / en-fr, tiktoken),
corpus RÉEL lu en lecture seule : 20 prompts de l'owner (5 conversations Claude Code les plus récentes), 7
documents résidents (CLAUDE.md ×2, RULES_SHARED.md, MEMORY.md, injections de hooks), 10 consignes d'exécuteurs
(`sandbox/tasks.db`), 5 sorties d'outils. Identifiants masqués avant traduction, restaurés après ; rétro-traduction
EN→FR pour juger le sens. Tokenizers o200k / cl100k = APPROXIMATIONS (celui de Claude n'est pas public).

## Cinq passages : quatre pièges avant une mesure valide

| Passage | Symptôme | Cause | Correctif |
|---|---|---|---|
| 1 | « n'avance pas » | les 3 volets parcouraient TOUTES les conversations (centaines de Mo), sans progression | 5 conversations récentes, progression (4153a10f5) |
| 2 | ne se termine pas | un lot unique de toutes les lignes, beam 2, 512 tokens fixes | lots de 16, décodage borné à l'entrée (47a3f5f26) |
| 3 | `No position encodings are defined for positions >= 512` | MarianMT n'a que 512 positions | découpage des lignes longues (5f25e9620) |
| 4 | gain **−233 %**, sorties en BOUCLE | entrée MarianMT sans `</s>` : le décodeur ne s'arrête qu'au plafond | `</s>` ajouté/retiré, pénalité de répétition (2245b7901) |
| 5 | mesure valide | — | rapport `docs/mesures/bench_traduction_2026-10-28.md` (48b4cf3f2) |

Leçon : **lire les échantillons avant les chiffres** — le −233 % était une mesure de boucles, pas de traduction.

## Résultat (passage 5)

| Volet | Gain o200k | Gain cl100k | Identifiants intacts |
|---|---|---|---|
| Prompts de l'owner (20) | 13,5 % | 20,8 % | aucun à protéger |
| Documents résidents (7, ~10 300 tokens) | 13,8 % | 17,1 % | 94,7 % (251/265) |
| Consignes d'exécuteurs (10) | 12,6 % | 16,8 % | 97,3 % |
| Sorties d'outils (5, déjà en anglais) | 2,3 % | 2,8 % | 82 % |

**Qualité, ce qui a tranché :** contresens sur des consignes (« Consigne owner permanente » → « Permanent owner
sign », « tâche du backlog » → « backlog spot », CI → IC, « plus AUCUN Agent Claude » → « more NONE Agent
Claude », faute de frappe de l'owner → « connection wanderers ») ; identifiants JSON abîmés (`"task_id":"bkg6g
m3c5"`, `tsk_type`, casse modifiée) ; statut `ILLISIBLE` du code perdu ; « caveman » → « cellarman ».

## Verdict

1. Pas de traduction à la volée par un petit modèle local : 13-17 % de gain contre des contresens sur des
   consignes et des identifiants faux — le coût en erreurs dépasse le gain, et la qualité de la réflexion prime.
2. Seul gisement notable : les documents résidents (~1 400 tokens/tour économisables par une traduction UNIQUE,
   faite par un modèle fort et relue) — atténué par le cache de prompt (~0,1× le prix) ; non retenu.
3. Le levier qui rapporte le plus reste le VOLUME (déport des sections, compaction de l'index mémoire).

## Pour reprendre un jour

Outil et NR conservés (`tools/forge_bench_traduction.py`, `tests/nr/test_bench_traduction*_nr.py`) ;
`--setup` recrée le venv isolé (~1 Go, `sandbox/workspace/trad_env`) ; la mesure tourne sous le compte owner
(les volets 1 et 2 lisent le profil owner, invisible au compte du hub). Modèles convertis restants :
`sandbox/workspace/models` (~600 Mo) et cache Hugging Face du profil owner (~1,2 Go) — à supprimer sur accord.
