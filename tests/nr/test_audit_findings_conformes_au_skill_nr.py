# -*- coding: utf-8 -*-
"""NR — les artefacts d'audit restent conformes au contrat du skill Cloudflare.

CE QUI A ÉTÉ PAYÉ, ET QUI JUSTIFIE CE FICHIER
=============================================
La campagne porte le skill `cloudflare/security-audit`, dont le contrat machine est
`report-schema.json` interprété par `validate-findings.cjs`. Mesure du 2026-09-22 :

    run-1   9 findings   100 erreurs
    run-2   2 findings    34 erreurs      annoncé « 0 erreur » le 2026-09-18
    run-3   structure      1 erreur       ($ : expected array, got object)
    run-4   -             pas d'artefact
    run-5   -             pas d'artefact

`run-2` ÉTAIT valide, en `needs_validation`. Son verdict a été promu à `confirmed`
sans migrer les champs — chaque verdict a les siens — et un `validation_result`
absent du schéma y a été ajouté.

    UN ARTEFACT VALIDÉ UNE FOIS N'EST PAS UN ARTEFACT VALIDE.

Quatre jours sans que personne le voie, parce que la validation se lançait à la
main. C'est le motif du corps : une pratique qui ne vit que dans la session d'un
agent disparaît avec elle et se re-paie. Elle a donc une forme exécutable ici.

LES DEUX ASSERTIONS, ET POURQUOI PAS « ZÉRO »
=============================================
1. Le run le PLUS RÉCENT est à zéro erreur. C'est le cliquet utile : on ne produit
   plus jamais un artefact invalide, et un artefact promu sans migration tombe rouge
   au run suivant.
2. L'historique est PLAFONNÉ, pas exigé à zéro. Exiger zéro rendrait ce test rouge
   dès sa naissance, et un test rouge dès sa naissance se fait désarmer dans la
   semaine. Le plafond empêche l'aggravation pendant que la remise en conformité de
   run-1 à run-3 se décide.

CE QUE CE NR NE PEUT PAS GARDER, ET IL LE DIT
=============================================
`sandbox/audit/` n'est suivi par AUCUN commit (mesuré le 2026-09-22). En CI, qui
tourne dans un worktree détaché, les runs n'existent pas : le test ne peut alors
rien valider et il le DÉCLARE au lieu de passer au vert. Un test vert par absence de
données est exactement le faux calme que cette campagne documente.

    ILLISIBLE != CONFORME.   ABSENT != CONFORME.

Faire entrer ces artefacts sous git est une décision d'owner : ce sont des
livrables de sécurité, et un livrable hors revue est ce que la ligne R5 du registre
reproche déjà à un autre script.
"""

import re
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus node (code appele) (l.99)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_audit_findings_validate as V  # noqa: E402

# Mesuré le 2026-09-22 : 135 erreurs cumulées sur run-1 (100), run-2 (34), run-3 (1).
PLAFOND_ERREURS_HISTORIQUES = 135


def _outillage_ou_skip():
    ok, raison = V.outillage_disponible()
    if not ok:
        pytest.skip(f"validateur du skill inutilisable ({raison}) — couverture NON établie")


def _numero(nom):
    m = re.search(r"(\d+)$", nom)
    return int(m.group(1)) if m else -1


def test_le_validateur_mord_sur_un_artefact_invalide(tmp_path):
    """CONTRÔLE NÉGATIF : sans lui, un plafond respecté ne prouverait rien.
    Un validateur qui ne voit rien laisse passer tous les plafonds."""
    _outillage_ou_skip()
    audit = tmp_path / "audit"
    (audit / "run-1").mkdir(parents=True)
    # `confirmed` sans les champs que ce verdict exige — l'erreur exacte de run-2.
    (audit / "run-1" / "findings.json").write_text(
        '[{"verdict": "confirmed", "fingerprint": "x:y", "title": "t", "description": "d"}]',
        encoding="utf-8",
    )
    (audit / "run-2").mkdir()  # run sans artefact : compté à part, jamais conforme
    res = V.recenser(audit)
    assert res["runs"]["run-1"]["erreurs"], "le validateur accepte un `confirmed` amputé"
    assert res["sans_artefact"] == ["run-2"], (
        f"un run sans findings.json n'est pas recensé comme tel : {res['sans_artefact']}"
    )


