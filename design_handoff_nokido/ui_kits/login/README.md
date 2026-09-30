# UI Kit — Verrouillage & langue (startup)

Couche de **verrouillage au démarrage** de Nokido, fidèle à la philosophie souveraine : le coffre est **local**, le déverrouillage ne quitte jamais l'appareil.

## Contenu

- **Logo animé** (cartoon : le marteau frappe l'enclume → éclair).
- **Mot de passe local** avec afficher/masquer, état d'erreur.
- **Biométrie** (option de déverrouillage rapide).
- **Phrase de récupération** (lien discret).
- **Choix de langue** en haut à droite — **FR / EN / ES / DE** ; tout le texte de l'écran est traduit en direct (i18n).
- Marqueur de provenance « LOCAL · hors-ligne » + pied `Ring 0 · nœud souverain`.

Déverrouiller (mot de passe ≥ 3 caractères, ou biométrie) → écran « coffre déverrouillé » qui mène au hub.

## Fichiers

- `index.html` — entrée interactive (responsive PC + mobile).
- `login-screen.ref.jsx` — l'écran + le dictionnaire i18n (`I18N`) et le sélecteur de langue.

## Composants réutilisés

`TextInput`, `Button`, `ProvenanceBadge` — du design system.

## À faire / pistes

- Ajouter d'autres langues (le dico `I18N` est extensible — une clé par langue).
- Persistance du choix de langue (localStorage `nokido.lang`) et synchro avec `data-theme`.
- Multi-profils / multi-nœuds sur la même machine.
