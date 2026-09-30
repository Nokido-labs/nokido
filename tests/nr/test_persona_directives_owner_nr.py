"""NR -- « Mémoire du persona » montre les directives de l'OWNER, pas les leçons de l'agent.

DEFAUT SIGNALE PAR L'OWNER le 2026-09-18 : « mémoire persona est censé être
"Ce que Nokido a compris de toi", c'est pas vraiment le cas ».

MESURE. La route rendait des entrées comme `{"t": "** Fix errors before commit"}` :
des `SOLUTION:` extraites par expression régulière de `lessons_learned`,
c'est-à-dire ce que l'AGENT a compris de ses propres erreurs de développement.
La vue, elle, promet ce que Nokido a compris de l'OWNER. Deux choses
différentes, et le texte commençant par `**` trahissait en plus un découpage
abîmé.

LA CHAINE, et pourquoi elle a cette forme. Les directives durables sont
extraites des transcripts par `forge_directive_audit`. Le portail ne peut PAS
les lire lui-même : son compte n'a pas accès au profil de l'owner
(`PermissionError WinError 5`, mesuré le même jour). Le hook de session, qui
tourne du bon côté et fait déjà ce calcul, dépose donc son résultat dans
`sandbox/persona_directives.json`, que le portail sait lire.

CE QUE CE NR FIGE, aux DEUX bouts :
  * le producteur écrit bien l'artefact depuis son mode hook ;
  * le consommateur lit cet artefact et NE retombe PAS sur les leçons техniques
    quand il manque. Reservir `lessons_learned` « faute de mieux » reconduirait
    exactement la confusion qu'on vient de lever : une source absente n'est pas
    une source de remplacement.
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
APP = RACINE / "app" / "web_hub" / "app.py"
AUDIT = RACINE / "tools" / "forge_directive_audit.py"
ARTEFACT = "persona_directives.json"


def _corps(fichier: Path, nom: str) -> str:
    """Corps EXECUTABLE d'une fonction : ni commentaires, ni docstring.

    Deux pièges, et j'ai payé les deux le même jour. D'abord le commentaire qui
    CITE le code retiré pour expliquer pourquoi il l'a été. Puis — une fois les
    commentaires écartés — la DOCSTRING, qui fait exactement la même chose et
    que mon premier dépouillage laissait passer : ce NR s'est accusé lui-même à
    cause de la prose qui le justifie.

    Une MENTION n'est pas une STRUCTURE. On ne garde donc que ce qui s'exécute.
    """
    lignes = fichier.read_text(encoding="utf-8", errors="replace").splitlines()
    for n in ast.walk(ast.parse("\n".join(lignes))):
        if not (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom):
            continue
        corps = list(n.body)
        # Retire la docstring : c'est de la documentation, pas du comportement.
        if (corps and isinstance(corps[0], ast.Expr)
                and isinstance(getattr(corps[0], "value", None), ast.Constant)
                and isinstance(corps[0].value.value, str)):
            corps = corps[1:]
        if not corps:
            return ""
        debut = corps[0].lineno - 1
        fin = max((c.end_lineno or c.lineno) for c in corps)
        brut = lignes[debut:fin]
        return "\n".join(l for l in brut if not l.lstrip().startswith("#"))
    return ""


def test_le_depouillage_mord_sur_les_DEUX_formes(tmp_path):
    """Commentaire ET docstring : les deux portent de la prose qui cite le code.

    Ce test fabrique une fonction témoin dont la docstring et le commentaire
    nomment le motif interdit, alors que son code ne le contient pas. Le
    dépouillage doit la déclarer propre — sinon le garde accuse la
    documentation, ce qui décourage précisément d'en écrire.
    """
    # Le témoin s'écrit dans le répertoire temporaire du test : un NR n'écrit
    # pas dans le dépôt pour se prouver (et le compte qui l'exécute n'en a pas
    # le droit -- PermissionError mesurée).
    temoin = tmp_path / "temoin_depouillage.py"
    temoin.write_text(
        'def f():\n    """read_lessons est retiré ici."""\n'
        "    # lessons_learned aussi\n    return 1\n", encoding="utf-8")
    net = _corps(temoin, "f")
    assert "return 1" in net, "le dépouillage a mangé le code : %r" % net
    assert "read_lessons" not in net, "docstring non retirée : %r" % net
    assert "lessons_learned" not in net, "commentaire non retiré : %r" % net


def test_le_producteur_depose_l_artefact():
    corps = _corps(AUDIT, "main")
    assert corps, "`main` introuvable dans forge_directive_audit : ILLISIBLE"
    assert ARTEFACT in corps, (
        "le hook ne dépose pas %s : le portail n'aura jamais les directives, "
        "puisqu'il ne peut pas lire les transcripts lui-même" % ARTEFACT)


def test_le_consommateur_lit_l_artefact():
    corps = _corps(APP, "api_hub_persona")
    assert corps, "`api_hub_persona` introuvable dans app.py : ILLISIBLE"
    assert ARTEFACT in corps, (
        "/api/hub/persona ne lit pas %s : la vue ne peut pas montrer les "
        "directives de l'owner" % ARTEFACT)


def test_le_consommateur_ne_RETOMBE_PAS_sur_les_lecons_techniques():
    """Le cœur du défaut signalé : servir autre chose sous la même promesse."""
    corps = _corps(APP, "api_hub_persona")
    for interdit in ("read_lessons", "lessons_learned"):
        assert interdit not in corps, (
            "/api/hub/persona utilise encore `%s` : ce sont les leçons de "
            "DEVELOPPEMENT de l'agent, pas ce que Nokido a compris de l'owner. "
            "Une source absente n'est pas une source de remplacement." % interdit)


def test_une_correction_de_frappe_ne_compte_pas_pour_DEUX_directives():
    """Mesure du premier export reel : deux entrees du 15/09 etaient le MEME
    message reedite. Affichees cote a cote, elles donnent l'impression d'un
    systeme qui radote.

    Ce test fige surtout POURQUOI la premiere tentative a echoue : comparer les
    quarante premiers caracteres ne captait rien, la correction etant INSEREE AU
    MILIEU. Le cas ci-dessous est celui, reel, qui l'a montre.
    """
    import importlib.util as _iu

    spec = _iu.spec_from_file_location("_fda_nr", AUDIT)
    mod = _iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Les textes sont ceux du corpus REEL, non raccourcis. Piege paye en
    # ecrivant ce test : abreges, ils tombent a 0,800 de similarite et le NR
    # echouait sur un cas que la fonction traite correctement en production. Un
    # temoin qui n'a pas la forme du reel mesure autre chose que le reel.
    brutes = [
        {"texte": "1 et 3 quels les 4 missions ? et y a plus de skills que ca ? "
                  "je veux que tu les liste avant decision",
         "date": "2026-09-15", "couverte_par": ["x"]},
        {"texte": "1 et 3 quels les 4- artefact dez missions ? et y a plus de skills "
                  "que ca ? je veux que tu les liste avant decision",
         "date": "2026-09-15", "couverte_par": ["x"]},
        {"texte": "coupe docker des que la tache est finie", "date": "2026-09-14",
         "couverte_par": []},
    ]
    out = mod._sans_redites(brutes)
    assert len(out) == 2, (
        "la redite n'est pas ecartee (%d sorties pour 3 entrees) : une "
        "correction de frappe compte encore pour deux directives" % len(out))
    textes = [d["texte"] for d in out]
    assert any("artefact dez" in t for t in textes), (
        "c'est la version la plus COURTE qui a ete gardee : une correction "
        "allonge presque toujours la phrase, la plus complete est la plus fidele")
    assert any("docker" in t for t in textes), (
        "une directive DISTINCTE a ete avalee par la deduplication")


def test_la_prose_de_l_AGENT_n_est_pas_servie_comme_parole_d_owner():
    """« Ce que Nokido a compris de toi » ne doit pas contenir du Nokido.

    Mesure du premier export : huit entrées sur soixante commençaient par « ⚠️ »,
    « **Go.** » ou une puce de rapport — ma propre écriture, présentée comme une
    directive de l'owner. Cause structurelle : quand le contexte est compacté, un
    message de type « user » est injecté AVEC le résumé rédigé par l'assistant.

    Le filtre de forme est une heuristique et se trompera parfois. Le coût des
    deux erreurs n'est pas symétrique : laisser passer la prose de l'agent
    corrompt la mémoire du persona à la racine, tandis qu'écarter une directive
    la laisse dans l'audit complet, qui continue de tout compter.
    """
    import importlib.util as _iu

    spec = _iu.spec_from_file_location("_fda_nr2", AUDIT)
    mod = _iu.module_from_spec(spec)
    spec.loader.exec_module(mod)

    for prose in ("⚠️ Deux réserves honnêtes, ni l'une ni l'autre bloquante",
                  "**Go.** Ta précondition est satisfaite",
                  "1. Une grande part est de la config env-spécifique",
                  "- Le lanceur : _service_action() écrite ligne 136",
                  "| colonne | valeur |"):
        assert mod._forme_de_rapport(prose), (
            "cette sortie d'agent passerait pour une directive : %r" % prose[:60])

    for parole in ("coupe docker des que la tache est finie",
                   "c est toujours pas acceptable, ce qui n est pas utile",
                   "rien ne doit plus se lancer au clic",
                   "allow_critical oui"):
        assert not mod._forme_de_rapport(parole), (
            "une parole d'owner est écartée à tort : %r" % parole[:60])


def test_le_resume_de_compaction_est_ecarte_a_la_source():
    """Le filtre de forme ne doit pas être le seul rempart : la CAUSE est un
    champ du format, et elle se traite là où elle naît."""
    corps = _corps(AUDIT, "messages_owner")
    assert "isCompactSummary" in corps, (
        "les résumés de compaction ne sont pas écartés : ils portent la prose "
        "de l'assistant sous l'étiquette « user »")


def test_l_indisponibilite_est_DITE():
    """ILLISIBLE != VIDE != contenu : les trois doivent se distinguer à l'écran."""
    corps = _corps(APP, "api_hub_persona").lower()
    assert "indisponible" in corps, (
        "quand la source manque, la route doit le DIRE : un écran vide ou un "
        "contenu de substitution se lit comme une mesure")
