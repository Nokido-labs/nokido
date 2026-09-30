"""Non-regression : le parseur d'intentions LIT la demande de l'owner.

DEFAUT MESURE le 2026-09-12 par execution reelle (`sandbox/mesure_am1_multi_intention.py`,
job `job_cb2dce8821fd`), pas par relecture. Sur trois instructions de la forme que
l'owner emploie vraiment, **deux sur trois capturent ZERO verbe** : `parse_intent`
rend alors `action="executer"` et `target="projet"`, ses deux valeurs par DEFAUT.
L'orchestrateur autonome (`forge_autonomous_orchestrator:401`) construit son DAG
depuis cet objet : un intent vide produit un plan generique sans que rien ne signale
que la demande n'a pas ete comprise. C'est un `UNKNOWN` rendu comme une valeur.

Quatre defauts INDEPENDANTS, chacun mesure, chacun un test ici :

  D1  ACCENTS DETRUITS. La normalisation est `re.sub("[^a-z0-9 -]", " ", texte)` :
      tout caractere accentue devient une ESPACE, donc « verifie » s'ecrit
      « v rifie » et coupe le mot en deux. Aucun verbe accentue n'est joignable.

  D2  LEXIQUE A L'INFINITIF, OWNER A L'IMPERATIF. `ACTION_VERBS` liste `corriger`,
      `pousser`, `analyser` ; l'owner ecrit « corrige », « pousse », « analyse ».
      Le test etant `v in norm` (sous-chaine), un infinitif n'est JAMAIS contenu
      dans sa propre forme conjuguee. Ce qui passe ne passe que par accident,
      quand la forme ANGLAISE est un prefixe du mot francais : `refactor` est
      bien dans « refactorise », `test` dans « teste » — mais `corriger` n'est
      pas dans « corrige ». Le lexique marche donc pour des raisons etrangeres
      a la langue qu'il pretend couvrir.

  D3  ORDRE DU LEXIQUE, PAS DE LA PHRASE. `verbs = [v for v in ACTION_VERBS if
      v in norm]` itere sur la LISTE : `action = verbs[0]` rend le verbe le plus
      haut dans le lexique, pas le premier de la demande. Mesure : « analyse le
      rag, refactorise le cache et teste » rend `action="test"`, parce que `test`
      precede `refactor` dans la liste. L'intention principale de l'owner n'est
      pas celle qui est retenue.

  D4  SOUS-CHAINE = FAUX POSITIFS. Chercher `run` par sous-chaine le trouve dans
      « brunch » ; `index` dans « indexation » est voulu, `run` dans « brun » ne
      l'est pas. Un verbe se reconnait sur un MOT, pas sur une suite de lettres.

Et le cinquieme point, qui est la demande initiale : une instruction owner porte
souvent PLUSIEURS intentions (« mesure X puis corrige Y et pousse »). Le champ
`verbs` les collecte deja, mais la mesure du 12/09 montre qu'il n'est lu par
PERSONNE hors du parseur (`action` l'est par deux modules) : un champ conserve et
jamais consomme est perdu tout autant. On expose donc les intentions ORDONNEES
par leur position dans la phrase, et `action` devient la premiere d'entre elles.

⚠️ Ce fichier n'importe PAS `ACTION_VERBS` pour batir ses attentes : un instrument
qui lit le vocabulaire de sa cible valide la cible par elle-meme. Les verbes cites
ici sont ceux d'instructions owner reelles, ecrits a la main.

Ecrit ROUGE avant la correction de `app/forge_intent_parser.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + ast (l.268)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


def _parse(texte: str):
    from forge_intent_parser import parse_intent  # type: ignore

    return parse_intent(texte)


# --------------------------------------------------------------------- D1
def test_un_verbe_accentue_n_est_pas_coupe_en_deux_par_la_normalisation():
    """D1. « verifie » porte un accent aigu ; la normalisation le remplace par une
    espace et fabrique « v rifie », ou plus aucun verbe n'est joignable. Le mot
    est ecrit ici avec son accent parce que c'est ainsi que l'owner l'ecrit."""
    pi = _parse("vérifie le lien du routeur")
    assert pi.verbs, (
        "aucun verbe capture dans « vérifie le lien du routeur » : l'accent a "
        "ete remplace par une espace, le mot est coupe en deux"
    )
    assert any("verif" in v for v in pi.verbs), (
        f"le verbe verifier n'est pas reconnu sous sa forme accentuee : {pi.verbs}"
    )


