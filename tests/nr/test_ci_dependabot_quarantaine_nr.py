# -*- coding: utf-8 -*-
"""NR — aucune PR Dependabot ne peut atteindre le runner SELF-HOSTED.

__FORGE_COLOR__ = "immunitaire/guard : quarantaine des PR de dependances"

DEFAUT MESURE le 2026-09-10. `ci-selfhosted.yml` ouvrait EXPLICITEMENT ses PR
aux branches Dependabot :

    (github.event_name != 'pull_request' ||
     startsWith(github.head_ref, 'dependabot/'))

Deux defauts dans une seule ligne.

1. LA BARRIERE. `github.head_ref` est le NOM DE BRANCHE, choisi par l'auteur de
   la PR. Ce n'est pas une identite, c'est une etiquette — et une etiquette ne
   garde rien. L'identite etablie par GitHub est `pull_request.user.login` /
   `github.actor`.

2. LE RAISONNEMENT. Le commentaire disait « le contenu se borne a des montees
   de version ». Faux au sens de l'EXECUTION : une montee de version fait
   tourner du code tiers a l'installation, a l'import, dans les hooks du
   gestionnaire de paquets et pendant les tests. Avec 233 alertes ouvertes,
   c'etaient potentiellement 233 series de code non revu sur la machine qui
   heberge le hub :8766, les daemons, les modeles et le coffre.

CE QUI NUANCE, ET QUI A ETE MESURE : `dependabot_secrets = 0` (API, 2026-09-10),
donc les secrets du depot sont vides dans ces PR. Le risque n'est pas
l'exfiltration : c'est l'execution. On nomme la menace correctement plutot que
de la gonfler — un garde qui crie a faux se fait desarmer.

Modele retenu (decision owner) : quarantaine a deux etages.

    PR Dependabot -> ci-dependabot.yml (GitHub-hoste, jetable, 0 secret)
                  -> revue et merge HUMAINS
                  -> alpha -> ci-selfhosted.yml normal
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
QUARANTAINE = WF / "ci-dependabot.yml"

_SELF = re.compile(r"self-hosted", re.I)
_IDENTITE = ("github.actor", "pull_request.user.login", "github.event.sender.login")
_SECRETS_INTERDITS = ("LAFORGE_ADMIN_TOKEN", "PYPI_TOKEN", "TESTPYPI_TOKEN")


def _charge(f: Path) -> dict:
    return yaml.safe_load(f.read_text(encoding="utf-8", errors="replace")) or {}


def _declencheurs(doc: dict) -> dict:
    # PyYAML lit `on:` comme le booleen True (YAML 1.1). Sans ce contournement,
    # l'oracle lirait « aucun declencheur » sur TOUS les workflows et passerait
    # a vide — un faux vert massif.
    brut = doc.get("on", doc.get(True))
    if isinstance(brut, str):
        return {brut: None}
    if isinstance(brut, list):
        return {k: None for k in brut}
    return brut or {}


def _jobs_self_hosted_sur_pr(doc: dict) -> list[tuple[str, str]]:
    """(job, garde) des jobs self-hosted qu'un evenement de PR peut atteindre."""
    decl = _declencheurs(doc)
    if not any(str(k).startswith("pull_request") for k in decl):
        return []
    out = []
    for nom, j in (doc.get("jobs") or {}).items():
        if not _SELF.search(str(j.get("runs-on", ""))):
            continue
        garde = str(j.get("if", ""))
        if not _est_protege(garde):
            out.append((nom, garde))
    return out


def _termes_conjoints(garde: str) -> list[str]:
    """Termes relies par `&&` AU PREMIER NIVEAU de parentheses.

    On lit la STRUCTURE, pas la presence d'une sous-chaine. C'est toute la
    lecon du defaut corrige ici : `github.event_name != 'pull_request'` etait
    bien present dans le garde fautif, mais a l'interieur d'une disjonction qui
    l'annulait. Un terme conjoint de premier niveau, lui, s'applique TOUJOURS.
    """
    termes, profondeur, courant = [], 0, ""
    i = 0
    while i < len(garde):
        c = garde[i]
        if c == "(":
            profondeur += 1
        elif c == ")":
            profondeur -= 1
        if profondeur == 0 and garde[i:i + 2] == "&&":
            termes.append(courant)
            courant = ""
            i += 2
            continue
        courant += c
        i += 1
    termes.append(courant)
    return [t.strip() for t in termes if t.strip()]


def _est_protege(garde: str) -> bool:
    """Un job self-hosted est protege si un terme CONJOINT de premier niveau
    exclut Dependabot, ou borne l'evenement hors des PR."""
    if not garde:
        return False
    for t in _termes_conjoints(garde):
        # Une alternative interne ne compromet pas un terme conjoint, mais un
        # terme qui EST lui-meme une disjonction ne garantit rien a lui seul.
        if "||" in t:
            continue
        # ⚠️ UN TERME NIE N'EST PAS UNE BORNE. Troisieme occurrence du meme
        # defaut dans ce garde, trouvee en verifiant sa morsure : l'ancien
        # `gates` portait `!(github.event_name == 'workflow_dispatch' && ...)`,
        # et chercher la sous-chaine `workflow_dispatch` y lisait une borne la
        # ou il y a une EXCLUSION. La negation inverse le sens ; la sous-chaine
        # ne la voit pas.
        if t.lstrip().startswith("!") and not t.lstrip().startswith("!="):
            continue
        if any(m in t for m in _IDENTITE) and "dependabot" in t and "!=" in t:
            return True
        if ("github.event_name == 'workflow_dispatch'" in t
                or "github.event_name != 'pull_request'" in t):
            return True
    return False


