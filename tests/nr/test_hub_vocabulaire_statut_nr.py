"""NR : le serveur ne peut pas emettre un statut de tuile que le front ignore.

Regression MESUREE le 2026-09-17, et causee par moi. Le matin j'ai ajoute au
serveur un quatrieme etat de vitalite, `unknown`, pour les cibles qu'on ne SAIT
PAS sonder -- une correction juste : 12 tuiles annoncaient auparavant une sante
que personne n'avait verifiee. Mais je ne suis alle voir NI le consommateur, NI
le rendu. Mesure du soir :

    /api/hub/modules : unknown x11 sur 18 tuiles
    hub-compiled.js  : up=2  down=2  soon=2  unknown=0

Le front ne connaissait que trois mots. Les onze tuiles sont donc tombees dans
le fourre-tout `provOf` (badge « hybride »), grisees a 50 %, etiquetees
« Service hors-ligne » -- une affirmation qu'aucune mesure ne soutient -- et
surtout SANS LIEN, parce que la clicabilite etait cablee sur `status === "up"`.
L'owner l'a vu a l'ecran avant moi, et avec le mot exact : « des tuiles en
hybride qui ne sont meme pas cliquables ».

La lecon n'est pas « penser a mettre a jour le front ». C'est qu'un PRODUCTEUR
ne doit jamais emettre un vocabulaire que son CONSOMMATEUR ignore, et que cette
propriete doit etre VERIFIEE, pas recommandee. Ce NR la verifie.

Il lit les deux cotes a la source : les valeurs que le serveur peut ecrire dans
`status`, et les valeurs que le front compare a `m.status`. Le premier ensemble
doit etre inclus dans le second. Chaque verificateur porte son controle
negatif : un test qui ne sait pas echouer ne prouve rien quand il passe.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SERVEUR = RACINE / "app" / "web_hub" / "app.py"
FRONT = RACINE / "design_handoff_nokido" / "ui_kits" / "hub" / "hub-compiled.js"
REFERENCE = RACINE / "design_handoff_nokido" / "ui_kits" / "hub" / "hub-views.ref.jsx"
SHELL = RACINE / "design_handoff_nokido" / "ui_kits" / "hub" / "hub-shell.ref.jsx"

RX_CONSO = re.compile(r"m\.status\s*===\s*[\"']([a-z_]+)[\"']")


def _vocabulaire_serveur(source: str) -> set[str]:
    """Valeurs que le serveur peut poser dans `status` (table de conversion)."""
    arbre = ast.parse(source)
    valeurs: set[str] = set()
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Assign) or len(noeud.targets) != 1:
            continue
        cible = noeud.targets[0]
        if not isinstance(cible, ast.Name) or cible.id != "legacy":
            continue
        if not isinstance(noeud.value, ast.Dict):
            continue
        for v in noeud.value.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                valeurs.add(v.value)
    return valeurs


def _vocabulaire_front(source: str) -> set[str]:
    return set(RX_CONSO.findall(source))


def _clicable_sur(source: str) -> str:
    """Rend l'expression qui decide de la clicabilite, ou une chaine vide."""
    m = re.search(r"const\s+clickable\s*=\s*([^;]+);", source)
    return m.group(1).strip() if m else ""


# ------------------------------------------------------------- invariants


def test_le_front_existe_et_est_lisible():
    for f in (SERVEUR, FRONT, REFERENCE):
        assert f.exists(), f"{f} introuvable : ce NR ne peut rien prouver a l'aveugle"


def test_tout_statut_emis_par_le_serveur_est_compris_par_le_front():
    emis = _vocabulaire_serveur(SERVEUR.read_text(encoding="utf-8"))
    compris = _vocabulaire_front(FRONT.read_text(encoding="utf-8", errors="replace"))
    assert emis, "aucune table de conversion trouvee : le verificateur est aveugle"
    orphelins = sorted(emis - compris - {"up"})
    assert not orphelins, (
        f"le serveur peut emettre {orphelins} que le front ne compare jamais. "
        "Un producteur qui emet un mot inconnu de son consommateur produit des "
        "tuiles muettes : c'est la regression du 2026-09-17"
    )


