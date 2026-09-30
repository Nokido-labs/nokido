# Nokido — Design System

Le système de design de **Nokido** : une *superapp souveraine, locale d'abord*, qui devient le hub personnel d'IA et de services de l'utilisateur. Nokido est un orchestrateur multi-agents *local-first* (cerveau souverain, silos de raisonnement, cascade de routage local→cloud, anneaux d'intégrité, marketplace de skills). Ce design system donne **un corps, une peau et une grammaire d'usage** à ce cerveau.

> « Une seule solution propriétaire diffusée sur des datacenters toujours plus grands ne sera jamais au niveau de 8 milliards de cerveaux humains. Encore faut-il les connecter. »

Nokido **fédère** l'intelligence locale de chacun plutôt que de tout centraliser. Le design rend cette souveraineté **visible, rassurante et désirable**.

---

## Sources

Ce système est dérivé du dépôt produit Nokido (codebase Python + web hub) :

- **GitHub** : `user/Nokido` — explorez ce dépôt pour approfondir l'implémentation réelle (orchestration, sécurité, RAG, agents).
- **Charte visuelle de référence** : `app/web_hub/static/nokido.css` (+ `nokido.js`) — palette « netcfg-agent » (inspiration Datadog / Site24x7), thème sombre violet.
- **Vues réelles du hub** : `app/web_hub/dashboard.html`, `sidebar.html`, `launcher_html.py`, `forge_feed.html`, `anatomy.html`.

Les invariants produit proviennent du **prompt maître du module design** (philosophie, architecture, persona, direction UI/UX) fourni avec la commande.

> Note : aucun fichier de police ni logo bitmap n'existe dans le dépôt. Le logo est un lockup typographique (glyphe ⚡ + wordmark). Les polices Inter / JetBrains Mono sont chargées depuis Google Fonts — voir CAVEATS.

---

## Les invariants (à ne jamais trahir)

1. **Souveraineté d'abord.** L'intention reste sur la machine sauf autorisation explicite (et après anonymisation). Le design montre toujours *où* vit le calcul.
2. **Local par défaut, cloud en dernier recours.** Cascade NPU → iGPU → Ollama/llama.cpp local → cloud. C'est un **curseur**, pas un interrupteur.
3. **Fédération, pas centralisation.** Chaque hub personnel est un nœud souverain.
4. **Superapp composable.** L'utilisateur crée sa propre app à partir de modules (sections).
5. **Persona évolutif.** Le persona s'affine ; sa « mémoire » est visible, éditable, révocable.
6. **Intention longue.** Le système capte des caps (roadmaps 100+ étapes) sans noyer l'instant.

---

## CONTENT FUNDAMENTALS — comment on écrit

- **Langue : français**, partout (UI, labels, erreurs, micro-copie). Anglais toléré uniquement pour les termes techniques consacrés (« local », « cloud », « ring », « skill », « MCP », « silo »).
- **Voix : tutoiement** de l'utilisateur (« Message à Nokido… », « Reste sur ta machine sauf autorisation »). Ton direct, technique, sobre — jamais marketing, jamais infantilisant.
- **Casing :** labels de champ et de carte en **MAJUSCULES** avec interlettrage (`letter-spacing: 0.5–0.6px`) — ex. « CONFIDENTIALITÉ », « LOCAL ». Titres de page en *Sentence case*. Boutons en *Sentence case* (« Enregistrer », « Révoquer »).
- **Méta technique en mono** : timestamps `14:32:08`, latence `612ms`, IDs `LF1.S.H.1.3.INT`, chemins `/transport/`, modèles `ollama:local`. Toujours JetBrains Mono.
- **Provenance explicite** : on nomme toujours l'origine (« LOCAL », « DISTANT », « HYBRIDE ») et, si pertinent, l'anneau (« brouillon », « vérifié », « or »).
- **Pas d'emoji décoratif** dans les composants. Exceptions héritées du dépôt : le **glyphe ⚡** (logo) et quelques pictos d'en-tête legacy (🧠, 🧬) — à éviter dans les nouveaux écrans, préférer Lucide.
- **Honnêteté** : zéro pub, zéro reco biaisée. Pour les domaines sensibles (santé, finance) : jamais de conseil affirmatif, on affiche le périmètre de confidentialité.
- **Exemples de ton** : « Local forcé — confidentialité maximale » · « Calcul sur la machine. Hors-ligne possible. » · « Signalé, anonymisé, réversible. » · « BIENTÔT » (module non déployé).

