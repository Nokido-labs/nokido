# Bench traduction FR->EN (2026-10-28)

Statut : OK. Tokenizers = approximations (pas celui de Claude).

| Volet | n | gain o200k % | gain cl100k % | ids intacts | latence s |
|---|---|---|---|---|---|
| 1_prompts_owner | 20 | 13.5 | 20.75 | 0/0 | 3.02 |
| 2_documents_residents | 7 | 13.8 | 17.1 | 251/265 | 8.08 |
| 3a_consignes_executeurs | 10 | 12.57 | 16.82 | 110/113 | 8.08 |
| 3b_sorties_outils_hub | 5 | 2.27 | 2.75 | 46/56 | 1.87 |

RAM ajoutee (Mo) : 204

| Affirmation | Preuve | Etat |
|---|---|---|
| Gain de tokens | comptage tiktoken ci-dessus, JSON bench_traduction_2026-10-28.json | MESURE |
