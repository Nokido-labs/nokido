# 03 — Voix du SWARM (surface `forge_swarm_team`, 15/10)

**Comment** : `launch_team` sur l'équipe enregistrée, 9 participants activés EN MÉMOIRE (l'équipe enregistrée n'est
pas modifiée), même question à tous : un dossier de 20 lignes résumant 00 (Codex) et 01 (Claude), réponse ≤ 250 mots.
Réponses brutes : `C:/tmp/drafts/anatomie/swarm_resultats.json`. Aucun juge LLM : la lecture ci-dessous est la mienne
(CLAUDE) et elle est dite comme telle.

## Mesure de la session (avant tout contenu)
| Participant | Résultat |
|---|---|
| gemini | réponse réelle (6,1 s) |
| groq (via routeur) | réponse réelle, tronquée à 614 car. (6,0 s) |
| deepseek (via routeur) | réponse réelle (16,4 s) |
| mistral (via routeur) | réponse réelle (10,9 s) |
| groq_direct, groq_70b | `[groq error] HTTP 403` — **comptés `ok=True` par la surface** |
| hf_qwen | `litellm.BadRequestError` (modèle inconnu) — **compté `ok=True`** |
| laforge (ollama), litellm | délai de 30 s dépassé (`ok=False`) |

**4 réponses réelles sur 9.** Deux défauts de l'organe swarm lui-même : (1) une coroutine non attendue faisait perdre
toute la session au 1er essai (corrigé `a564c5880`) ; (2) une chaîne d'erreur est rangée en succès (faux vert, à
corriger). Et un défaut de MA question : trois participants ont lu l'analogie au pied de la lettre (capteurs IMU,
électromyographie, réflexe thermique) — le dossier ne disait pas que Nokido est un LOGICIEL.

## Ce qui est exploitable
- **gemini — angle mort : la validation EXTERNE par l'humain.** Les thèses ferment des boucles internes ; aucune ne
  ferme la boucle « leçon apprise → validée ou rejetée par l'owner ». Boucle proposée en premier : la validation des
  leçons apprises par l'humain, avant tout investissement dans des facultés avancées.
- **deepseek — angle mort : le COÛT MÉTABOLIQUE des boucles.** Une prédiction ratée peut consommer une part du budget
  cloud sans alerte. Rejoint la boucle budget cloud de 01 : « si le budget est épuisé sans réflexe d'urgence, le
  système est en état UNKNOWN avant même la panne ».
- **mistral — objection à la thèse 2 de Claude (« le savoir descend en réflexes »).** Un réflexe appris a besoin d'une
  boucle de RENFORCEMENT (récompense, désapprentissage), pas d'un hook statique. Boucle proposée : survivre 72 h sans
  cloud après la perte de la plupart des capteurs, avec un journal des erreurs.

## Réponses brutes (recopiées, coupes du modèle comprises)
### gemini
> Renforcements : Cerveau — densification des connexions pour chaque nouvelle donnée (taux d'adaptation) ; Instinct —
> neurones « vigie » des écarts aux schémas connus (temps de détection d'une anomalie inédite) ; Proprioception —
> « jumeau numérique » temps réel par fusion de capteurs redondants (concordance au réel). Angle mort : les thèses
> ferment des boucles internes et négligent la boucle de validation externe par l'humain, cruciale pour l'innovation
> et la simplification, liées à la perception humaine de la valeur. Boucle à prouver : la validation des « leçons
> apprises » par l'humain, avant toute faculté avancée.

### groq (tronquée par le modèle)
> Proprioception — fusionneur de capteurs + filtre EKF (erreur de pose < 1 %) ; Réflexes — sous-système temps réel
> (latence < 10 ms pour 95 % des stimuli) ; Prédiction — modèle bayésien séquentiel (précision > 90 … [coupé]

### deepseek
> Réflexes — latence stimulus → réponse (< 50 ms) ; Curiosité — taux de découvertes utiles (logs d'actions + surprise
> prédictive) ; Autorégulation — stabilité homéostatique (écart type des paramètres vitaux sur 24 h < 10 %).
> Angle mort : le coût énergétique des boucles ; une prédiction erronée peut consommer 30 % du budget cloud sans alerte,
> un réflexe mal calibré peut désynchroniser la proprioception. Boucle : « si le budget cloud est épuisé sans réflexe
> d'urgence (P1), le système est en état UNKNOWN avant même la détection d'une panne ».

### mistral
> Instinct — temps de réaction aux stimuli critiques ; Curiosité — ratio exploration/évitement ; Mémoire — précision
> des rappels contextuels sous stress. Angle mort : « le savoir descend en réflexes » ignore la plasticité
> hiérarchique ; un réflexe appris exige une boucle avec rétroaction (dopaminergique), non modélisable par des hooks
> statiques. Boucle : survivre 72 h en autonomie totale sans cloud après une coupure de 90 % des capteurs, proprioception
> > 90 %, journal d'erreurs traçable.

## Lecture de CLAUDE (dite comme telle)
- L'objection de mistral est juste et déjà PARTIELLEMENT couverte : le gate de capacités PROMEUT un rappel en mur après
  3 récidives (c'est un apprentissage), mais rien ne DÉ-PROMEUT un mur qui crie à faux, ni ne mesure son taux de faux
  positifs. Le renforcement doit marcher dans les deux sens.
- L'angle mort de gemini est le plus important des trois : `anchor_solution` écrit des leçons que personne ne valide.
- Le point de deepseek confirme la boucle budget cloud comme premier banc.
