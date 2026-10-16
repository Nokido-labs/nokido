# 04 — Synthèse du débat « analogie au corps » (15/10, rédigée par CLAUDE)

Voix : **00** Codex (diagnostic, verbatim) · **01** Claude · **02** AGY (M2M, 2e essai) · **03** swarm (4 réponses
réelles sur 9) · **05** réponse de Claude à la demande de Codex sur la visibilité du live. Ce document résume ; il ne
remplace aucune voix, et les arbitrages ci-dessous sont des PROPOSITIONS pour l'owner.

## Consensus (les quatre voix convergent)
1. **Ne pas ajouter d'organes : prouver que les boucles se ferment** (Codex, Claude, AGY ; le swarm n'en propose pas).
2. **Le schéma corporel est déclaré, pas mesuré.** Codex le soupçonnait, Claude l'a mesuré (census « live, rien ne
   manque », `regulation_gaps` 0/2 012, contre six écarts réels du jour), AGY le confirme par le code
   (`forge_anatomy_state` affiche lui-même « topologie DECLAREE, pas une mesure »).
3. **Un réflexe est une inhibition conservatrice** (refuser, freiner, basculer en local), jamais une action
   destructrice ; rollback = levée du veto (Codex, AGY, Claude).
4. **Simplifier les chemins dupliqués, pas les organes dormants** (AGY : 110 « zones mortes » sur 194 étaient des
   outils au repos ; Claude : 4 sondes HTTP pour un même geste).

## Désaccords à trancher (owner)
**A. La première boucle à prouver.** Codex : ressource → régulation · Claude : budget cloud · AGY : boucle
nociceptive (refus → repli → consignation) · gemini : validation humaine des leçons · deepseek : budget cloud.
→ **Proposition de fusion** : la boucle **nociceptive et métabolique**. Un 429 « per day », un refus de sandbox, un
refus de ring sont la MÊME douleur : capteur (refus typé) → signal normalisé (`BLOCKED_BY_BARRIER`, barrière,
repli suggéré) → prédiction métabolique (budget restant vs travail prévu) → repli réversible (autre modèle, autre voie,
étaler) → mesure (tâche faite ou non, verdict valide ou non). Les échecs du jour la couvrent tous : quota groq et faux
banc, sandbox d'AGY (1er essai muet), événement durable refusé à Codex, `introspect` expirés.

**B. L'instinct.** Claude : déclaration portée par l'organe · AGY : « schéma mort si aucun récepteur ne l'évalue ;
l'encoder au chargement ». → Compatibles : la déclaration `# nokido-compte:` est DÉJÀ évaluée à chaque appel par le
gate (`afecf5e72`, preuve réelle) ; l'extension proposée par AGY (vérifier les déclarations au chargement) s'ajoute.

**C. La mémoire.** Claude : transmettre sans perte (pack natif) · AGY et Codex : oublier (demi-vie, archivage froid).
→ Pas contradictoires : la **transmission** (pack public, ce qui est publié) doit être complète par construction ; la
**mémoire de travail** (RAG privé, 9 M fragments) doit oublier, gelée et non supprimée.

**D. Le cerveau.** Claude : un arbitre unique · AGY : bicaméral (bulbe local `classify()` déterministe + cortex hub).
→ La mesure du jour donne raison à AGY : le hub est tombé deux fois (MCP coupé, moniteurs perdus) et tout s'arrêtait.

## Angles morts apportés par le débat
- **Nociception** (AGY) : aucune voie normalisée pour « on m'a refusé, voici l'alternative ».
- **Biodiversité métabolique** (AGY) : forfaits, quotas, local gratuit — l'homéostasie doit répartir selon le régime.
- **Validation externe par l'owner** (gemini) : les leçons ancrées (`anchor_solution`) ne sont validées par personne.
- **Coût métabolique des boucles** (deepseek) et **réflexes qui désapprennent** (mistral) : le gate promeut un rappel en
  mur, mais rien ne dé-promeut un mur qui crie à faux ni ne mesure son taux de faux positifs.
- **Curiosité intéroceptive** (AGY) : `detect_self_gaps` existe, mais elle se nourrit de `regulation_gaps`, qui rend 0
  — une curiosité alimentée par un instrument aveugle n'a rien à chercher.

## Ce que le débat a lui-même révélé (mesuré, corrigé ou consigné)
| Fait | Faculté | Suite |
|---|---|---|
| swarm : coroutine non attendue, session perdue | muscles | corrigé `a564c5880` |
| swarm : 3 erreurs comptées en succès (7 annoncées, 4 réelles) | proprioception | corrigé `3983fc110` |
| AGY : shell refusé par le sandbox, arrêt sans artefact | nociception | piège 8 de la skill m2m-agy |
| Codex : aucune référence obtenue, événement durable refusé (ring 2) | nociception | référence retrouvée : `frm_69403423ec20` |
| Codex : `introspect` / `rag` larges expirés | métabolisme | 05 : appels nommés et bornés |

## Décisions de l'owner (15/10 au soir, « ok go »)
Les quatre propositions ci-dessus sont adoptées : **A** boucle nociceptive et métabolique en premier ; **B** déclaration
évaluée à l'appel (fait) + vérification au chargement ; **C** transmission publique complète, mémoire de travail qui
oublie par gel ; **D** cerveau bicaméral. Avec la contrainte de Codex (`06_codex_final.md`) : aucun nouvel organe
avant la cartographie des lecteurs, écrivains et boucles — on étend l'existant (les intents d'erreur M2M
`ERR_RBAC_DENY`, `ERR_TIMEOUT`, `BUDGET_EXCEEDED` existent déjà). SSoT : `decision_owner_debat_anatomie_A_D_20261015`.

## Prochaines preuves proposées (sur GO owner)
1. **Boucle nociceptive et métabolique** (A) : un refus normalisé dans les réponses du hub, et un repli mesuré.
   Métrique : refus suivis d'un repli réussi / refus.
2. **Schéma mesuré** : régénérer le census (17 j) et publier l'écart déclaré/observé. Métrique : écarts détectés par
   le corps lui-même / écarts trouvés par un agent.
3. **Réflexes qui désapprennent** : taux de faux positifs par mur, et dé-promotion.
4. **Boucle de validation owner** des leçons ancrées.