def test_le_run_le_plus_recent_est_conforme():
    """Le cliquet qui compte : on ne produit plus d'artefact invalide."""
    _outillage_ou_skip()
    res = V.recenser()
    if res.get("racine_absente") or (not res["runs"] and not res["sans_artefact"]):
        pytest.skip(
            "aucun run d'audit sur cet arbre (sandbox/audit n'est pas suivi par git) — "
            "couverture NON établie, ce n'est pas une conformité"
        )
    assert not res["illisibles"], f"run(s) illisible(s), donc non couvert(s) : {res['illisibles']}"
    connus = {**{n: v for n, v in res["runs"].items()}}
    dernier_avec_artefact = max(connus, key=_numero) if connus else None
    dernier_tout_court = max(
        [*connus, *res["sans_artefact"]], key=_numero, default=None
    )
    print(
        f"[skill] {len(connus)} run(s) porteur(s) · {len(res['sans_artefact'])} sans artefact · "
        f"{res['total_erreurs']} erreur(s) cumulées · dernier = {dernier_tout_court}"
    )
    assert dernier_tout_court in connus, (
        f"le run le plus récent ({dernier_tout_court}) n'a PAS de findings.json : le format "
        "du skill a été abandonné au profit d'un rapport en prose. Un tableau se lit à "
        "l'oeil, un artefact se VALIDE."
    )
    erreurs = res["runs"][dernier_avec_artefact]["erreurs"]
    assert not erreurs, (
        f"{dernier_avec_artefact} porte {len(erreurs)} erreur(s) contre le contrat du "
        f"skill : {erreurs[:6]}"
    )


# Mesuré le 2026-09-22 : 4 ledgers présents, tous à zéro erreur ; run-3 et run-6
# n'en ont aucun. Le plafond porte sur les runs SANS ledger, pas sur zéro d'emblée :
# run-6 vient d'une délégation et son ledger est encore à produire.
PLAFOND_RUNS_SANS_LEDGER = 2


def test_tout_ledger_present_est_conforme():
    """Le skill a DEUX artefacts. `findings.json` dit ce qui a été TROUVÉ, le ledger
    dit ce qui a été REGARDÉ — sans lui, « rien trouvé » ne se distingue pas de
    « rien cherché »."""
    _outillage_ou_skip()
    res = V.recenser()
    if res.get("racine_absente") or not res.get("ledgers"):
        pytest.skip("aucun ledger sur cet arbre — couverture NON établie, pas une conformité")
    fautifs = {n: v["erreurs"] for n, v in res["ledgers"].items() if v["erreurs"]}
    print(
        f"[skill] {len(res['ledgers'])} ledger(s) · {res['total_erreurs_ledger']} erreur(s) · "
        f"{len(res.get('sans_ledger', []))} run(s) sans ledger"
    )
    assert not fautifs, (
        "ledger(s) non conforme(s) au contrat du skill : "
        + "; ".join(f"{n} -> {e[:3]}" for n, e in fautifs.items())
    )


def test_le_nombre_de_runs_sans_ledger_ne_croit_pas():
    """Un run sans ledger n'est pas un run propre : c'est un run dont la couverture
    est inconnue. Plafond plutôt que zéro, pour la raison habituelle."""
    _outillage_ou_skip()
    res = V.recenser()
    if res.get("racine_absente") or (not res["runs"] and not res.get("sans_ledger")):
        pytest.skip("aucun run d'audit sur cet arbre — couverture NON établie")
    sans = res.get("sans_ledger", [])
    assert len(sans) <= PLAFOND_RUNS_SANS_LEDGER, (
        f"{len(sans)} run(s) sans coverage-ledger.json, plafond {PLAFOND_RUNS_SANS_LEDGER} "
        f"(mesuré le 2026-09-22) : {sans}. Sans ledger on ne sait pas ce qui a été regardé."
    )


def test_les_erreurs_historiques_ne_croissent_pas():
    """Plafond, pas exigence de zéro : un test rouge dès sa naissance se fait désarmer."""
    _outillage_ou_skip()
    res = V.recenser()
    if res.get("racine_absente") or not res["runs"]:
        pytest.skip("aucun run d'audit sur cet arbre — couverture NON établie")
    assert res["total_erreurs"] <= PLAFOND_ERREURS_HISTORIQUES, (
        f"{res['total_erreurs']} erreurs cumulées contre le contrat du skill, plafond "
        f"{PLAFOND_ERREURS_HISTORIQUES} (mesuré le 2026-09-22). Détail par run : "
        + ", ".join(f"{n}={len(v['erreurs'])}" for n, v in res["runs"].items())
    )