# --------------------------------------------------------------------- D2
@pytest.mark.parametrize(
    "instruction, racine_attendue",
    [
        ("corrige le routeur", "corrig"),
        ("pousse la branche alpha", "pouss"),
        ("analyse le rag", "analys"),
        ("commite le correctif", "commit"),
        ("optimise la cascade", "optimis"),
    ],
)
def test_un_verbe_a_l_imperatif_est_reconnu(instruction, racine_attendue):
    """D2. Le lexique liste des infinitifs, l'owner ecrit a l'imperatif. Un
    infinitif n'est jamais contenu dans sa forme conjuguee : la recherche par
    sous-chaine echoue silencieusement et l'intent sort vide."""
    pi = _parse(instruction)
    assert pi.verbs, f"aucun verbe capture dans « {instruction} »"
    assert any(v.startswith(racine_attendue) for v in pi.verbs), (
        f"« {instruction} » : attendu un verbe de racine « {racine_attendue} », "
        f"obtenu {pi.verbs}"
    )


def test_l_action_n_est_pas_la_valeur_par_defaut_quand_un_verbe_est_present():
    """D2, consequence. `action` retombe sur « executer » — sa valeur par defaut —
    des que le lexique ne reconnait rien. L'appelant ne peut pas distinguer
    « l'owner a demande d'executer » de « je n'ai rien compris »."""
    pi = _parse("corrige le routeur puis pousse")
    assert pi.action != "executer", (
        "action == « executer » : c'est la valeur par DEFAUT du parseur, rendue "
        "ici alors que deux verbes explicites sont presents. UNKNOWN rendu comme "
        "une valeur."
    )


# --------------------------------------------------------------------- D3
def test_l_action_retenue_suit_l_ordre_de_la_PHRASE_et_non_du_lexique():
    """D3. Mesure du 12/09 : « analyse le rag, refactorise le cache et teste »
    rend `action="test"`, parce que `test` precede `refactor` dans ACTION_VERBS.
    L'action doit etre la PREMIERE intention de la demande."""
    pi = _parse("refactorise le cache et teste")
    assert pi.action and pi.action.startswith("refactor"), (
        f"action = {pi.action!r} : le verbe retenu est celui qui vient en tete du "
        "LEXIQUE, pas celui qui ouvre la phrase"
    )


def test_les_verbes_sont_rendus_dans_l_ordre_d_apparition():
    pi = _parse("analyse le rag, refactorise le cache et teste")
    assert len(pi.verbs) >= 3, f"trois intentions attendues, obtenu {pi.verbs}"
    positions = []
    for v in pi.verbs:
        r = v[:5]
        positions.append("analyse le rag, refactorise le cache et teste".find(r))
    assert positions == sorted(positions), (
        f"verbes rendus dans le desordre : {pi.verbs} -> positions {positions}"
    )


# --------------------------------------------------------------------- D4
def test_un_verbe_ne_matche_pas_au_milieu_d_un_autre_mot():
    """D4, contre-epreuve. `run` est dans le lexique et « brunch » le contient.
    Un verbe se reconnait sur un MOT."""
    pi = _parse("le brunch est prevu demain")
    assert not any(v == "run" for v in pi.verbs), (
        f"« run » capture dans « brunch » : reconnaissance par sous-chaine, {pi.verbs}"
    )


# ------------------------------------------------------- multi-intention
def test_les_intentions_multiples_sont_exposees_et_ordonnees():
    """La demande initiale. Une instruction owner porte souvent plusieurs
    intentions ; elles doivent etre lisibles par l'appelant, ordonnees, sans
    qu'il ait a redecouper la phrase lui-meme."""
    pi = _parse("mesure les chunks puis corrige le routeur et pousse")
    intentions = getattr(pi, "intentions", None)
    assert intentions is not None, (
        "ParsedIntent n'expose aucun champ `intentions` : le multi-intention "
        "reste implicite dans `verbs`, que la mesure du 12/09 montre lu par "
        "personne hors du parseur"
    )
    assert len(intentions) >= 2, (
        f"deux intentions au moins attendues (corriger, pousser), obtenu {intentions}"
    )
    assert intentions[0] == pi.action, (
        f"la premiere intention {intentions[0]!r} doit etre l'action retenue "
        f"{pi.action!r} — sinon deux champs disent deux choses differentes"
    )


def test_les_intentions_sont_dans_to_dict_sinon_l_appelant_ne_les_voit_pas():
    """`forge_autonomous_orchestrator:407` fait `result["intent"] = intent.to_dict()`.
    Un champ absent de `to_dict` n'existe pas pour l'appelant."""
    pi = _parse("analyse le rag puis commite")
    d = pi.to_dict()
    assert "intentions" in d, (
        f"`intentions` absent de to_dict() : clefs = {sorted(d)}"
    )
    assert d["intentions"] == getattr(pi, "intentions", None)