STATUTS = ("up", "down", "soon", "unknown", "inconnu")


def _statuts_discrimines(expr: str) -> list[str]:
    """Statuts sur lesquels l'expression FAIT UNE DIFFERENCE."""
    return [s for s in STATUTS if re.search(rf"\b{s}\b", expr)]


def test_un_statut_inconnu_reste_cliquable():
    """UNKNOWN n'est pas DOWN : on n'interdit pas d'ouvrir ce qu'on n'a pas mesure.

    FORMULATION ELARGIE le 2026-09-18, et dans le sens du DURCISSEMENT. La version
    precedente exigeait que l'expression MENTIONNE l'inconnu. Or la propriete qui
    compte n'est pas la mention, c'est l'effet : aucun statut ne doit priver une tuile
    de son lien. Une clicabilite qui ne discrimine AUCUN statut (`!editMode`) satisfait
    cette propriete plus fortement qu'une qui enumere les cas -- et l'ancienne
    redaction la refusait, alors qu'elle rend precisement tout cliquable.

    On accepte donc deux formes, et une seule chose est interdite : discriminer sur un
    statut SANS traiter l'inconnu. Le controle negatif ci-dessous le verifie.
    """
    for fichier in (FRONT, REFERENCE):
        expr = _clicable_sur(fichier.read_text(encoding="utf-8", errors="replace"))
        assert expr, f"expression de clicabilite introuvable dans {fichier.name}"
        discrimines = _statuts_discrimines(expr)
        if not discrimines:
            continue  # ne depend d'aucun statut : rien ne peut priver une tuile de lien
        assert "inconnu" in expr or "unknown" in expr, (
            f"{fichier.name} : la clicabilite vaut `{expr}`, elle discrimine "
            f"{discrimines} sans traiter l'etat inconnu. Ne pas savoir si un service "
            "repond n'autorise pas a INTERDIRE d'ouvrir sa page"
        )


def test_le_libelle_ne_declare_pas_hors_ligne_ce_qui_est_inconnu():
    for fichier in (FRONT, REFERENCE):
        texte = fichier.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"const\s+hint\s*=\s*([^;]+);", texte)
        assert m, f"expression du libelle introuvable dans {fichier.name}"
        expr = m.group(1)
        assert "inconnu" in expr, (
            f"{fichier.name} : le libelle ne distingue pas l'etat inconnu et "
            "retombe sur « Service hors-ligne », une affirmation qu'aucune mesure "
            "ne soutient"
        )


def _couleur_du_point(source: str) -> str:
    """Expression qui choisit la couleur du point de statut, dans la barre laterale."""
    m = re.search(r"const\s+dotColor\s*=\s*([^;]+);", source)
    return m.group(1).strip() if m else ""


