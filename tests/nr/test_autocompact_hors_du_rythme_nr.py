"""NR — aucun rythme circadien n'appelle plus NokidoAutoCompact, dans AUCUN runtime.

DECISION OWNER 2026-09-21, option B : « retirer le declenchement circadien et
garder l'outil en invocation manuelle avec son --dry-run ».

CE QUI A ETE MESURE AVANT LA DECISION
=====================================
`NokidoAutoCompact` etait reveille chaque CREPUSCULE et n'etait declare dans
AUCUN services.toml -- 7 des 8 services du programme le sont, lui seul manquait.
Le superviseur repondait « service non declare dans services.toml », et
`supervisor.ts` le CONSTATAIT en commentaire depuis le cutover du 2026-07-09
sans le corriger. Defaut visible, inerte, jamais solde.

CE QUI A TRANCHE, et ce n'est pas une question de style : `forge_auto_compact`
fait un `DELETE FROM rag_chunks` sur `RAG/embeddings.db`, la base de 25 Go --
operation que le module qualifie lui-meme d'irreversible et qui porte un gate
anti-regression. Declarer le service aurait ajoute un ECRIVAIN AUTOMATIQUE
QUOTIDIEN au verrou RAG, a rebours du P0 arrete le 2026-09-19 dont le critere
est que cette base CESSE de recevoir.

LES DEUX JUMEAUX, ET C'EST LE PIEGE PRINCIPAL
=============================================
Le programme circadien existe DEUX FOIS : `app/forge_circadian.py` (Python) et
`proxy_deno/core/supervisor.ts` (TypeScript). Mesure du 2026-09-20 : c'est le
TypeScript qui S'EXECUTE -- une correction portee au seul Python aurait ete un
correctif applique au jumeau mort, et le rythme aurait continue d'appeler.
Ce NR verifie donc LES DEUX, par lecture de fichier, parce qu'aucun import
Python ne peut voir le programme Deno.

CE QUI N'EST PAS SUPPRIME : l'outil. `tools/forge_auto_compact.py` reste
invocable a la main, avec son `--dry-run` qui ne mute rien. Retirer un
declenchement n'est pas enterrer une capacite.
"""
import pathlib

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
PY = RACINE / "app" / "forge_circadian.py"
TS = RACINE / "proxy_deno" / "core" / "supervisor.ts"
OUTIL = RACINE / "tools" / "forge_auto_compact.py"

SERVICE = "NokidoAutoCompact"


def _lignes_actives(chemin: pathlib.Path) -> list[str]:
    """Lignes de CODE seulement : un commentaire qui NOMME le service pour
    raconter son retrait n'est pas un declenchement. Sans cette distinction,
    l'instrument lirait son propre vocabulaire -- faute payee plusieurs fois."""
    actives = []
    for brut in chemin.read_text(encoding="utf-8", errors="replace").splitlines():
        nu = brut.strip()
        if nu.startswith("#") or nu.startswith("//") or nu.startswith("*"):
            continue
        actives.append(brut)
    return actives


@pytest.mark.parametrize("chemin", [PY, TS], ids=["python", "typescript"])
def test_aucun_runtime_ne_reveille_plus_ce_service(chemin):
    """LE test. Les deux jumeaux, parce que seul l'un des deux s'execute et que
    corriger l'autre ne changerait rien."""
    assert chemin.exists(), "%s a disparu : ce NR ne mesure plus rien" % chemin.name
    fautives = [l for l in _lignes_actives(chemin) if SERVICE in l]
    assert not fautives, (
        "%s reveille encore %s dans du CODE ACTIF :\n    %s\n"
        "Le rythme l'appellerait chaque jour pour un service non declare."
        % (chemin.name, SERVICE, "\n    ".join(l.strip()[:100] for l in fautives))
    )


def test_l_outil_n_est_PAS_supprime():
    """Retirer un declenchement n'est pas enterrer une capacite.

    « Geler, jamais supprimer » : le code reste invocable a la main, et c'est
    la moitie de la decision B -- sans elle on aurait perdu la compaction.
    """
    assert OUTIL.exists(), (
        "l'outil a ete supprime : la decision B retirait le DECLENCHEMENT, pas "
        "la capacite"
    )
    src = OUTIL.read_text(encoding="utf-8", errors="replace")
    assert "run_compaction" in src
    assert "dry_run" in src


def test_le_dry_run_ne_mute_rien():
    """Exigence du mandat : « si dry_run existe, verifier son contrat AVANT
    toute execution reelle ». C'est desormais le seul mode sur par defaut pour
    qui voudrait relancer la compaction a la main."""
    import ast

    arbre = ast.parse(OUTIL.read_text(encoding="utf-8", errors="replace"))
    fn = next((n for n in ast.walk(arbre)
               if isinstance(n, ast.FunctionDef) and n.name == "compact_batch"), None)
    assert fn is not None, "compact_batch introuvable : la forme du module a change"
    corps = ast.unparse(fn)
    # Le DELETE doit etre garde par une sortie anticipee quand dry_run est vrai.
    assert "dry_run" in corps, "compact_batch ignore dry_run : il muterait toujours"
    assert "DELETE" in corps, "ce NR decrit le mauvais site : le DELETE n'est plus ici"
    i_garde = corps.find("dry_run")
    i_delete = corps.find("DELETE")
    assert i_garde < i_delete, (
        "le DELETE precede la garde dry_run : un dry_run muterait la base de "
        "25 Go, ce qui est exactement ce qu'il existe pour empecher"
    )


def test_le_retrait_laisse_sa_trace():
    """Un retrait sans trace se refait a l'identique six mois plus tard.

    Le fichier doit garder la RAISON, pas seulement l'absence.
    """
    for chemin in (PY, TS):
        txt = chemin.read_text(encoding="utf-8", errors="replace")
        assert SERVICE in txt, (
            "%s ne mentionne plus du tout %s : l'absence seule ne dit pas "
            "POURQUOI, et le declenchement sera recree" % (chemin.name, SERVICE)
        )