def test_le_denominateur_est_non_vide():
    """Sans workflows lus, tous les tests suivants passeraient a vide."""
    fichiers = sorted(WF.glob("*.y*ml"))
    assert len(fichiers) >= 3, f"seulement {len(fichiers)} workflow(s) : perimetre suspect"
    avec_self = [f for f in fichiers
                 if _SELF.search(f.read_text(encoding="utf-8", errors="replace"))]
    assert avec_self, (
        "aucun workflow self-hosted trouve — ce garde n'aurait alors rien a garder, "
        "et son vert ne voudrait rien dire")


def test_aucun_job_self_hosted_n_est_ATTEIGNABLE_par_une_PR():
    """Le coeur du garde. Un job self-hosted declenchable par `pull_request` doit
    porter soit une borne d'evenement, soit une barriere d'IDENTITE."""
    ouverts = []
    for f in sorted(WF.glob("*.y*ml")):
        for nom, garde in _jobs_self_hosted_sur_pr(_charge(f)):
            ouverts.append(f"{f.name}::{nom} (garde={garde.strip()[:120]!r})")
    assert not ouverts, (
        "job(s) self-hosted atteignable(s) par une PR — du code non revu "
        "s'executerait sur la machine de l'owner :\n  " + "\n  ".join(ouverts))


def test_le_NOM_DE_BRANCHE_n_est_plus_utilise_comme_barriere():
    """`head_ref` est choisi par l'auteur de la PR. Une etiquette n'est pas une
    identite — c'est le defaut precis corrige le 2026-09-10."""
    fautifs = []
    for f in sorted(WF.glob("*.y*ml")):
        doc = _charge(f)
        for nom, j in (doc.get("jobs") or {}).items():
            garde = str(j.get("if", ""))
            if "head_ref" in garde and "dependabot" in garde:
                fautifs.append(f"{f.name}::{nom}")
    assert not fautifs, (
        "barriere fondee sur le NOM DE BRANCHE (controle par l'auteur de la PR) "
        f"au lieu de l'identite : {fautifs}")


def test_le_workflow_de_quarantaine_EXISTE_et_est_jetable():
    assert QUARANTAINE.is_file(), (
        "ci-dependabot.yml absent : retirer les PR du self-hosted sans gate de "
        "remplacement ne securise pas, ca supprime une mesure")
    doc = _charge(QUARANTAINE)
    jobs = doc.get("jobs") or {}
    assert jobs, "aucun job dans le workflow de quarantaine"
    for nom, j in jobs.items():
        runner = str(j.get("runs-on", ""))
        assert not _SELF.search(runner), (
            f"{nom} tourne sur {runner!r} : la quarantaine perdrait tout son sens")
        assert "ubuntu" in runner or "windows" in runner or "macos" in runner, (
            f"{nom} : runner inattendu {runner!r}")


def test_la_quarantaine_filtre_sur_l_IDENTITE_de_l_auteur():
    doc = _charge(QUARANTAINE)
    for nom, j in (doc.get("jobs") or {}).items():
        garde = str(j.get("if", ""))
        assert any(m in garde for m in _IDENTITE), (
            f"{nom} sans barriere d'identite : le workflow tournerait sur des PR "
            "humaines et deviendrait un gate parasite")
        assert "dependabot[bot]" in garde, f"{nom} ne cible pas Dependabot"


def test_la_quarantaine_n_a_AUCUN_secret():
    """Propriete MESUREE a conserver : `dependabot_secrets = 0`. Donner un secret
    a ce workflow la detruirait."""
    brut = QUARANTAINE.read_text(encoding="utf-8", errors="replace")
    for s in _SECRETS_INTERDITS:
        assert s not in brut, f"le workflow de quarantaine reference {s}"
    perms = _charge(QUARANTAINE).get("permissions") or {}
    assert perms == {"contents": "read"}, (
        f"permissions trop larges pour un gate de PR non revue : {perms}")


def test_la_quarantaine_DIT_ce_qu_elle_ne_couvre_pas():
    """Regle owner : `NOT_TESTED` n'est jamais converti en PASS. Un gate qui tait
    son angle mort laisse lire son vert comme « Nokido est certifie »."""
    brut = QUARANTAINE.read_text(encoding="utf-8", errors="replace")
    assert "LOCAL_INTEGRATION" in brut and "NOT_TESTED" in brut, (
        "le verdict ne declare pas l'integration locale comme NON TESTEE")
    for capacite in ("hub", "Ollama", "UI", "daemons"):
        assert capacite in brut, (
            f"l'angle mort ne nomme pas {capacite} : un angle mort qu'on ne nomme "
            "pas se lit comme une couverture")


def test_la_quarantaine_installe_REELLEMENT_et_verifie_la_coherence():
    """Une PR verte qui n'a rien installe ne prouve rien. Et `pip check` est le
    seul controle qui voie les incompatibilites ENTRE paquets."""
    brut = QUARANTAINE.read_text(encoding="utf-8", errors="replace")
    assert "pip install" in brut, "aucune installation reelle"
    assert "pip check" in brut, "coherence des dependances non verifiee"
    assert "--no-cache-dir" in brut, (
        "sans --no-cache-dir, un cache peut servir une version deja vue et "
        "masquer ce que l'index sert reellement")
    assert "denominateur vide" in brut, (
        "un run qui n'installe AUCUN manifeste doit echouer, pas passer")