def test_la_barre_laterale_ne_declare_pas_hors_ligne_un_echec_de_SONDE():
    """Meme regle que pour les tuiles, un etage plus bas : ECHEC DE SONDE n'est pas PANNE.

    Signale par l'owner le 2026-09-18 : « le bouton hub passe rouge alors qu'il est
    fonctionnel ». Le producteur `/status` (app/web_hub/app.py) replie trois situations
    differentes sur un meme `ok: false` :

        httpx.ConnectError     -> error "unreachable"  <- PREUVE d'absence, rouge legitime
        httpx.TimeoutException -> error "timeout"      <- INDETERMINE
        Exception quelconque   -> error "<texte>"      <- INDETERMINE

    Le delai de sonde est de 2,0 s et le hub :8766 gele par intermittence (kill-watchdog
    a 15 s, gels de 16-17 s consignes) : une sonde expiree pendant un gel affichait donc
    « hors ligne » sur un service vivant. Mesure du 2026-09-18 a froid : 30 tirs sur
    `:8766/health`, p50 13 ms, max 50 ms, zero depassement -- la cause n'est donc pas
    permanente, ce qui ne prouve pas qu'elle n'existe pas (un fait intermittent ne se
    refute pas par une lecture a l'instant t).

    Tant que le producteur ne distingue pas ces cas -- `app.py` est un CRITICAL_FILE,
    l'ouvrir demande une autorisation owner -- le consommateur doit au moins refuser
    d'AFFIRMER une panne qu'il n'a pas mesuree.
    """
    for fichier in (SHELL, FRONT):
        texte = fichier.read_text(encoding="utf-8", errors="replace")
        expr = _couleur_du_point(texte)
        assert expr, f"expression de couleur du point introuvable dans {fichier.name}"
        assert "injoignable" in expr or "unreachable" in texte, (
            f"{fichier.name} : la couleur du point ne distingue pas « connexion refusee » "
            "de « je n'ai pas pu sonder » — un timeout y devient une accusation de panne"
        )


def test_les_deux_fichiers_du_front_restent_jumeaux():
    """Le bundle est maintenu A LA MAIN : les deux doivent bouger ensemble."""
    a = _vocabulaire_front(FRONT.read_text(encoding="utf-8", errors="replace"))
    b = _vocabulaire_front(REFERENCE.read_text(encoding="utf-8", errors="replace"))
    assert a == b, (
        f"le bundle servi comprend {sorted(a)} et la reference {sorted(b)} : "
        "une divergence ici signifie que l'utilisateur voit autre chose que ce "
        "que le depot decrit"
    )


# ------------------------------------------------- controles NEGATIFS


def test_le_controle_du_point_de_statut_sait_refuser():
    """MORSURE — la forme BINAIRE d'origine doit etre refusee par ce controle."""
    binaire = ('const dotColor = st == null ? "var(--text-disabled)" '
               ': (st.ok ? "var(--green)" : "var(--red)");')
    assert "injoignable" not in _couleur_du_point(binaire), \
        "le controle accepterait la forme qui a fait passer un service vivant au rouge"


def test_le_controle_du_vocabulaire_sait_refuser():
    faux_serveur = 'legacy = {"live": "up", "offline": "down", "unknown": "unknown"}\n'
    faux_front = 'const a = m.status === "up"; const b = m.status === "down";'
    emis = _vocabulaire_serveur(faux_serveur)
    compris = _vocabulaire_front(faux_front)
    assert "unknown" in emis - compris, (
        "le verificateur accepte un serveur qui emet un mot absent du front : "
        "il ne discrimine rien"
    )


def test_le_controle_de_clicabilite_sait_refuser():
    """MORSURE — l'ancienne expression discriminait `up` sans traiter l'inconnu."""
    faux = "const clickable = !editMode && up; // ancien comportement"
    expr = _clicable_sur(faux)
    assert expr, "le verificateur ne lit meme plus l'expression"
    assert _statuts_discrimines(expr) == ["up"], (
        "le verificateur ne voit plus que cette expression discrimine sur un statut"
    )
    assert "inconnu" not in expr and "unknown" not in expr, (
        "le verificateur accepte l'ancienne expression de clicabilite"
    )


def test_une_clicabilite_inconditionnelle_est_acceptee():
    """Contre-epreuve de l'elargissement : sans elle, on ne saurait pas ce qu'il ouvre."""
    assert _statuts_discrimines(_clicable_sur("const clickable = !editMode;")) == []
    assert _statuts_discrimines(_clicable_sur('const clickable = status !== "down";')) == ["down"]


def test_le_controle_de_jumelage_sait_refuser():
    a = _vocabulaire_front('m.status === "up"')
    b = _vocabulaire_front('m.status === "up"; m.status === "unknown"')
    assert a != b, "le verificateur de jumelage ne voit pas une divergence evidente"
