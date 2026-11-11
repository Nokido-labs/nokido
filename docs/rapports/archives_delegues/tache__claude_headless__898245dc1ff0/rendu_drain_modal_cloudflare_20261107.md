# Drain d'embedding : Modal et Cloudflare (2026-11-07)

## Module du drain
`forge_retrieval_sweep` n'est pas le drain (c'est un balayage multi-surface). Le drain est `tools/forge_reindex_deport.py`.
Il fait `_apply_vault_keys_to_fre` puis `phase_b_embed`. Son journal est `C:/tmp/reindex_deport.log`.
Le journal `logs/supervisor/NokidoDeportEmbed.log` est revenu vide à la lecture (0 ligne).

## (1) Modal est-il dans la chaîne ?
Non. `PROVIDERS` du drain = HF, DeepInfra, Cloudflare, Nvidia, plus `local` :8099 en dernier.
- Modal n'existe que dans `app/forge_embed_router.py` (`_modal_call`, `_essais_batch`). Le drain n'appelle pas ce routeur pour ses 4 providers cloud.
  Il n'importe du routeur que `_llama8099_call` et `encode_blob`.
- Modal n'y a donc jamais été câblé.
  - Le drain a été écrit le 05/06 avec 4 providers cloud.
  - `local` a été ajouté le 03/08.
  - L'endpoint Modal a été déployé le 19/08, d'après le docstring de `_modal_url`.
- Limite : je n'ai pas pu lancer `git log`. Ces dates viennent des commentaires du code, pas de l'historique git.
- Le « ça a déjà fonctionné » de l'owner vaut pour le routeur (`embed_batch`), pas pour le drain.

## (2) Le 429 de Cloudflare
- Dernière élection réussie dans `C:/tmp/reindex_deport.log` : **2026-11-07 00:53:31Z**, 0,4 s pour 20 textes.
- À 01:10:05Z, `local` est retenu. Cloudflare est en 429 à chaque vague suivante (03:51, 04:51, 08:49).
- Le 06/11, Cloudflare passe en `local` à 13:52Z, puis revient à 21:26Z. Ce retour n'est pas à minuit UTC.
- **Verdict : quota ou cadence, pas compte.**
  - La clé et le compte sont valides, puisque les succès durent jusqu'au 07/11 00:53.
  - Ce n'est pas un quota journalier simple, puisqu'il ne se réinitialise pas à une heure fixe.
  - Je ne peux pas trancher entre quota glissant et cadence : le journal coupe le corps de la réponse à 90 caractères.
- Chaque vague dépense le gratuit en environ une heure. Les autres providers sont morts :
  - Nvidia 410
  - DeepInfra 402
  - HF 402
- Le code respecte déjà le 429 sans boucle :
  - à l'élection, il écarte le provider ;
  - en cours de vague, il s'arrête proprement (`return -1`) ;
  - la vague horaire suivante retente.
- Ajouté : la mention « quota/cadence : écarté sans réessai » dans le journal.
- Piste non faite : lire `Retry-After`, ce qui demande de changer `_post` dans `forge_rebuild_embeddings`.

## (3) Changements
Dans `tools/forge_reindex_deport.py` :
- `_elire_provider` : l'élection est extraite en fonction testable. Un seul essai par provider, et la tolérance de durée est propre à chaque provider (`duree_max`, 25 s par défaut).
- Provider `Modal` : tolérance 150 s et timeout 150 s (`LAFORGE_EMBED_MODAL_TIMEOUT_S`) pour couvrir le démarrage à froid de 66 s. Le provider vérifie qu'il reçoit 1024 dimensions et autant de vecteurs que de textes.
  - `_PREF` : Modal (-1), Cloudflare (0), Nvidia, DeepInfra, HF, local (9).
  - Le secret passe par `_modal_url`, donc par `get_secret` et son nom. Aucune valeur n'est écrite dans un log ou un test.
- **Garde-fou :** Modal n'est câblé que si `LAFORGE_EMBED_MODAL_VALIDE=1`. Le code est donc branché mais inactif par défaut.
  - Aucun redémarrage n'a été fait et la variable n'est pas posée.
  - Cloudflare reste actif comme avant, car il est déjà en production.

Tests, dans `tests/nr/test_deport_embed_selection_indexee_nr.py` :
- Réseau simulé, aucune base touchée.
- Rouge d'abord : 3 échecs (`_elire_provider` absent).
- Vert ensuite : 5 passés.
- Les tests couvrent :
  - Modal retenu après 66 s simulées ;
  - Cloudflare en 429 appelé une seule fois, puis `local` ;
  - Modal derrière l'interrupteur ;
  - un provider lent sans tolérance reste écarté.

## Protocole de vérification de l'espace commun
Non exécuté : il demande du réseau et les secrets du coffre. Il n'ouvre aucune base et n'écrit aucun vecteur.
1. Lot de 100 à 200 textes publics en français et en anglais, de longueurs variées. Sources possibles : docs publiques, licences, extraits Wikipédia. Il ne contient aucun texte issu de la base.
   - Vérifier qu'aucun texte ne contient de secret (`masquer_pour_cloud` s'applique de toute façon).
   - Fixer le lot dans un fichier versionné et en noter le hash.
2. Calculer les vecteurs avec trois chemins, tous en mémoire :
   - local `_llama8099_call` (:8099 doit être éveillé, sinon la référence est absente) ;
   - Modal `_modal_call`, premier appel de chauffe à ne pas compter ;
   - Cloudflare `_cloudflare_call`, en respectant le 429, avec un lot par minute au plus.
3. Vérifier la forme : dimension 1024 et nombre de vecteurs égal au nombre de textes.
   - Normes : si un chemin rend des vecteurs non normalisés, comparer après normalisation L2 et le noter.
4. Cosinus texte à texte entre les chemins, pour les paires local-Modal, local-Cloudflare et Modal-Cloudflare.
   - Seuil : **min cos ≥ 0,9990** et médiane ≥ 0,9995, soit le seuil du 05/11 sur un lot dix fois plus gros.
   - Test de discrimination : pour chaque texte, son vecteur voisin (même texte dans un autre chemin) doit être le plus proche parmi tous les autres textes. Rang 1 dans 100 % des cas.
5. Verdict :
   - Modal : poser `LAFORGE_EMBED_MODAL_VALIDE=1` seulement si les paires local-Modal sont toutes au seuil.
   - Cloudflare : même critère. S'il échoue, Cloudflare doit être retiré du drain, car il écrit déjà des vecteurs en base.
   - Sortie : un petit JSON avec la date, le hash du lot et les statistiques min, médiane et rang. Aucune valeur de secret, aucun vecteur écrit en base.

## Interdits respectés
- Aucune requête sur `%NOKIDO_DATA%\embeddings.db`. Je n'ai pas lancé `phase_b_embed`, qui fait un `COUNT` sur cette base.
- `config/agent_identities.json` non touché.
- Pas de redémarrage ni de push.

{"intent":"OK_DONE","pointer_ref":"rendu_drain_modal_cloudflare_20261107.md"}
