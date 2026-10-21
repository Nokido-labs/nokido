# -*- coding: utf-8 -*-
"""NR — CLIQUET : aucun nouvel ecrivain de pouls hors du chemin canonique.

`forge_heartbeat.beat_daemon` est le chemin UNIQUE d'ecriture d'un pouls. Le
recensement du 2026-07-28 avait trouve 39 reimplementations maison ; la migration du
2026-09-05 en a repris 20, et ce cliquet interdit a la dette de remonter.

POURQUOI CE CLIQUET EXISTE — la mesure, pas le principe. Une ecriture maison
n'inscrit pas le `pid` : le pouls atteste alors d'une vie sans dire QUI la porte.
Consequence mesuree le 2026-09-05 : 24 pouls sur 49 sans pid, donc la moitie de la
flotte sans hote attribuable, donc `forge_nervous_map.autorites()` incapable de dire
sous quelle autorite vit l'organe. Certaines de ces ecritures ne produisaient meme pas
du JSON (`organ_afferent` ecrivait `str(time.time())`, `harness_worker` une date ISO
nue) alors que `proxy_deno/core/service_loader.ts` declare un fichier JSON : elles
etaient donc ILLISIBLES au contrat.

CE QUE CE TEST NE MESURE PAS, ET POURQUOI. `tools/forge_signal_graph` compte
`beat_daemon` parmi ses `WRITE_HELPERS` : il repond « qui ecrit un pouls », pas « qui
l'ecrit A LA MAIN ». Utilise tel quel comme cliquet, il rendait 51 avant ET apres la
migration de vingt modules — un compteur insensible a ce qu'il est cense mesurer. Le
detecteur ci-dessous cherche donc l'ecriture BRUTE : un nom lie a un litteral
`*.heartbeat` qui recoit `write_text` / `write_bytes` / `touch`, ou qui part dans un
`open(..., "w")`.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git ls-files (l.59)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

CANON = "app/forge_heartbeat.py"
METHODES_ECRITURE = {"write_text", "write_bytes", "touch"}

# CLIQUET. Il ne peut que DESCENDRE a portee de detecteur CONSTANTE. Le baisser en
# meme temps qu'on migre fait partie du travail ; le remonter demande de justifier
# pourquoi un organe doit reimplementer un geste que le corps tient a un seul endroit.
#
# HISTORIQUE, parce qu'un chiffre qui bouge doit dire POURQUOI :
#   43  mesure initiale (2026-09-05, avant migration)
#   23  apres migration de 20 ecrivains vers `beat_daemon`
#   25  MEME JOUR, sans qu'aucune dette ne revienne : le detecteur a gagne la
#       detection des noms CONSTRUITS (f-strings), qui lui echappaient entierement.
#       `nokido_hub` et `forge_peer_discovery` etaient donc deja la, invisibles.
#       Une mesure qui s'elargit n'est PAS une dette qui monte — mais taire la
#       difference reviendrait a maquiller l'un en l'autre.
PLAFOND_ECRIVAINS_BRUTS = 25


def _fichiers_suivis() -> list[str]:
    """Frontiere = ce que git SUIT. `os.walk` ramasse des copies et des datasets."""
    out = subprocess.run(
        ["git", "-c", "safe.directory=*", "-C", str(ROOT), "ls-files", "--",
         "app/*.py", "tools/*.py"],
        capture_output=True, text=True, errors="replace", timeout=120)
    if out.returncode != 0:
        pytest.skip("git ls-files indisponible : perimetre NON etabli, "
                    "un cliquet sur une frontiere inconnue ne prouve rien")
    return [l.strip() for l in out.stdout.splitlines() if l.strip()]


def _ecriture_brute(rel: str):
    """Lignes d'ecriture MANUELLE d'un pouls. `None` = fichier ILLISIBLE.

    Trois etats, jamais deux : un fichier qu'on n'a pas pu analyser n'est pas un
    fichier sans dette — sinon la couverture est surestimee en silence.
    """
    try:
        arbre = ast.parse((ROOT / rel).read_text("utf-8", "ignore"))
    except Exception:  # noqa: BLE001
        return None
    pouls = set()
    nom_construit = False
    # FAUX POSITIF FERME LE 2026-10-14. `nom_construit` vaut pour tout le module : `tools/session_anchor.py`
    # LIT les pouls des daemons via `f"{name}.heartbeat"` et ecrit son ancre de cadence
    # `ANCRE = ROOT / "sandbox" / "session_anchor.dernier"` -- ce `ANCRE.write_text` etait compte comme
    # un pouls brut (26 pour un plafond de 25). Un nom dont TOUTES les affectations nomment explicitement
    # un AUTRE fichier (litteral a extension, ni `.heartbeat` ni f-string) n'est pas un pouls. Un nom issu
    # d'un appel (le cas `forge_task_executor` ci-dessous) n'en nomme aucun : il reste couvert.
    autre_fichier: dict = {}
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign) and n.targets:
            if ".heartbeat" in ast.unparse(n.value):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        pouls.add(t.id)
            nomme_autre = (not any(isinstance(c, ast.JoinedStr) for c in ast.walk(n.value))
                           and ".heartbeat" not in ast.unparse(n.value)
                           and any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                                   and "." in c.value.replace("\\", "/").rsplit("/", 1)[-1]
                                   for c in ast.walk(n.value)))
            for t in n.targets:
                if isinstance(t, ast.Name):
                    autre_fichier[t.id] = autre_fichier.get(t.id, True) and nomme_autre
        # ANGLE MORT FERME LE 2026-09-05. `forge_task_executor` ecrivait TROIS pouls
        # (`task_executor`, `_worker_code`, `_antigravity`) via
        # `SANDBOX / f"task_executor_{slug}.heartbeat"`, puis `_hb.write_text(...)` ou
        # `_hb` vient d'un APPEL et non d'un litteral : le detecteur ne voyait rien,
        # et ces trois organes echappaient au cliquet comme ils echappaient a l'atlas.
        # Un nom construit a l'execution reste un nom de pouls.
        if isinstance(n, ast.JoinedStr) and ".heartbeat" in ast.unparse(n):
            nom_construit = True
    if not pouls and not nom_construit:
        return []
    sites = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr in METHODES_ECRITURE:
            base = f.value
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name) and (base.id in pouls
                                               or (nom_construit and not autre_fichier.get(base.id))):
                sites.append(n.lineno)
        elif isinstance(f, ast.Name) and f.id == "open" and n.args:
            a0 = n.args[0]
            if isinstance(a0, ast.Name) and a0.id in pouls:
                mode = ast.unparse(n.args[1]) if len(n.args) > 1 else ""
                if "w" in mode or "a" in mode:
                    sites.append(n.lineno)
    # FAUX POSITIF FERME LE 2026-10-17 (meme famille que le 14/10, meme etroitesse). `autre_fichier` est collant a
    # l'echelle du MODULE : dans `forge_task_executor`, `job = Path(job)` (attente du harness) et
    # `chemin = Path(env_cfg)` suffisaient a rendre suspects TOUS les `job.write_text` (jobs JSON du harness Codex et
    # Vibe) et `chemin.write_text` (config MCP de Vibe) -- 26 pour un plafond de 25, sans un seul pouls ecrit.
    # Exception LOCALE : un site est ecarte seulement si, DANS LA FONCTION qui le contient, TOUTES les affectations
    # du nom nomment explicitement un autre fichier. Ne fait que RETIRER des sites ; contre-epreuve sur tout le depot
    # suivi : seul forge_task_executor sort, aucun site retire dans les 25 autres (nokido_hub:1350, vrai pouls, reste).
    ecartes = set()
    for fn in (x for x in ast.walk(arbre) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))):
        affect: dict = {}
        for x in ast.walk(fn):
            if isinstance(x, ast.Assign):
                for t in x.targets:
                    if isinstance(t, ast.Name):
                        affect.setdefault(t.id, []).append(x.value)
        for x in ast.walk(fn):
            if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.lineno in sites:
                base = x.func.value
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name) and affect.get(base.id) and all(
                        _nomme_un_autre_fichier(v) for v in affect[base.id]):
                    ecartes.add(x.lineno)
    return sorted(set(sites) - ecartes)


def _nomme_un_autre_fichier(v) -> bool:
    """La valeur affectee nomme explicitement un AUTRE fichier : litteral a extension, ni `.heartbeat` ni f-string."""
    return (not any(isinstance(c, ast.JoinedStr) for c in ast.walk(v)) and ".heartbeat" not in ast.unparse(v)
            and any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and "." in c.value.replace("\\", "/").rsplit("/", 1)[-1] for c in ast.walk(v)))


def test_un_job_json_dans_sa_fonction_n_est_pas_un_pouls_mais_un_vrai_pouls_reste_compte(tmp_path, monkeypatch):
    """NR du correctif du 17/10, dans les DEUX sens : l'exception locale ne masque jamais un vrai pouls."""
    src = (
        "from pathlib import Path\n"
        "def _hb_file(a):\n"
        "    return Path('sandbox') / f'task_executor_{a}.heartbeat'\n"
        "def attendre(job):\n"
        "    job = Path(job)\n"
        "    return job.exists()\n"
        "def deleguer(jid):\n"
        "    job = Path('jobs') / (jid + '.json')\n"
        "    job.write_text('{}')\n"
        "def battre(a):\n"
        "    hb = _hb_file(a)\n"
        "    hb.write_text('{}')\n"
    )
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "faux_module.py").write_text(src, encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    sites = _ecriture_brute("tools/faux_module.py")
    assert 9 not in sites, "le job JSON du harness est compte comme un pouls"
    assert 12 in sites, "le vrai pouls brut (hb.write_text) n'est plus compte : faux negatif"


def _recensement() -> tuple[dict, list]:
    bruts, illisibles = {}, []
    for rel in _fichiers_suivis():
        if rel == CANON:
            continue
        sites = _ecriture_brute(rel)
        if sites is None:
            illisibles.append(rel)
        elif sites:
            bruts[rel] = sites
    return bruts, illisibles


def test_cliquet_ecrivains_de_pouls_hors_canon():
    bruts, illisibles = _recensement()
    assert not illisibles, (
        "%d fichier(s) ILLISIBLE(S) : la dette est SOUS-estimee, le cliquet ne "
        "prouve rien -> %s" % (len(illisibles), illisibles[:5]))
    assert len(bruts) <= PLAFOND_ECRIVAINS_BRUTS, (
        "la dette de pouls REMONTE : %d ecrivains bruts pour un plafond de %d. "
        "Un pouls s'ecrit par `forge_heartbeat.beat_daemon`, seul chemin qui inscrit "
        "le pid — sans lui l'organe bat sans porteur attribuable.\nNouveaux : %s"
        % (len(bruts), PLAFOND_ECRIVAINS_BRUTS, sorted(bruts)))


def test_cliquet_est_serre_sur_la_mesure():
    """Un cliquet trop lache ne cliquette pas : il doit coller a la mesure.

    Sans ce test, on pourrait migrer dix modules sans jamais descendre le plafond, et
    le garde laisserait revenir dix dettes sans rien dire.
    """
    bruts, _ = _recensement()
    assert len(bruts) >= PLAFOND_ECRIVAINS_BRUTS - 2, (
        "le plafond (%d) est LARGE de %d par rapport a la mesure (%d) : le descendre, "
        "sinon la dette peut revenir sans declencher le garde"
        % (PLAFOND_ECRIVAINS_BRUTS, PLAFOND_ECRIVAINS_BRUTS - len(bruts), len(bruts)))


def test_le_detecteur_distingue_une_ancre_d_un_pouls_construit(tmp_path):
    # Faux positif du 2026-10-14 : une ancre nommee en clair n'est pas un pouls, meme dans un module qui
    # construit des noms de pouls. L'angle mort du 2026-09-05 (pouls issu d'un APPEL) reste ferme.
    module = tmp_path / "module_temoin.py"
    module.write_text(
        "from pathlib import Path\n"
        "ROOT = Path('.')\n"
        "ANCRE = ROOT / 'sandbox' / 'session_anchor.dernier'\n"
        "def lit(name):\n"
        "    return (ROOT / 'sandbox' / f'{name}.heartbeat').exists()\n"
        "def ancre():\n"
        "    ANCRE.write_text('1', encoding='utf-8')\n"
        "def pouls(slug):\n"
        "    _hb = _chemin(slug)\n"
        "    _hb.write_text('{}', encoding='utf-8')\n", encoding="utf-8")
    assert _ecriture_brute(str(module)) == [10]


def test_beat_daemon_inscrit_pid_et_horodatage(tmp_path, monkeypatch):
    """Le contrat du canon : `pid` + `ts`, et la charge de l'appelant preservee.

    `_ROOT` est deplace vers un dossier temporaire, et la sonde de couplage est
    neutralisee : ce test ne doit ni fabriquer un organe dans `sandbox/` — le
    diagnostic enumere ce dossier et y verrait un organe vivant — ni polluer le
    registre des signaux.
    """
    import forge_heartbeat as fh
    import forge_signal_coupling as fsc

    monkeypatch.setattr(fh, "_ROOT", tmp_path)
    monkeypatch.setattr(fsc, "emit_signal", lambda *a, **k: True)

    assert fh.beat_daemon("organe_de_test", note="essai", n=3) is True
    ecrit = tmp_path / "sandbox" / "organe_de_test.heartbeat"
    assert ecrit.exists(), "le pouls n'a pas ete ecrit sous la racine deplacee"
    charge = __import__("json").loads(ecrit.read_text(encoding="utf-8"))
    assert charge.get("pid"), "pas de pid : c'est precisement ce qui rend un organe " \
                              "inattribuable"
    assert charge.get("ts"), "pas d'horodatage"
    assert charge.get("note") == "essai" and charge.get("n") == 3, \
        "la charge de l'appelant doit survivre a la centralisation"


def test_beat_daemon_ne_leve_jamais(tmp_path, monkeypatch):
    """Invariant : echec de la sonde != echec du heartbeat, et jamais d'exception.

    Une charge non serialisable passait chez plusieurs implementations maison grace a
    `default=str` ; le canon doit accepter ce que les variantes acceptaient, sinon
    centraliser DEGRADE.
    """
    import forge_heartbeat as fh
    import forge_signal_coupling as fsc

    monkeypatch.setattr(fh, "_ROOT", tmp_path)

    def _sonde_qui_casse(*a, **k):
        raise RuntimeError("registre de couplage indisponible")

    monkeypatch.setattr(fsc, "emit_signal", _sonde_qui_casse)

    class Opaque:
        def __repr__(self):
            return "<opaque>"

    assert fh.beat_daemon("organe_de_test", objet=Opaque()) is True, \
        "une sonde qui casse ne doit PAS faire echouer le pouls"
    ecrit = tmp_path / "sandbox" / "organe_de_test.heartbeat"
    assert "<opaque>" in ecrit.read_text(encoding="utf-8")