---

## VISUAL FOUNDATIONS

**Vibe générale.** Tableau de bord souverain, sombre, dense, technique mais soigné. Inspiration observabilité (Datadog/Site24x7) revisitée violet. Aucune fioriture : la couleur et le mouvement portent du **sens** (provenance, intégrité, avancée), jamais de la décoration.

**Thèmes.** Trois modes : **sombre** (`:root`, défaut), **clair** (`[data-theme="light"]`), **auto** (`[data-theme="auto"]` — suit le `prefers-color-scheme` du poste). Le hub applique l'attribut sur `<html>` ; `nokido.js` gère `theme.set/restore`. L'accent violet et toute la sémantique (provenance, anneaux, domaines) sont identiques dans les trois modes — seuls fonds, bordures, texte et ombres changent.

**Couleurs.** Thème sombre uniquement. **5 strates de fond** du plus sombre au plus clair : `--bg-0 #0C0A13` (body) → `--bg-1 #14121C` (panneaux) → `--bg-2 #1C1928` (cartes) → `--bg-3 #252233` (survol) → `--bg-4 #2E2A3D` (actif). Accent **unique : violet `#774AFF`** (souverain), avec famille sémantique : bleu `#3BB2D0`, cyan `#2DD4BF`, vert `#4AC28B`, ambre `#FFC22D`, orange `#FF9142`, rouge `#F24F4F`, rose `#EC4899`. Texte : `#EDEBF4` / `#B2AEC4` / `#6E6A82` / `#4A4759`.

**Provenance (le motif central).** Local = **vert** (`--prov-local`), chaud, ancré, halo discret. Distant = **violet** (`--prov-remote`), signalé, réversible. Hybride = **cyan**. Chaque réponse/donnée/action porte un marqueur.

**Anneaux d'intégrité (× RBAC × organes).** Brouillon = cercle **pointillé gris**. Vérifié = **cyan plein** lumineux. Or = **jaune** avec lueur. L'anneau d'une donnée **détermine sa zone RBAC** (`ZONE_BY_RING`) : or → `system`, vérifié → `trusted`, brouillon → `sandbox-online`, non vérifié → `sandbox-offline`. Chaque **organe** du système (cerveau, mémoire/RAG, routeur, skills, outils externes) vit avec une **santé** (active = vert pulsé rapide, alive = cyan pulsé lent, idle = gris, dead = rouge) et porte son anneau + sa zone. Voir la carte « Anneaux d'intégrité × RBAC × organes ».

**Identité par domaine.** Chaque section a sa teinte d'accent (transport=bleu, santé=vert, finance=ambre, loisir=rose, achat=orange, création=violet, jeux=cyan, dev=gris froid, domotique=vert) mais hérite de la même structure de carte. Cohérence globale, reconnaissance immédiate. L'accent apparaît en **filet vertical de 3px** à gauche de la carte + tuile d'icône teintée (16 % d'opacité).

**Typo.** **Inter** (UI/corps, base 13.5px / 1.5) + **JetBrains Mono** (code, méta, statuts, provenance, IDs). Échelle compacte de dashboard. Titres 700, labels 600 majuscules.

**Espacement & rayons.** Base 4px. Rayons : `6px` (boutons/inputs/puces), `10px` (cartes/panneaux), `14px` (grandes surfaces), `999px` (pastilles). Padding de carte ~16px.

**Backgrounds.** Aplats sombres, **pas de gradient décoratif** sur les fonds (sauf jauges fonctionnelles : la barre de souveraineté est un dégradé vert). Pas d'image full-bleed, pas de texture, pas d'illustration. La profondeur vient des strates de fond + bordures.

