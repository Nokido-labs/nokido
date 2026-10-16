"""NR -- le workflow « Miroirs publics » du dist (owner 14/10 : toute publication part vers TOUS les depots publics).

Contrats :
  1. il PART dans le dist (WORKFLOWS_DIST), se declenche au tag de version, et ne tourne QUE sur le depot public
     (le fichier vit aussi dans le prive : sans garde, chaque tag y echouerait sans secrets) ;
  2. ses cibles sont EXACTEMENT celles de publish_multi.MIROIRS_PUBLICS (une forge ajoutee d'un cote et oubliee de
     l'autre rougit ici) ;
  3. aucun jeton dans une URL ni sur une ligne de commande -- en-tete http.extraHeader seulement ;
  4. un secret ABSENT est DIT (::error::) et fait echouer le job ; une forge en echec n'empeche pas les autres ;
  5. permissions minimales (contents: read), source = depot public lui-meme, branches + tags seulement.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

WF = ROOT / ".github" / "workflows" / "miroirs-publics.yml"
SECRETS = ("CODEBERG_TOKEN", "GITLAB_TOKEN", "HF_TOKEN", "SF_DEPLOY_KEY")


def _texte():
    return WF.read_text(encoding="utf-8")


def _constante(nom: str):
    """Une constante de publish_multi lue par AST : le module importe des modules lourds, la valeur suffit."""
    arbre = ast.parse((ROOT / "tools" / "publish_multi.py").read_text(encoding="utf-8"))
    for n in arbre.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == nom for t in n.targets):
            return ast.literal_eval(n.value)
    raise AssertionError("%s introuvable dans tools/publish_multi.py" % nom)


def _miroirs_publics() -> dict:
    return _constante("MIROIRS_PUBLICS")


def test_le_workflow_part_dans_le_dist_et_suit_la_fin_de_la_release():
    """Mesure 0.20.11 : declenche au tag, il partait AVANT le commit README du bot (miroirs a 19c350a, public a
    dc1667e). Il suit desormais la FIN de la release ; le nom vise doit etre EXACTEMENT celui de release.yml, sinon
    plus rien ne le declenche -- en silence."""
    import forge_dist_publish as m
    assert ".github/workflows/miroirs-publics.yml" in m.WORKFLOWS_DIST
    t = _texte()
    nom_release = re.search(r"^name:\s*(.+)$", (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"),
                            re.M).group(1).strip()
    assert 'workflows: ["%s"]' % nom_release in t, "workflow_run doit viser %r" % nom_release
    assert "types: [completed]" in t and "workflow_run.conclusion == 'success'" in t
    assert "github.repository == 'Nokido-labs/nokido'" in t, "le depot prive ne doit jamais lancer ce job"
    assert "refs/heads/main" in t and "describe --tags" in t, "verifie main ET le dernier tag"


def test_les_cibles_sont_celles_de_publish_multi():
    t = _texte()
    for nom, cible in _miroirs_publics().items():
        assert cible["url"] in t, "%s : cible absente du workflow (%s)" % (nom, cible["url"])


def test_aucun_jeton_dans_une_url():
    t = _texte()
    assert not re.search(r"https?://[^\s/'\"]*:\$\{?\w", t), "jeton dans une URL : il finirait dans les journaux git"
    assert "http.extraHeader" in t


def test_un_secret_absent_est_dit_et_une_forge_en_echec_n_arrete_pas_les_autres():
    t = _texte()
    for s in SECRETS:
        assert "secrets.%s" % s in t
        assert re.search(r"::error::%s absent" % s, t), "%s absent doit etre DIT" % s
    assert re.search(r"if \[ -s manquants \].*exit 1", t), "les forges non publiees font echouer le job"
    etapes = re.findall(r"- name: (.+)\n\s+if: \$\{\{ !cancelled\(\) \}\}", t)
    assert len(etapes) >= 5, "chaque forge et la verification se tentent meme apres un echec : %s" % etapes


def test_permissions_minimales_et_source_publique():
    t = _texte()
    assert re.search(r"permissions:\s*\n\s*contents:\s*read", t)
    assert "github.com/${{ github.repository }}.git" in t


def test_memes_refspecs_que_publish_multi_et_jamais_de_force():
    """Mesure 0.20.11 : la branche jetable essai/** etait refusee en non fast-forward par SF, Codeberg et GitLab.
    Le workflow pousse les MEMES refspecs que publish_multi (main + tags), et un miroir qui diverge le DIT."""
    t = _texte()
    attendu = " ".join("'%s'" % r for r in _constante("_REFSPECS"))
    assert attendu == "'refs/heads/main:refs/heads/main' 'refs/tags/*:refs/tags/*'"
    assert t.count(attendu) == 3, "les 3 forges git poussent main + tags"
    assert "push --force" not in t and "'refs/heads/*" not in t
