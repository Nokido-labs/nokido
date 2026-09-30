# -*- coding: utf-8 -*-
"""NR — un token de design a UNE valeur, quelle que soit la page qui le lit.

Mesure 2026-09-29 (tache pair_074f1865f105f88c, claude.ai, approuvee par l'owner) :
laforge-tokens.css (portail :8766) redefinissait 10 variables du :root, la seconde
valeur ecrasant la premiere. « Hybride » y prenait la couleur de « distant » (#774AFF),
l'anneau « verifie » passait du bleu au vert, cinq domaines changeaient de teinte --
alors que le hub React de :7400 gardait la palette de tokens/colors.css. Un etat qui en
imite un autre, c'est la premiere regle de la charte violee.

Trois chaines de styles sont comparees, valeur EFFECTIVE (derniere definition d'un bloc
`:root` le long des @import) :
- hub React (:7400/design/ui_kits/hub/)  : design_handoff_nokido/styles.css ;
- pages classiques d'app/web_hub (:7400) : app/web_hub/static/laforge-ds/styles.css ;
- portail (:8766/)                        : app/web_hub/static/laforge-tokens.css.

SOCLE : variables dont la divergence est CONNUE et laissee a la decision de l'owner. Il
ne fait que decroitre ; toute autre divergence est une regression.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAINES = {"hub": ROOT / "design_handoff_nokido" / "styles.css",
           "vanilla": ROOT / "app" / "web_hub" / "static" / "laforge-ds" / "styles.css",
           "portail": ROOT / "app" / "web_hub" / "static" / "laforge-tokens.css"}
# Vide depuis la decision owner du 2026-09-29 (--ease-in-out et --prov-local-tint alignes
# sur le hub) : toute divergence est desormais une regression.
SOCLE: set = set()


def _sans_commentaires(t: str) -> str:
    return re.sub(r"/\*.*?\*/", "", t, flags=re.S)


def _fichiers(entree: Path, vus=None) -> list:
    vus = vus if vus is not None else []
    if not entree.exists() or entree in vus:
        return vus
    t = _sans_commentaires(entree.read_text(encoding="utf-8", errors="replace"))
    for imp in re.findall(r'@import\s+(?:url\()?["\']([^"\']+)["\']', t):
        _fichiers((entree.parent / imp).resolve(), vus)
    vus.append(entree)
    return vus


def _decl_root(chemin: Path) -> list:
    t = _sans_commentaires(chemin.read_text(encoding="utf-8", errors="replace"))
    t = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", t)
    out = []
    for sel, corps in re.findall(r"([^{}]+)\{([^{}]*)\}", t):
        if sel.strip() == ":root":
            out += [(v, " ".join(x.split())) for v, x in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", corps)]
    return out


def _mesure():
    effectif, contradictions = {}, []
    for nom, entree in CHAINES.items():
        assert entree.exists(), "%s absent : la chaine %s n'est pas mesurable (ILLISIBLE, ni vrai ni faux)" % (entree, nom)
        eff = {}
        for f in _fichiers(entree.resolve()):
            vu = {}
            for v, x in _decl_root(f):
                if v in vu and vu[v] != x:
                    contradictions.append((f.relative_to(ROOT).as_posix(), v, vu[v], x))
                vu[v] = x
                eff[v] = x
        assert eff, "aucune variable :root lue dans la chaine %s -- parseur ou chemin a revoir" % nom
        effectif[nom] = eff
    return effectif, contradictions


def test_les_trois_chaines_donnent_la_meme_valeur():
    effectif, _ = _mesure()
    tous = set().union(*[set(e) for e in effectif.values()])
    divergentes = {v: {n: effectif[n].get(v) for n in CHAINES} for v in sorted(tous)
                   if len({effectif[n][v] for n in CHAINES if v in effectif[n]}) > 1}
    nouvelles = {v: d for v, d in divergentes.items() if v not in SOCLE}
    assert not nouvelles, "token a PLUSIEURS valeurs selon la page qui le lit : %s" % nouvelles


def test_aucun_fichier_ne_se_contredit_lui_meme():
    _, contradictions = _mesure()
    hors_socle = [c for c in contradictions if c[1] not in SOCLE]
    assert not hors_socle, "variable redefinie avec une AUTRE valeur dans le meme fichier (la seconde ecrase) : %s" % hors_socle


def test_hybride_et_distant_ne_se_confondent_jamais():
    effectif, _ = _mesure()
    for nom, eff in effectif.items():
        if "--prov-hybrid" in eff and "--prov-remote" in eff:
            assert eff["--prov-hybrid"] != eff["--prov-remote"], (
                "%s : « hybride » a la couleur de « distant » (%s)" % (nom, eff["--prov-hybrid"]))


def test_le_socle_ne_garde_que_des_divergences_reelles():
    """Un socle qui garde une variable deja alignee masquerait son retour : il doit decroitre."""
    effectif, _ = _mesure()
    perimees = [v for v in SOCLE if len({effectif[n][v] for n in CHAINES if v in effectif[n]}) <= 1]
    assert not perimees, "retirer du SOCLE ces variables, desormais alignees : %s" % perimees
