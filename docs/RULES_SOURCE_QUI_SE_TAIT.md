<!-- DEPORTE depuis RULES_SHARED.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de RULES_SHARED.md, re-facture a chaque tour. -->

# Ne jamais conclure d'une source qui se tait (2026-07-30)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## Ne jamais conclure d'une source qui se tait (2026-07-30)

Mesure sur 58 sessions et 268 aveux d'erreur extraits des transcripts
(`forge_symptom_index`) : la majorité de ces erreurs sont **un seul défaut**, pas une
liste. L'agent transforme « je n'ai rien vu » en « il n'y a rien ». Chaque forme
ci-dessous a été payée, et chacune a désormais un garde EXÉCUTABLE — parce que le
même corpus prouve que la note ne suffit pas : 485 mémoires existaient et l'enquête
ratée du 26/07 sur des heartbeats `never_read` a été **entièrement refaite le 29/07**,
trois hypothèses fausses et quatre redémarrages, sans que rien ne s'allume.

**1. Toute affirmation d'absence nomme ce qu'on n'a pas pu voir. Trois états, jamais
deux : vrai · faux · illisible.** Un capteur qui rend `False` pour « pas là » ET pour
« accès refusé » fabrique des faux négatifs indétectables. Mesuré le même jour :
`psutil` rend une cmdline vide pour **331 process sur 339** (autre compte) → lu comme
« ce service ne tourne pas » ; `Path.exists()` rend `False` sous le compte sandbox pour
un dossier qui EXISTE ; `deno lint` sort une chaîne vide quand deno est introuvable →
lu comme « 0 erreur » ; un répertoire de projet scanné sur deux → « mars-mai absent du
disque », faux. Corollaire : un filtre qui écarte des données le DIT (« retenues /
vues » + la liste des écartées), sinon la couverture est surestimée en silence.

**2. Avant d'ouvrir une enquête sur un symptôme, demander si on y est déjà passé.**
`forge_symptom_index --ask <symptôme>` rend les sessions antérieures ET les aveux de
chacune. Ce n'est plus à la discrétion de l'agent : `hook_recon_first` le consulte
AVANT toute action et refuse une fois, en affichant les pièges. Il indexe le SYMPTÔME,
là où les mémoires n'indexent que des CONCLUSIONS — un système qui indexe ses réponses
mais pas ses questions refait ses enquêtes.

**3. Une mesure qui ARRANGE l'agent se vérifie avant d'être rapportée.** Chercher le
biais qui l'a produite, pas la confirmation. Mesuré : un taux de « redites » affichait
une amélioration parce que son dénominateur comptait TOUS les messages owner au lieu
des seuls messages éligibles — un mois riche en « ok » / « go » faisait baisser le taux
mécaniquement. Le biais était du côté flatteur, et l'incohérence n'existait qu'à
l'agrégation. Même famille : un verdict bâti sur `created_at` de chunks `conv_*`, qui
est la date d'INGESTION et non celle des événements, déclarait « EMPIRE » sur 11 motifs
sur 12 — artefact, pas mesure. **Ne jamais accepter un chiffre parce qu'il est
défavorable non plus** : un mauvais instrument ne sert personne.

**Le principe qui les chapeaute.** Face à une récidive, la question n'est pas « quelle
règle écrire » mais **« qu'est-ce qui peut m'arrêter »**. Ce qui a effectivement tenu
le 29-30/07 : `bash_guard`, `hook_recon_first`, `forge_tool_gate`, le parse-check `.ts`
du git-gate, et le check `chemin_erreur_muet` qui a modifié la façon d'écrire les
`except` **dans la soirée même**. Avec une exigence de PRÉCISION : un garde qui crie à
faux se fait désarmer, donc un faux positif se corrige tout de suite (celui sur
`laforge_py314`, nom d'environnement pris pour un symptôme, l'a été en dix minutes).

**4. Une IMPOSSIBILITÉ s'énonce APRÈS mesure, jamais avant** (owner 2026-09-19,
après trois reprises dans la même heure). « Aucun compte ne peut », « ce mode est
hors de portée », « l'outil n'existe pas » sont des affirmations **empiriques** :
elles se prouvent par un appel, pas par souvenir. Payé le 19/09 : *« aucun compte du
hub ne peut écrire dans le superrepo »* — `LaForgeTrusted` le fait, et la mémoire du
09/09 le disait déjà ; *« la CI certifiante est hors de portée »* — `--reference
<sha>` existait ; *« le mode ne s'est pas enclenché »* — il tournait, c'est mon motif
de recherche qui ne matchait pas. **Les trois fois, la contrainte inventée a fait
sauter l'outil gouverné qui existait**, et c'est ce que l'owner a dû reprendre :
*« y en a marre de te reprendre alors que tu as la solution déjà faite »*.

Corollaire, plus large que l'impossibilité : **aucune conclusion ne se tire d'un
silence** — ni d'un `findstr` vide, ni d'une ligne absente d'un journal, ni d'un `rc`
seul. Chercher l'ARTEFACT qui prouve, jamais le motif qui manque. Exécuté par
`hook_capability_gate` (`outil_gouverne_saute`, `ci_sans_reference`).

Outils de cette section : `forge_symptom_index` (mémoire d'enquête),
`forge_process_inventory` (qui tourne, avec l'angle mort chiffré),
`forge_recurrence_audit` (motifs récidivants + taux de recadrage owner).

