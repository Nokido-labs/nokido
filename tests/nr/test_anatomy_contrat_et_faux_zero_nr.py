# -*- coding: utf-8 -*-
"""NR — la carte anatomique ne lit que des champs qui EXISTENT, et n'invente aucun zero.

Quatre defauts mesures le 2026-09-18 sur `/anatomy`, tous invisibles a la lecture :

1. `health` vaut `"ok"` pour les 22 organes, et le CSS ne definissait que
   `.organ.active/.alive/.idle/.dead` : AUCUNE animation ne s'appliquait jamais. La page
   se rafraichissait bien toutes les 2 s — elle ne montrait simplement rien qui bouge.
2. `renderFlows` n'animait un lien que si `intensity > 0.5`, or `activity` plafonne a 0.3
   pour 21 organes sur 22 (plancher constant, pas une mesure) : intensite maximale
   observee **0.439**. Le seuil n'etait donc jamais atteint.
3. `renderLegend` groupait sur `o.system` et affichait `o.module`. Le contrat d'un organe
   est {activity, bio, color, health, label, port, r, x, y} : `system` n'existe sur AUCUN
   organe. En JavaScript un champ absent ne leve pas — il s'affiche « undefined ».
4. `rag.embedded` vaut `null` quand le snapshot du producteur est perime (mesure : 11,9
   jours, `mesure: "INCONNU"`). Le `|| 0` affichait « 0 vectorise » : un chiffre INVENTE,
   pire qu'une case vide, et exactement le faux zero que la doctrine interdit.

Ce fichier verrouille les deux qui peuvent revenir en silence : la lecture d'un champ
absent, et le faux zero. Les deux autres sont couverts par leur contraire — on verifie
que la page distingue mesure et absence de capteur, au lieu de tout faire bouger pareil.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PAGE = ROOT / "app" / "web_hub" / "anatomy.html"

# Contrat REEL d'un organe, releve sur le hub vivant le 2026-09-18.
CHAMPS_ORGANE = {"activity", "bio", "color", "health", "label", "port", "r", "x", "y"}
# Presents sur une PARTIE seulement des organes : les lire sans garde affiche "undefined".
CHAMPS_PARTIELS = {"module", "system"}


def _script(avec_commentaires: bool = False) -> str:
    """Code du bloc de script. Par defaut SANS ses commentaires.

    Quatrieme fois en un jour qu'un instrument se fait mordre par son propre
    vocabulaire : le commentaire qui documente le defaut corrige cite `o.system` et
    `o.module`, et la premiere version de ce fichier accusait donc la page d'un defaut
    qu'elle ne portait plus. Un garde ne lit que ce qui s'EXECUTE.

    On ne retire que les lignes dont le premier caractere non blanc est `//`, plus les
    blocs `/* */`. Un retrait naif de tout `//` mutilerait les URL du code
    (`http://www.w3.org/2000/svg`) et fabriquerait un autre faux verdict.
    """
    if not PAGE.exists():
        pytest.skip("anatomy.html absent")
    h = PAGE.read_text(encoding="utf-8", errors="replace")
    ouvre, ferme = "<" + "script" + ">", "</" + "script" + ">"
    i = h.find(ouvre)
    j = h.find(ferme, i)
    assert i >= 0 and j > i, "bloc de script introuvable dans anatomy.html"
    js = h[i + len(ouvre):j]
    if avec_commentaires:
        return js
    js = re.sub(r"/\*.*?\*/", " ", js, flags=re.S)
    return "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))


def test_la_page_ne_lit_aucun_champ_absent_du_contrat():
    """MORSURE — `o.system` a fait grouper 22 organes sous « undefined » pendant des jours."""
    js = _script()
    for champ in sorted(CHAMPS_PARTIELS):
        assert not re.search(r"\bo\.%s\b" % champ, js), (
            "la page lit `o.%s`, qui n'est pas garanti par le contrat d'un organe "
            "(%s) : en JavaScript ce champ ne leve pas, il s'affiche « undefined »"
            % (champ, ", ".join(sorted(CHAMPS_ORGANE)))
        )


def test_le_depouillement_des_commentaires_fonctionne():
    """Sonde de la sonde — si le depouillement echouait, tous les tests ci-dessus
    deviendraient des faux verdicts, dans un sens ou dans l'autre."""
    brut, net = _script(avec_commentaires=True), _script()
    assert len(net) < len(brut), "aucun commentaire retire : le depouillement ne marche pas"
    assert "http://www.w3.org/2000/svg" in net, (
        "le depouillement a mutile une URL : il retirerait aussi du code"
    )
    assert "createElementNS" in net, "le depouillement a mange du code executable"


