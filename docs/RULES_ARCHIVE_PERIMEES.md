# Regles PERIMEES — archive datee

Blocs sortis de `RULES_SHARED.md` le 2026-09-12 parce que leur SYNTAXE est morte
et remplacee par une regle qui figure deja plus haut dans ce fichier. Ils ne sont
pas supprimes : la mesure qu'ils portent reste vraie et reste consultable.

⚠️ Ce qui n'a PAS ete sorti, et pourquoi — la verification a montre que « marque
perime » ne veut pas dire « sortable » :

- le bloc qui porte « le compte regle les ACL, pas les guards de l'action » : il
  declare lui-meme ce corollaire encore valide ;
- le bloc `OUTIL PERIME` sur `forge_anon_push` : c'est une PROHIBITION, et
  l'outil existe toujours. Une regle « ne fais pas X » ne part jamais en
  chargement paresseux ;
- le bloc `A RE-VERIFIER` : une hypothese ouverte, pas une regle morte.



## sandbox=online / trusted comme selecteur de compte

_Sorti de `RULES_SHARED.md` ligne 477, 1273 octets._

| **[SYNTAXE PÉRIMÉE 2026-09-01 — la règle du dessus la remplace ; la MESURE reste vraie, mais elle a été faite via un chemin qui rendait SYSTEM, donc sa conclusion « sous tel compte » est à re-vérifier sous `network=true`]** LE COMPTE D'EXÉCUTION EST UN PARAMÈTRE, PAS UNE FATALITÉ. Trois comptes existent — `LaForgeSbxOffline` (défaut), `LaForgeSbxOnline`, `LaForgeTrusted` — et `run` les sélectionne par `sandbox=`. Rester sur le défaut devant un outil qui a besoin du réseau, du loopback ou d'un sous-processus dialoguant en local, c'est s'infliger un échec évitable — et le plus souvent un échec MUET | **[NE PLUS APPLIQUER — `sandbox="online"` est REFUSÉ depuis `7ebea14b0` ; forme actuelle : `network=true`]** ~~`run action=shell sandbox="online"` (ou `"trusted"`)~~. **Mesure 2026-08-26** : Playwright expire en **180 s sans erreur franche** sous le défaut — il pilote le navigateur par le **loopback**, que ce compte bloque — et se lance en **1,3 s** sous `sandbox="online"`. Le timeout muet avait envoyé chercher la cause dans le profil persistant, le chemin des navigateurs puis le mode headed : **trois fausses pistes avant d'essayer simplement l'autre compte**. Réflexe : devant un timeout sans message, changer de compte AVANT de soupçonner la configuration |


## `code=` lu comme du PowerShell sous trusted/online

_Sorti de `RULES_SHARED.md` ligne 504, 758 octets._

| **[SYNTAXE PÉRIMÉE 2026-09-01 — et la conclusion tombe : ce « PowerShell » était la branche par défaut `pwsh` in-process, donc SYSTEM. Par `network=true`, l'exécution passe par `spawn_as_sandbox` en `cmd.exe /c` — la syntaxe redevient celle du défaut]** `code=` sous `sandbox="trusted"` / `"online"` est du POWERSHELL, pas cmd.exe. Mesuré 2026-08-28 : `git ... & echo ... & findstr ...` n'enchaîne rien — PowerShell lit `&` comme l'opérateur de **job en arrière-plan** et rend une table `Id/Name/State/Running` au lieu des sorties. Le premier segment paraît « ne rien renvoyer » | `commands=[...]` (chaque commande séparée, sortie par commande), ou `;` / `-and` dans un `code=` unique. Le défaut `offline` reste cmd.exe : la syntaxe change AVEC le compte |