def test_aucun_decorateur_n_est_applique_deux_fois():
    """DEFAUT PREEXISTANT revele le 2026-09-12 : `@dataclass` etait empile SIX fois
    sur `ParsedIntent`. L'empilement etait INVISIBLE tant que le dernier champ
    portait un defaut SIMPLE — `dataclass` conserve `confidence = 0.0` comme
    attribut de classe, donc le 2e passage le revoit. Un champ a `default_factory`
    est au contraire RETIRE des attributs de classe au 1er passage : au 2e il
    parait sans defaut et l'import du module entier tombe en TypeError.

    Le defaut dormait depuis l'ecriture du fichier ; c'est l'ajout de `intentions`
    qui l'a reveille. Un decorateur duplique ne se voit pas a la relecture et
    n'echoue qu'a la prochaine modification : il se garde, il ne se surveille pas.
    """
    import ast

    source = RACINE / "app" / "forge_intent_parser.py"
    arbre = ast.parse(source.read_text(encoding="utf-8", errors="replace"))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        noms = [ast.unparse(d) for d in noeud.decorator_list]
        doublons = sorted({n for n in noms if noms.count(n) > 1})
        assert not doublons, (
            f"{noeud.name} porte {len(noms)} decorateurs dont des doublons "
            f"{doublons} — un decorateur applique deux fois retraite la classe "
            "et fait disparaitre les defauts a default_factory"
        )


def test_aucun_chemin_d_erreur_muet_dans_le_parseur():
    """`_enrich_llm` avalait toute exception par un `pass` nu (L348, signale 74x
    depuis mai par le gate recidive, et remonte sur le commit de ce chantier).

    Consequence : un appelant qui passe `use_llm=True` recoit le resultat REGEX
    en croyant tenir un intent enrichi. L'echec de l'enrichissement devient
    indiscernable d'un enrichissement qui n'avait rien a ajouter — trois etats
    confondus en un, dans la fonction meme qui sert a lever un doute.

    Un `except` peut rester silencieux s'il est MARQUE `# muet-ok` : on interdit
    le silence non declare, pas le silence delibere.
    """
    import ast

    source = RACINE / "app" / "forge_intent_parser.py"
    lignes = source.read_text(encoding="utf-8", errors="replace").splitlines()
    arbre = ast.parse("\n".join(lignes))
    muets = []
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.ExceptHandler):
            continue
        agit = any(
            not isinstance(s, ast.Pass)
            and not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
            for s in noeud.body
        )
        if agit:
            continue
        fenetre = "\n".join(lignes[max(0, noeud.lineno - 3): noeud.lineno + 3])
        if "muet-ok" in fenetre:
            continue
        muets.append(noeud.lineno)
    assert not muets, (
        f"chemin(s) d'erreur MUET(s) ligne(s) {muets} de {source.name} : "
        "journaliser, ou marquer `# muet-ok` si le silence est voulu"
    )


def test_aucun_decorateur_duplique_dans_tout_le_depot():
    """PORTEE. Un defaut trouve a DEUX sites n'est pas un cas particulier.

    Balayage du 2026-09-12 : 2438 fichiers de `app/` et `tools/` lus, **0
    illisible**, deux sites porteurs — `ParsedIntent` (6 decorateurs) et
    `forge_triad_authority.TriadStep` (2). Les deux desamorces le meme jour.
    Le dormant ne se reveille qu'a la prochaine modification du fichier, donc
    il ne se surveille pas a l'oeil : il se garde.

    Le DENOMINATEUR est affirme, pas seulement le resultat : un scan qui n'a pas
    pu lire se lit comme rassurant.
    """
    import ast

    vus, illisibles, touches = 0, [], []
    for dossier in ("app", "tools"):
        for p in (RACINE / dossier).rglob("*.py"):
            if {"_attic", "backups", "legacy"} & set(p.parts):
                continue
            vus += 1
            try:
                arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                illisibles.append(f"{p.name}: {type(e).__name__}")
                continue
            for noeud in ast.walk(arbre):
                if not isinstance(
                    noeud, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                noms = [ast.unparse(d) for d in noeud.decorator_list]
                dbl = sorted({n for n in noms if noms.count(n) > 1})
                if dbl:
                    touches.append(f"{p.name}::{noeud.name} {dbl} (x{len(noms)})")

    assert vus > 1000, f"balayage anormalement court ({vus} fichiers) — instrument suspect"
    assert not illisibles, f"fichiers ILLISIBLES, couverture non prouvee : {illisibles[:5]}"
    assert not touches, (
        f"decorateur(s) duplique(s) sur {vus} fichiers lus : {touches}. "
        "Invisible a la relecture, sans effet jusqu'a l'ajout d'un champ a "
        "default_factory, puis ImportError sur le module entier."
    )


# ------------------------------------------------ contre-epreuve du detecteur
def test_une_phrase_sans_aucun_verbe_ne_fabrique_pas_d_intention():
    """Symetrie : ne pas remplacer une sur-deduction par une autre. Une phrase
    sans verbe d'action doit rendre une liste VIDE, pas un verbe invente."""
    pi = _parse("le ciel est bleu ce matin")
    assert pi.verbs == [], f"verbes fabriques sur une phrase sans action : {pi.verbs}"
    assert getattr(pi, "intentions", []) == []
