"""NR -- un bouton « inconnu » doit devenir rare, et un non-effet ATTENDU n'est pas un defaut.

DEUX CONFUSIONS MESUREES le 2026-09-17, toutes deux de la meme famille que la
constitution semantique (`UNKNOWN != NO`) :

1. **`DISABLED_BY_POLICY` lu comme `UNKNOWN`.** La campagne a rapporte 3 boutons
   « inconnus » sur `/maison` -- dont `Status`, que le code de `SAFE_VERBS`
   ecarte DELIBEREMENT en le nommant : « ce qui appelle un appareil (Scan ADB,
   Shell, Screenshot, Status) reste HORS de cette liste ». On SAIT ce que c'est
   et on choisit de ne pas le cliquer -- ce n'est pas de l'ignorance. Or le
   fichier dit lui-meme qu'« un inconnu laisse croire qu'on ignore » : le
   rapport se contredisait.

2. **Un non-effet ATTENDU compte comme un clic sans effet.** Mesure directe sur
   le service vivant : le bouton « Chat » de `/postal` porte la classe
   `tab on` -- l'onglet est DEJA actif, et son gestionnaire rappelle le meme
   panneau. Reafficher l'onglet affiche ne change rien : par construction, pas
   par panne. Le rapporter comme « clique sans effet observable » fabrique un
   defaut a instruire qui n'existe pas, et noie les vrais.

CE QUE CE NR FIGE. Quatre etats la ou il y en avait trois, et une distinction
entre deux silences :

    safe            -> on clique
    hors_perimetre  -> on SAIT, et on ne clique pas (appareil, effet hors systeme)
    destructive     -> on sait que ca ECRIT, on ne clique pas
    unknown         -> on ne sait pas  ->  doit tendre vers zero

    changed=False sur un onglet DEJA ACTIF      -> attendu, ce n'est pas un defaut
    changed=False sur un bouton quelconque      -> a instruire

ASYMETRIE ASSUMEE, et c'est la regle du corps : sauter a tort coute une
COUVERTURE, cliquer a tort coute un EFFET sur un appareil. En cas de doute, on
saute -- mais on le NOMME.
"""
from __future__ import annotations

import pytest

CAMPAGNE = pytest.importorskip("tools.forge_ui_campaign")


# --------------------------------------------------------------------------
# 0. L'INSTRUMENT AVANT LA MESURE
# --------------------------------------------------------------------------

def test_les_classes_attendues_existent_toutes():
    """Un NR qui teste des noms absents passerait sur du vide."""
    for nom in ("_classify_btn", "SAFE_VERBS", "DESTRUCTIVE_VERBS",
                "HORS_PERIMETRE_VERBS", "_onglet_deja_actif"):
        assert hasattr(CAMPAGNE, nom), (
            "`%s` absent de forge_ui_campaign : le contrat ne peut pas etre "
            "verifie, donc ILLISIBLE -- ni vrai ni faux" % nom)


# --------------------------------------------------------------------------
# 1. CE QU'ON SAIT NE DOIT PLUS SORTIR EN « INCONNU »
# --------------------------------------------------------------------------

@pytest.mark.parametrize("texte", ["Scan ADB", "Status"])
def test_ce_qui_sollicite_un_appareil_est_NOMME_pas_inconnu(texte):
    """Ils sont ecartes par CHOIX ; le dire « inconnu » efface ce choix.

    ⚠ CORRECTION DU 2026-09-18 : « Shell » et « Screenshot » ont ete RETIRES de cette
    liste. Je les y avais mis le matin meme, en ignorant que le NR du 2026-08-29
    (`test_les_boutons_qui_ECRIVENT_ne_sont_pas_des_inconnus`) exige depuis trois
    semaines qu'ils soient dits `destructive`. J'ai donc remplace une doctrine
    existante par la mienne sans l'avoir lue, et fige mon choix dans ce fichier --
    deux gardes du meme depot se contredisaient, et la CI l'a vu.

    La doctrine ANTERIEURE fait foi, et sa raison tient : le cout des deux erreurs
    n'est pas symetrique. Un shell ouvre l'execution de commandes ; un declenchement
    de capture agit sur un appareil. Aucun des deux ne se PROUVE inoffensif, et ce
    qui ne se prouve pas inoffensif se range du cote prudent.

    Reste ici ce que le garde du 29/08 ne conteste pas : « Scan ADB » ENUMERE un
    peripherique, « Status » LIT. Ni l'un ni l'autre n'ecrit.
    """
    k = CAMPAGNE._classify_btn(texte)
    assert k == "hors_perimetre", (
        "%r classe `%s`. Ces boutons visent un appareil externe ou une lecture : le "
        "code les ecarte deja DELIBEREMENT de SAFE_VERBS en les nommant un par un. "
        "Les rendre `unknown` fait passer une politique pour de l'ignorance."
        % (texte, k))


@pytest.mark.parametrize("texte", ["🖥 Shell", "📸 Screenshot", "Shell", "Screenshot"])
def test_l_accord_avec_le_garde_du_29_aout_est_verrouille(texte):
    """MORSURE ANTI-DIVERGENCE — deux gardes du meme depot ne doivent plus se contredire.

    Sans ce test, rien n'empeche de re-ranger ces libelles en `hors_perimetre` : la
    contradiction ne se verrait qu'a la prochaine CI complete, et seulement parce
    qu'un AUTRE fichier la signale. On la fige donc ici aussi, du cote de la doctrine
    la plus ancienne.
    """
    assert CAMPAGNE._classify_btn(texte) == "destructive", (
        "%r n'est plus destructif : cela contredit le NR du 2026-08-29, qui l'exige "
        "avec sa raison -- sauter a tort coute une couverture, cliquer a tort coute "
        "un effet" % texte)