**Bordures.** `--border #332F44` (standard, sur bg-2+), `--border-subtle #262338` (séparateurs/panneaux). 1px partout.

**Ombres.** `--shadow-md` (cartes), `--shadow-lg` (modales). Le halo signature : `--shadow-glow` (lueur violette `0 0 24px rgba(119,74,255,0.15)`) au survol des cartes interactives.

**Cartes.** Fond `bg-2`, bordure `--border` 1px, rayon 10px, ombre md. Au survol (interactives) : fond → `bg-3` + halo violet. Modules : + filet d'accent vertical 3px + tuile d'icône teintée.

**Animation.** Sobre et porteuse de sens. `--motion-fast 120ms` (hover/teintes), `--motion-base 150ms` (cartes), `--motion-slow 220ms` (toasts/panneaux). Courbe `--ease-out cubic-bezier(0.16,1,0.3,1)`. Motifs : **pulse** (indicateurs vivants, 2s), **toast-in** (glissé droite), **fade-in** (événements de feed), **promote** (anneau qui passe à l'or). `prefers-reduced-motion` respecté.

**Hover / press.** Boutons pleins → assombrissement (violet → `--purple-dim`). Boutons ghost → texte+bordure virent au violet. Cartes → strate de fond plus claire + halo. Liens → violet vers cyan.

**Focus (accessibilité).** Anneau `--focus-ring` (`0 0 0 3px rgba(119,74,255,0.35)`) au `:focus-visible`. Contraste WCAG AA, cibles tactiles ≥ 44px (taille `lg` des boutons).

**Transparence & blur.** Teintes douces (16 % d'opacité) pour les fonds de badge et tuiles d'icône. Pas de glassmorphism / backdrop-blur dans le dépôt — éviter.

**Layout.** Sidebar fixe 220px à gauche, topbar fixe 52px, contenu max 1280px centré. Grille de modules : `repeat(auto-fit, minmax(248px, 1fr))` (valeur du code, `_ds_bundle.js` et `hub-views.ref.jsx`). Responsive : la sidebar se replie < 768px.

---

## ICONOGRAPHY

- **Système : Lucide** (`https://unpkg.com/lucide@latest`), chargé via CDN dans les vues du hub (`dashboard.html`). Trait régulier ~2px, style ligne. Usage : `<i data-lucide="route"></i>` puis `lucide.createIcons()`.
- **État allumé/éteint** : une tuile d'icône est **éteinte au repos** (fond `bg-2`, icône `text-dim`) et **s'allume quand elle est active** : fond en teinte pleine du domaine + halo (`box-shadow` color-mix 55 %). Voir la carte « Iconographie ».
- **Tuiles d'icône** : carré 44px (ou 40px en module), rayon `--radius-sm`, fond teinté à 16 % de l'accent, icône 22px dans la couleur d'accent pleine. Classes legacy : `.lf-icon-purple/blue/cyan/green/yellow/orange/red/pink`.
- **Pictos suggérés par domaine** : transport=`route`, santé=`heart-pulse`, finance=`wallet`, loisir=`compass`, achat=`shopping-cart`, création=`sparkles`, jeux=`gamepad-2`, dev=`terminal`, domotique=`house`, cerveau/persona=`brain`/`cpu`, souveraineté=`shield-check`, curseur=`sliders-horizontal`, kill switch=`octagon-alert`.
- **Emoji** : éviter. **Le logo raconte la forge** — un **marteau** en acier frappe une **enclume** stylisée et fait **jaillir l'éclair de calcul** en dégradé **violet → cyan** (`#CDB4FF → #774AFF → #2DD4BF`), avec lueur. C'est la métaphore du produit : l'humain (marteau) + l'outil (enclume) forgent l'intelligence (éclair). Fichier : `assets/laforge-mark.svg` (acier en dégradé `#E7E4F0 → #8A8599`). Décliné en marque seule, lockup + wordmark dégradé, et pastille. L'ancien glyphe ⚡ reste un raccourci toléré en très petit. Quelques en-têtes legacy utilisent 🧠/🧬 — ne pas reproduire.
- **Aucun PNG d'icône** n'est stocké : tout passe par Lucide CDN.

---

## INDEX / MANIFESTE

**Racine**
- `styles.css` — point d'entrée CSS (uniquement des `@import`).
- `cover.html` — page de garde du design system (manifeste + index des écrans).
- `favicon.svg` — favicon dérivée de la marque.
- `readme.md` — ce document.
- `SKILL.md` — mode d'emploi Agent Skill.

**`tokens/`** — `fonts.css`, `colors.css`, `themes.css` (clair + auto/poste), `typography.css`, `spacing.css`, `effects.css`, `base.css`.

**`guidelines/`** — cartes-spécimens (Design System tab) : couleurs (fonds, accents, provenance, anneaux, domaines, texte), typo (échelle, mono), espacement (échelle, rayons/ombres), brand (logo, icônes).

**`components/`** — primitives React (namespace `window.NokidoDesignSystem_bdc2ac`) :
- `core/` — **Button**, **Card**
- `forms/` — **TextInput**, **Select**
- `feedback/` — **Badge**, **StatusPill**
- `sovereignty/` — **ProvenanceBadge**, **SovereigntyGauge**, **PowerSlider**
- `modules/` — **ModuleCard**
- `intent/` — **CapStep**
- `rings/` — **RingMeter** (modèle d'intégrité à 11 anneaux, Ring 0→10)

**`ui_kits/`** — recréations d'écrans complets :
- `login/` — verrouillage au démarrage (coffre souverain) + choix de langue FR/EN/ES/DE.
- `hub/` — le hub Nokido (PC), **unifié** : Accueil (modules), Intention longue, **Fédération** (exposer son hub d'IA + garde-fous), Maison (domotique), Mémoire persona, Souveraineté (curseur + **bascule local↔distant en direct** + journal). Liens vers Composer et verrouillage. Bouton **thème** (sombre/clair/auto) persistant. `mobile.html` : le même hub en **glance mobile** (onglets bas).
- `onboarding/` — onboarding souverain (mobile, iPhone) : niveau local/cloud → puissance allouée → activation des sections → récap.
- `composer/` — composer son app (PC) : catalogue → ta vue, épingler/masquer/réordonner.
- `webhub/` — **le vrai portail web `:7400` modernisé** au DS, **centralisé** : Portail de services, **Setup souverain** (scan machine · compromis · profils de conf · DB vectorielle multi-tiers AMI 4096d / FAISS 1024d / FTS rerank · modes de lancement), **Rings** (placement des agents sur les 11 anneaux), Chat (ask), **Launcher**, **Anatomie Live** (OPSEC, kill switch), **Network Graph**, **MCP Lab**, **RAG Dashboard**, Event Feed, Status JSON, CTF Reports, Pipeline souverain, Swarm, LLM Debate. Panneau **Tweaks**. Recréation fidèle de `dashboard.html` / `sidebar.html` / `launcher_html.py` / `anatomy.html` / `rag_dashboard.html` / `forge_feed.html` + vocabulaire de `forge_desktop` (11 rings, tiers RAG).

**`assets/`** — `laforge-mark.svg` (marque : marteau + enclume + éclair), `laforge-prefs.js` (préférences persistantes partagées : `power`, `theme`, `lang` via localStorage).

---

## CAVEATS

- **Polices** : aucun binaire fourni → Inter + JetBrains Mono chargées depuis Google Fonts (`tokens/fonts.css`). Pour un usage 100 % hors-ligne/souverain, remplacer par des fichiers locaux. *Merci de fournir les .woff2 officiels si vous en avez.*
- **Logo** : marque illustrée (enclume + marteau + éclair) dessinée à partir du brief — `assets/laforge-mark.svg`. À valider / remplacer si un logo officiel existe.
- **Provenance/anneaux/curseur** : interprétés depuis le prompt maître + concepts du codebase (OPSEC, kill switch, anneaux d'intégrité). À valider avec l'équipe produit.
