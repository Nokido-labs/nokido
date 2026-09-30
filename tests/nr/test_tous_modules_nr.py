"""NR — UN test par module. Tous les modules, sans exception.

Demande owner du 2026-08-14 : « je veux du NR sur chaque module ». Mesure du
jour : 73 modules testes sur 1138, soit 6,5 %. Ecrire 1065 tests metier a la
main est hors de portee et serait, pour l'essentiel, du test de facade.

Ce fichier prend l'autre chemin : des invariants STRUCTURELS, verifies sur
CHAQUE module, choisis parce qu'ils correspondent a des pannes REELLEMENT
survenues sur ce depot. Ils ne remplacent pas un test metier — ils garantissent
qu'aucun module n'est plus jamais totalement hors surveillance.

Les deux invariants ont ete MESURES avant d'etre cables, pour ne pas cabler un
garde qui hurle (regle owner : mesurer avant cabler) :

  * PARSE          1138 modules, 0 echec. Un module qui ne parse plus est mort
                   pour tout le systeme ; le cout du test est nul et le signal
                   total.
  * PAS DE DOUBLON 2 cas sur 1138. Une definition en double ecrase la premiere
                   SILENCIEUSEMENT a l'import : ni erreur, ni avertissement, et
                   toute correction apportee a la premiere reste sans effet.
                   C'est exactement l'incident `embed_batch` defini 2x
                   (2026-08-03) et `_after_wizard` (retire ce jour).

Ecarte volontairement : `except:` nu — 57 occurrences, deja suivi par le hook
de recidive du gate de commit. Le doubler ici rendrait la suite rouge en
permanence, donc illisible, et un garde illisible ne garde rien.
"""
from __future__ import annotations

import ast
import collections
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Dette CONNUE et DECLAREE. Un doublon inscrit ici ne fait pas rougir la suite,
# mais il reste visible — on ne le masque pas, on le date et on dit pourquoi il
# n'est pas encore tranche.
# Vide, et c'est le but : la seule entree qu'il ait jamais portee
# (`forge_self_correction.rebuild_fts_index`) a ete RESOLUE le 2026-08-14 en
# rendant a chaque fonction un nom qui dit sa table, plutot qu'en supprimant
# celle qu'on croyait de trop. Le test `test_la_dette_declaree_existe_encore`
# aurait signale la tolerance devenue sans objet — il a fait son office.
DOUBLONS_TOLERES: dict[str, dict] = {
    # Releves en elargissant le perimetre a 2307 modules (2026-08-14). Ni l'un
    # ni l'autre n'est tranche a l'aveugle : `Nokido.py` fait 4849 lignes et est
    # le point d'entree historique, `patch.py` un utilitaire de patch. Les
    # inscrire ICI les rend visibles et dates, plutot que de les faire
    # disparaitre en retrecissant le perimetre — ce qui serait le reflexe
    # exactement inverse de celui qu'on cherche.
    "Nokido.py": {
        # `get_remote_context` manquait a l'appel : ma mesure affichait `d[:2]`
        # et j'ai recopie l'affichage au lieu du resultat. Un tronquage a
        # l'ecran devient un fait faux des qu'on le prend pour la liste.
        "noms": {"_silent", "looks_like_shell_command", "get_remote_context"},
        "motif": "Point d'entree historique (4849 lignes), exclu du lint par "
                 "EXCLUDE dans ci_local. A trancher avec l'owner.",
    },
    "patch.py": {
        "noms": {"_sentinel_check"},
        "motif": "Deux definitions de _sentinel_check ; verifier laquelle est "
                 "voulue avant d'en supprimer une.",
    },
}


IGNORES = {"_attic", "node_modules", "backups", "archive"}


def _modules() -> list[Path]:
    """TOUS les modules de code, pas seulement les `forge_*` de premier niveau.

    La premiere version ne prenait que `app/*.py` et `tools/*.py` commencant par
    `forge_` : 1138 modules sur 2307, soit la MOITIE du code hors surveillance —
    tous les sous-dossiers (`web_hub`, `ctf`, `collab_modes`, `views`) et tous
    les modules qui ne portent pas le prefixe. Un « 100 % » calcule sur un
    perimetre choisi n'est pas une couverture, c'est un cadrage.
    """
    out = []
    # `forge_desktop` est ABSENT du depot (`.gitignore` l'exclut en entier) :
    # l'inclure faisait diverger le local du runner CI, qui travaille sur un
    # clone. Un test doit porter sur ce que le depot contient, pas sur ce que
    # mon disque contient — sinon il atteste d'un etat que personne d'autre
    # n'a. Les modules desktop restent testables localement, pas en CI.
    for zone in ("app", "tools", "recon_silo"):
        racine = ROOT / zone
        if not racine.is_dir():
            continue
        for p in sorted(racine.glob("**/*.py")):
            if not (IGNORES & set(p.parts)):
                out.append(p)
    return out