@pytest.mark.parametrize("texte", ["✕", "×", "✖", "Fermer", "Close"])
def test_une_fermeture_de_panneau_est_SURE_donc_eprouvee(texte):
    """Une croix ne porte aucun verbe : elle tombait en `unknown`, donc n'etait
    JAMAIS cliquee. Fermer un panneau est de l'affichage pur -- exactement le
    motif qui avait fait ajouter `logs` et `live` a SAFE_VERBS le 2026-08-29."""
    k = CAMPAGNE._classify_btn(texte)
    assert k == "safe", (
        "%r classe `%s` : une fermeture de panneau reste non eprouvee alors "
        "qu'elle n'a aucun effet a redouter" % (texte, k))


def test_ce_qui_ECRIT_reste_destructif():
    """Contre-epreuve : elargir les surs ne doit pas desarmer la prudence.
    `Save` sur /rbac enregistre une politique RBAC -- 14 occurrences le 29/08."""
    for texte in ("Save", "Enregistrer", "Appliquer", "Supprimer", "Redemarrer"):
        assert CAMPAGNE._classify_btn(texte) == "destructive", (
            "%r n'est plus classe destructif : un bouton qui ECRIT serait "
            "clique par la campagne" % texte)


def test_un_bouton_vraiment_muet_reste_INCONNU():
    """Le troisieme etat doit survivre : ne pas tout ranger pour faire du vert.
    Un libelle vide ou opaque n'est ni sur, ni destructif, ni une politique."""
    for texte in ("", "   ", "zzz42"):
        assert CAMPAGNE._classify_btn(texte) == "unknown", (
            "%r n'est plus `unknown` : on a fabrique une certitude" % texte)


# --------------------------------------------------------------------------
# 1bis. UN LIEN VERS UN SITE TIERS SORT DU PERIMETRE
# --------------------------------------------------------------------------

def test_un_bouton_qui_ouvre_un_site_tiers_est_hors_perimetre():
    """Mesure du 2026-09-18 : le dernier bouton « inconnu » de l'interface,
    sur /llm_dashboard, ouvrait simplement `guerrillamail.com` dans un onglet.

    Un lien externe ne peut RIEN ecrire dans le systeme : le ranger parmi les
    destructifs serait faux, le laisser inconnu serait pretendre qu'on ignore ce
    qu'on vient de lire. La regle porte sur la NATURE du geste, pas sur une
    liste de noms de sites, qu'il faudrait rallonger a chaque ajout.
    """
    assert CAMPAGNE._classify_btn("Guerrilla", externe=True) == "hors_perimetre"
    assert CAMPAGNE._classify_btn("Temp-Mail", externe=True) == "hors_perimetre"
    assert CAMPAGNE._classify_btn("n'importe quoi", externe=True) == "hors_perimetre"


def test_le_drapeau_externe_ne_blanchit_rien_quand_il_est_faux():
    """Morsure : la nouvelle porte ne doit pas devenir une porte derobee.
    Sans ce test, rendre `externe` toujours vrai ferait disparaitre d'un coup
    tous les destructifs -- et la campagne cesserait de proteger quoi que ce soit."""
    assert CAMPAGNE._classify_btn("Save", externe=False) == "destructive"
    assert CAMPAGNE._classify_btn("Supprimer", externe=False) == "destructive"
    assert CAMPAGNE._classify_btn("Chercher", externe=False) == "safe"


# --------------------------------------------------------------------------
# 2. UN NON-EFFET ATTENDU N'EST PAS UN DEFAUT
# --------------------------------------------------------------------------

def test_un_onglet_deja_actif_est_reconnu():
    """Le cas MESURE sur /postal, rendu tel quel par le service."""
    assert CAMPAGNE._onglet_deja_actif("tab on", None) is True
    assert CAMPAGNE._onglet_deja_actif("tab", "true") is True
    assert CAMPAGNE._onglet_deja_actif("nav-item active", None) is True


def test_un_onglet_INACTIF_n_est_pas_excuse():
    """La morsure. Sans elle, il suffirait de rendre True partout pour que tout
    non-effet devienne « attendu » -- et un onglet reellement casse passerait."""
    assert CAMPAGNE._onglet_deja_actif("tab", None) is False
    assert CAMPAGNE._onglet_deja_actif("", "false") is False
    assert CAMPAGNE._onglet_deja_actif(None, None) is False


def test_le_mot_actif_dans_un_autre_mot_ne_compte_pas():
    """`on` est un mot de classe, pas une sous-chaine : `button`, `icon` et
    `monitoring` contiennent `on` sans etre des onglets actifs. Une regle qui
    matche la sous-chaine excuserait le non-effet de presque tous les boutons
    de l'interface -- exactement le piege `findstr` du 2026-08-01."""
    for classes in ("button", "icon-tab", "monitoring", "bouton-on-hover"):
        assert CAMPAGNE._onglet_deja_actif(classes, None) is False, (
            "classes %r prises pour un onglet actif : la regle matche une "
            "sous-chaine au lieu d'un mot de classe" % classes)
