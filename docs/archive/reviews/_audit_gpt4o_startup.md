### Analyse technique et arbitrage

#### A. Nature de `0x90`
Le caractère `0x90` peut être interprété de deux manières :
- **Gemini** : `0x90` est un caractère étendu de l'encodage CP1252 (``), ce qui est cohérent si le bridge traite du texte mal encodé.
- **Kimi** : `0x90` pourrait être un marqueur binaire, comme une partie d'un PE header ou un dump mémoire corrompu, ce qui indiquerait un problème plus grave.

Pour trancher : inspectez les données brutes transitant dans le pipe entre `mcp_stdio_bridge.py` et le hub. Si `0x90` apparaît dans un contexte textuel (e.g., JSON), Gemini a raison. Si c'est hors contexte (e.g., séquences binaires), Kimi a raison. **Hypothèse probable : Kimi est correct**, car un caractère isolé en dehors d'un flux textuel JSON est suspect.

#### B. `errors='replace'`
Passer `errors='replace'` dans le bridge masque les erreurs Unicode en remplaçant les caractères problématiques. Cela peut stabiliser temporairement le système, mais cela **cache un bug sous-jacent**. Si le problème est binaire (Kimi), ce fix est inadéquat et pourrait aggraver la situation en ignorant des données corrompues. **Priorité : investiguer et corriger la source des données invalides.**

#### C. Crash loop NSSM
Le délai de redémarrage de 2 secondes (`AppRestartDelay`) dans NSSM peut effectivement amplifier une boucle de crash si le bridge échoue systématiquement sur des inputs invalides. Chaque redémarrage consomme des ressources système (CPU, I/O) et peut saturer le hub. **Kimi a raison ici** : le comportement de NSSM doit être ajusté ou remplacé par un gestionnaire de processus plus intelligent.

### Conclusion et priorités
**Kimi a l'approche correcte dans ce contexte.** Les symptômes indiquent un problème binaire plus grave que de simples erreurs Unicode. Voici les priorités :
1. **Investiguer la source de `0x90`** : analyser les données brutes pour confirmer si elles sont binaires ou textuelles.
2. **Réparer la gestion des pipes** : restaurer `os.execv` et implémenter un circuit breaker pour éviter la propagation d'erreurs.
3. **Remplacer NSSM** : adopter un gestionnaire de processus asynchrone ou avec une logique de santé (`/healthz`).

Gemini propose une solution rapide mais insuffisante. Kimi a une vision plus robuste et systémique. **GO pour Kimi.**