MODULES = _modules()
assert MODULES, "aucun module trouve — le test se croirait vert sur un vide"


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.stem)
def test_module_parse(module: Path):
    """Le module doit rester analysable. Sans cela il est mort pour tout appelant."""
    src = module.read_text(encoding="utf-8", errors="replace")
    try:
        ast.parse(src)
    except SyntaxError as e:
        pytest.fail(f"{module.name} ne parse plus : {e}")


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.stem)
def test_module_sans_definition_ecrasee(module: Path):
    """Aucun nom defini deux fois au premier niveau.

    La seconde definition ecrase la premiere a l'import, sans un mot. Le piege
    est qu'on corrige alors du code qui ne s'execute jamais.
    """
    src = module.read_text(encoding="utf-8", errors="replace")
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        pytest.skip("ne parse pas — signale par test_module_parse")
    noms = [n.name for n in arbre.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    doublons = {k for k, v in collections.Counter(noms).items() if v > 1}
    toleres = DOUBLONS_TOLERES.get(module.name, {}).get("noms", set())
    restants = doublons - toleres
    assert not restants, (
        f"{module.name} definit {sorted(restants)} plusieurs fois au premier "
        "niveau : la derniere definition ecrase les precedentes a l'import, "
        "silencieusement."
    )


# Collisions CONNUES au 2026-08-15 : meme nom importable dans `app/` ET
# `tools/`, contenus DIFFERENTS. L'implementation chargee depend de l'ordre de
# `sys.path`, donc de l'appelant — demontre ce jour : selon l'ordre des
# `sys.path.insert`, `import forge_thought_interceptor` rend 2 027 o ou
# 13 481 o. Gelees ici plutot que fusionnees a l'aveugle : les contenus
# divergent (jusqu'a x52 pour engrid_engine) et trancher demande de savoir
# laquelle sert. Aucune NOUVELLE collision ne passera.
COLLISIONS_GELEES = {
    "forge_dep_manager", "forge_docker_audit", "forge_engrid_engine",
    "forge_js_endpoint_extractor", "forge_ping_monitor", "forge_quality_gate",
    "forge_thought_interceptor", "mcp_nr",
}


def test_aucune_nouvelle_collision_de_nom():
    """Deux fichiers de meme nom a la racine de deux chemins d'import.

    Seules les RACINES comptent : `app/` et `tools/` sont insérés dans
    `sys.path`, un fichier en sous-dossier s'importe par son package et n'entre
    pas en collision. Compter les sous-dossiers ferait remonter 22 « doublons »
    qui n'en sont pas — les agents metier ont tous leur `agent_core.py`.
    """
    import collections

    vus = collections.defaultdict(list)
    for zone in ("app", "tools"):
        for p in (ROOT / zone).glob("*.py"):
            if p.name != "__init__.py":
                vus[p.stem].append(p)
    collisions = {k for k, v in vus.items() if len(v) > 1}
    nouvelles = sorted(collisions - COLLISIONS_GELEES)
    assert not nouvelles, (
        f"{len(nouvelles)} nouvelle(s) collision(s) de nom : {nouvelles}\n"
        "Le module charge dependra de l'ordre de sys.path, donc de l'appelant."
    )


def test_les_collisions_gelees_existent_encore():
    """Une collision resolue doit sortir de la liste, sinon elle couvrirait
    une future collision portant le meme nom."""
    import collections

    vus = collections.defaultdict(list)
    for zone in ("app", "tools"):
        for p in (ROOT / zone).glob("*.py"):
            if p.name != "__init__.py":
                vus[p.stem].append(p)
    reelles = {k for k, v in vus.items() if len(v) > 1}
    perimees = sorted(COLLISIONS_GELEES - reelles)
    assert not perimees, (
        f"{perimees} ne sont plus en collision — retirer de COLLISIONS_GELEES."
    )


def test_la_dette_declaree_existe_encore():
    """Une tolerance qui ne correspond plus a rien doit disparaitre.

    Sans ce test, `DOUBLONS_TOLERES` deviendrait un cimetiere d'exceptions
    perimees qu'on n'ose plus retirer — et une exception perimee finit par
    couvrir un vrai defaut portant le meme nom.
    """
    for fichier, info in DOUBLONS_TOLERES.items():
        p = next((c for c in _modules() if c.name == fichier), None)
        assert p is not None, f"{fichier} tolere mais introuvable — retirer l'entree"
        arbre = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        noms = [n.name for n in arbre.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        vus = {k for k, v in collections.Counter(noms).items() if v > 1}
        perimes = info["noms"] - vus
        assert not perimes, (
            f"{fichier} : {sorted(perimes)} n'est plus duplique — retirer la "
            "tolerance de DOUBLONS_TOLERES."
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
