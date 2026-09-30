<!-- DEPORTE depuis RULES_SHARED.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de RULES_SHARED.md, re-facture a chaque tour. -->

# Vision partagée du corps de Nokido — SSoT anatomie (2026-07-14)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## Vision partagée du corps de Nokido — SSoT anatomie (2026-07-14)

Nokido = organisme, pas un tas de scripts. TOUS les agents clients (Claude, Gemini,
AGY/Antigravity, Codex, Copilot) raisonnent sur la MÊME carte du corps — sinon
« où vit X », « quel organe », « quelle pathologie », « que sait faire Nokido »
divergent d'un agent à l'autre. La vision ÉMANE de LaForge (census + skills), elle
n'est dictée par AUCUN agent (cf. principe : l'alignement émane de LaForge).

Source de vérité UNIQUE, tool-agnostic — déréférencer, ne PAS re-décrire ici :
- **Carte organe→module** : census auto-courant `sandbox/workspace/organ_map_full.json`
  (714 forge classés, 0 orphelin) + `module_inventory.md`. Régén 0-token :
  `LAFORGE_PYTHON tools/forge_module_census.py`. Vue narrative humaine = `CLAUDE.md §10`.
- **Diagnostic** (organe → pathologie → remède) : skill `forge-anatomy`.
- **Capacités par organe + accès à l'état vivant** (SSoT/MEMORY/blackboard/RAG) :
  skill `forge-capability` (généré depuis le census).

Réflexe partagé : AVANT d'affirmer qu'un module n'existe pas, d'en créer un, ou de
diagnostiquer un comportement système → consulter cette carte. C'est le préalable de
l'anti-dup ci-dessous. Un agent qui ignore la carte du corps = désaligné, quelle que
soit son égalité de capacités d'action (ring/tools).

### Un module NEUF déclare son organe — le code nourrit le corps (2026-07-25)

Le corps ne devine pas : il lit. Le rattachement d'un module suit quatre autorités
décroissantes (`tools/forge_module_census.organ`) — carte explicite, mot-clé du nom,
dossier, puis **déclaration du module lui-même** :

```python
__FORGE_COLOR__ = "cognition/sense-of-agency"   # organe + rôle, en clair
```

Un module que ces quatre filets ne placent pas ressort **`non classe`**, et un module
non classé est un module dont personne ne surveille la régulation. **Donc : tout
nouveau `forge_*.py` porte sa déclaration.** C'est une ligne, elle vaut mieux qu'une
inférence — le filet « deviner l'organe depuis la docstring » a été essayé le 25/07
puis RETIRÉ : sur de la prose il rangeait `forge_adb` (pont ADB) dans l'immunitaire
parce que la phrase disait « privilégié », et une étiquette inventée se propage en
RAG et dans l'atlas, où plus rien ne la distingue d'une mesure.

**Ce qu'une déclaration doit être pour être LUE (mesuré 2026-09-06, 301 → 0 non classés).**
Le census lit la déclaration en DERNIER filet (carte > nom > dossier > imports >
déclaration), dans les **`HEAD_CHARS` = 12 000 premiers caractères** du fichier, avec
une regex **ancrée en début de ligne** (`forge_module_census.DECL_RE`). Trois formes
payées le même jour : une déclaration posée après une docstring plus longue que la
fenêtre (`nokido.py` ligne 22 — « non classé » EN la portant) ; une MENTION dans un
commentaire ou une regex (`__FORGE_COLOR__\s*=` chez un lecteur) prise pour la
déclaration ; un homonyme lu à la place du bon fichier (`app/Nokido.py` pour
`tools/nokido.py`, système de fichiers insensible à la casse, `relpath` absent).
L'écrivain est `tools/forge_organ_declare.py --from lot.json [--apply --reformuler]` :
il lit la MÊME fenêtre et la MÊME regex que le lecteur, refuse en le disant
(`REFUSE_HORS_LEXIQUE`, `HORS_TETE`, `CASSERAIT`) et ne devine jamais l'organe — la
déclaration se rédige depuis la docstring LUE, avec le mot de l'organe en tête
(`vegetatif/heartbeat : …`, `immunitaire/guard : …`), qui vaut 3 voix au vote.
Vérifier après écriture par le census lui-même, jamais par un appel direct à `organ()`.
La règle est EXÉCUTÉE : gate CI `anatomie (0 module non classé)` =
`forge_module_census.py --check` (lecture seule, nomme chaque module sans organe),
non bloquant le temps d'en mesurer le bruit — un module neuf sans déclaration ni
mot-clé y ressort dès la CI locale, pas au prochain audit.

Réciproquement, le corps nourrit le code : chaque carte de module en RAG porte
`REGULATION: <statut> (<raison>)` — REGULE (supervisé + heartbeat) · SUPERVISE (lancé
SANS heartbeat, sa mort est silencieuse) · CABLE · INVOQUE (hook/config/script) ·
OUTIL · ZONE_MORTE. Défauts par organe : `forge_organ_agents.regulation_gaps()`.
Régénération : `tools/forge_body_regulation_audit.py` (en NREM1 via le circadien).

**`ZONE_MORTE` n'autorise AUCUNE suppression** : c'est un signal à instruire, en
croisant le LOG de l'organe. Depuis le 2026-09-06 l'audit lit lui-même les tâches
planifiées et le registre nssm (`scan_systeme`, trois états avec dénominateur : 387
tâches et 33 services lus ce jour-là) et capte les noms à espace cités entre guillemets
(`"Nokido Tray.bat"` dans `install_shortcuts.ps1`). Ce qu'il ne lit toujours PAS, et
qu'il DIT : les lanceurs du profil owner (Bureau, Démarrage — lisibles en SYSTEM
seulement ; relevés à la main : `nokido_start.ps1`, `nokido_stop.ps1`,
`restart_hub.ps1`) et `~/.claude` (hooks, statusline) depuis le compte sandbox. Les 29
zones mortes du 06/09 sont INSTRUITES dans `forge_body_regulation_audit.INSTRUITS`,
datées, par MESURE (effet d'un installateur vérifié au registre : 4 services présents,
`NokidoWasmedge` et sa tâche absents ; `forge_cert_binding.py` = module mTLS écrit et
jamais importé, dette du volet identification). Statuts d'instruction : `INSTALLATEUR`
· `OUTIL` · `ASSET` · `GELE` · `NON_CABLE` · `INDETERMINE` (ce qu'on n'a PAS pu voir,
nommé — `register_autopoiesis_cp.ps1` est illisible au sandbox, pas absent).