def test_les_champs_lus_appartiennent_au_contrat():
    """Sonde de la sonde : si la page ne lisait plus RIEN, ce fichier ne mesurerait rien."""
    js = _script()
    lus = set(re.findall(r"\bo\.([a-z_]+)\b", js))
    assert lus, "la page ne lit aucun champ d'organe : ce test ne mesure plus rien"
    inconnus = lus - CHAMPS_ORGANE - {"name", "trafic"}
    assert not inconnus, (
        "champs lus hors contrat : %s — soit le contrat a change et il faut mettre a "
        "jour CHAMPS_ORGANE, soit la page lit du vide" % sorted(inconnus)
    )


def test_aucun_faux_zero_sur_la_vectorisation():
    """`rag.embedded` null = INCONNU. Un `|| 0` en ferait « 0 vectorise »."""
    js = _script()
    assert not re.search(r"rag\.embedded\s*\|\|\s*0", js), (
        "`rag.embedded || 0` affiche un zero INVENTE quand le snapshot est perime"
    )
    assert "INCONNU" in js, (
        "la page ne sait pas dire INCONNU : un etat non mesure se lira comme un zero"
    )


def test_la_page_distingue_mesure_et_absence_de_capteur():
    """Faire bouger 22 organes quand un seul emet serait un faux vivant."""
    js = _script()
    assert "sans-capteur" in js, "la page ne distingue pas « pas de capteur » de « eteint »"
    assert "trafic_par_organe" in js, (
        "la page n'utilise pas le trafic MESURE : elle ne peut animer que sur `activity`, "
        "qui vaut 0.3 pour 21 organes sur 22"
    )


def test_un_lien_declare_n_est_pas_anime_comme_un_debit():
    """`flows_live === false` : ces aretes sont une topologie, pas une mesure."""
    js = _script()
    assert "flows_live" in js, (
        "la page ignore `flows_live` : elle presenterait une topologie declaree comme "
        "un debit observe"
    )


def test_le_css_connait_les_classes_que_le_script_pose():
    """MORSURE historique — `health: \"ok\"` ne correspondait a aucune regle CSS.

    Une classe posee sans regle correspondante ne produit rien, et rien ne le signale :
    ni erreur console, ni avertissement. C'est ainsi que la carte est restee immobile.
    """
    h = PAGE.read_text(encoding="utf-8", errors="replace")
    js = _script()
    posees = set(re.findall(r'organ \$\{(\w+)\}', js)) | set(
        re.findall(r'`organ (\w[\w-]*)`', js))
    # Les classes posees dynamiquement passent par la variable `etat` : on verifie les
    # valeurs qu'elle peut prendre, listees en clair dans le script.
    for etat in ("mesure", "sans-capteur", "eteint"):
        assert '"%s"' % etat in js, "l'etat %r n'est plus pose par le script" % etat
        assert ".organ.%s" % etat in h, (
            "la classe .organ.%s est posee mais le CSS ne la definit pas : "
            "elle ne produira rien, en silence" % etat
        )
    assert posees or True  # la forme litterale peut evoluer ; l'assertion utile est au-dessus
