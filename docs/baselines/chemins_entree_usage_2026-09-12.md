# Chemins d'entree de l'usage LLM — etat MESURE au 2026-09-12

Exige par l'owner **avant A4** : migrer une base dont la semantique n'est pas
etablie reviendrait a transporter le flou. Chaque case est une MESURE ou un
`NON VERIFIE` assume — aucune n'est une deduction depuis le code.

Etats : **PROUVE** (lu en base) · **PARTIEL** (present, incomplet) ·
**ESTIME** (calcule localement) · **UNKNOWN** (pas de chemin, ou pas mesure).
`NON CABLE` = le code existe et personne ne l'appelle.

## La chaine, telle qu'elle est apres A3

    client -> entrypoint -> adapter -> LLMUsageEvent -> log_call -> token_usage
                                                       (unique writer)

## Tableau

| chemin | entrypoint | adapter | recorder | etat |
|---|---|---|---|---|
| **CLAUDE CLI** (Claude Code) | hook statusline, payload stdin | `depuis_claude` | `log_call` | **CABLE ET PROUVE** |
| **CLAUDE Desktop stdio** | `mcp_stdio_bridge` | aucun | aucun | **UNKNOWN — aucun chemin** |
| **CLAUDE M2M / provider** | `forge_agent_proxy` (provider `claude_cli`) | aucun | `log_call` | **PARTIEL** |
| **AGY CLI** | `forge_agent_proxy` (provider `gemini_cli`) | `depuis_agy` **NON CABLE** | `log_call` | **PARTIEL, non distingue de AGY M2M** |
| **AGY M2M** (autonome) | postal / `forge_gemini_autonomous_agent` | `depuis_agy` **NON CABLE** | `log_call` | **PARTIEL, non distingue de AGY CLI** |
| **CODEX** | — | `depuis_codex` **NON CABLE** | — | **UNKNOWN** (1 ligne, 2026-08-04) |

## Detail par champ — mesure en base

| champ | CLAUDE CLI | CLAUDE M2M | AGY CLI | AGY M2M | CODEX |
|---|---|---|---|---|---|
| input / output tokens | **PROUVE** (in=2, out variable) | PARTIEL | PARTIEL | PARTIEL | UNKNOWN |
| cache_read / cache_write | **PROUVE** (CR=433309, CW=4874) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| reasoning_tokens | UNKNOWN (absent du payload) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| session_id | **PROUVE** (uuid REEL du client) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| execution_id | UNKNOWN (colonne absente) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| provenance / mode / transport | UNKNOWN (colonnes absentes) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| measurement_kind | UNKNOWN (colonne absente) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| cost_usd | **FAUX ZERO** | **FAUX ZERO** | **FAUX ZERO** | **FAUX ZERO** | UNKNOWN |

## Les quatre defauts que ces mesures etablissent

1. **`total_tokens` ignore le cache.** `total = input + output` : une ligne
   reelle porte `total=4` pendant que `cache_read_tokens=433309`. Sur Claude,
   le total sous-estime de cinq ordres de grandeur. Il ne doit pas etre lu
   comme la consommation.

2. **`cost_usd = 0.0` sur 4663 / 7859 lignes (59 %), et ZERO NULL.** `_price`
   rend `0.0` pour un modele inconnu : « gratuit » (ollama 979,
   openrouter_free 562, router_local 51) et « non tarife » (groq 1149,
   gemini_cli 744, cerebras 153, claude_cli 114) sont INDISCERNABLES. Un cout
   inconnu doit valoir NULL. C'est `UNKNOWN != 0` applique a la monnaie.

3. **Double comptage preexistant : 98 groupes, 98 lignes en trop**, du
   2026-06-05 au 2026-09-11, **100 % `forge_agent_proxy`** (1,2 % de la table).
   Signature = meme ts, agent, provider, prompt et completion. Le writer unique
   ne le corrige pas : c'est un double APPEL, pas un double writer. Les 20
   lignes CLAUDE neuves n'en portent **aucun**.

4. **AGY CLI et AGY M2M sont INDISCERNABLES en base.** Tous deux arrivent par
   `forge_agent_proxy` avec `provider='gemini_cli'`. C'est exactement la
   question a laquelle l'owner veut repondre, et aujourd'hui la base ne le
   peut pas. Le tuple provenance/mode/transport est ce qui les separera.

## Ce qui n'a PAS ete verifie, et qui doit l'etre avant de conclure

- **Origine des compteurs de `gemini_cli` et `claude_cli`** : rapportes par le
  fournisseur, ou calcules localement ? Un CLI ne rend pas toujours d'usage.
  Tant que ce n'est pas mesure, ces lignes ne peuvent etre marquees ni
  REPORTED ni ESTIMATED — elles sont **INDETERMINEES**.
- **Claude Desktop stdio** : rien ne prouve qu'aucun usage ne transite ; ce qui
  est prouve, c'est qu'**aucun adapter n'est cable** sur ce chemin. Absence de
  chemin, pas absence de trafic.
- **`forge_agent_proxy`** appelle `log_call` mais n'est pas un writer SQL : sa
  chaine exacte d'appel n'a pas ete tracee ligne a ligne.

## Consequence pour la suite

A4 (provenance) doit fournir : `execution_id`, `parent_execution_id`,
`provenance`, `execution_mode`, `transport`, `measurement_kind`,
`measurement_source` — **transportes depuis l'entree**, jamais deduits du
module ecrivain. `agent_id` reste, mais comme `writer_component`.

La migration (A6) n'a de sens qu'apres : migrer maintenant transporterait
4663 faux zeros, 98 doublons et une provenance absente dans la base cible.
