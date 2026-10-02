# -*- coding: utf-8 -*-
"""NR -- un SECRET de Nokido.env se lit au COFFRE, jamais dans le fichier (owner 2026-10-01).

« Le .env ne doit servir qu'a charger de nouveaux secrets sans les taper » : il fait ENTRER un
secret au coffre (tools/forge_env_to_vault.py). Douze chargeurs recopiaient le fichier, en clair,
dans os.environ. Primitive unique : forge_secrets.injecter_env_depuis_coffre -- NOMS du fichier,
VALEURS du coffre pour un secret ; un REGLAGE garde sa valeur du fichier (forge_env_sync y en
ecrit par conception). Cliquet : aucune NOUVELLE boucle qui recopie un .env dans os.environ.
Aucune vraie valeur n'est lue ici : le coffre est simule.
"""
import ast
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Sites encore autorises, avec leur raison. Le socle ne peut que DESCENDRE.
SOCLE = {
    "app/brain_worker.py": "lit deux REGLAGES nommes (LAFORGE_IDLE_*), aucun secret",
}


@pytest.fixture
def fs(monkeypatch):
    m = importlib.import_module("nokido_agent.app.forge_secrets")
    coffre = {("coffre", "NR_API_KEY"): ("valeur-coffre", False),
              ("wcm", "NR_SECRET_ILL"): (None, True)}
    monkeypatch.setattr(m, "_sonder", lambda source, k: coffre.get((source, k), (None, False)))
    return m


def _env(tmp_path, texte):
    p = tmp_path / "Nokido.env"
    p.write_text(texte, encoding="utf-8")
    return p


def test_secret_au_coffre_reglage_du_fichier_absent_jamais_servi(fs, tmp_path):
    p = _env(tmp_path, "NR_API_KEY=valeur-fichier\nNR_TOKEN_ABSENT=valeur-fichier-2\n"
                       "NR_SECRET_ILL=valeur-fichier-3\nNR_REGLAGE_URL=http://x:1  # commentaire\n"
                       "# NR_COMMENTE_KEY=valeur-commentee\nNR_DEJA_KEY=valeur-fichier-4\n")
    env = {"NR_DEJA_KEY": "deja"}
    b = fs.injecter_env_depuis_coffre(p, environ=env)
    assert env["NR_API_KEY"] == "valeur-coffre", "un secret vient du COFFRE, jamais du fichier"
    assert "NR_TOKEN_ABSENT" not in env and b["absentes"] == ["NR_TOKEN_ABSENT"]
    assert "NR_SECRET_ILL" not in env and b["illisibles"] == ["NR_SECRET_ILL"]
    assert env["NR_REGLAGE_URL"] == "http://x:1", "un reglage garde sa valeur du fichier"
    assert env["NR_DEJA_KEY"] == "deja" and "NR_COMMENTE_KEY" not in env
    assert (b["injectees"], b["reglages"], b["deja_posees"]) == (1, 1, 1)
    assert "valeur" not in json.dumps(b), "le bilan rend des NOMS, jamais une valeur"


def test_un_fichier_absent_est_dit(fs, tmp_path):
    b = fs.injecter_env_depuis_coffre(tmp_path / "absent.env", environ={})
    assert b.get("fichier_illisible") is True and b["injectees"] == 0


def _boucles_env_vers_environ(f: Path) -> list:
    arbre = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
    if not any(isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value.endswith(".env")
               for c in ast.walk(arbre)):
        return []
    handles = {it.optional_vars.id for w in ast.walk(arbre) if isinstance(w, ast.With)
               for it in w.items if isinstance(it.optional_vars, ast.Name)
               and "open(" in ast.unparse(it.context_expr)}

    def ecrit(n):
        for e in ast.walk(n):
            if isinstance(e, ast.Assign) and any(isinstance(t, ast.Subscript) and "environ" in ast.unparse(t.value)
                                                 for t in e.targets):
                return True
            if isinstance(e, ast.Call) and isinstance(e.func, ast.Attribute) \
                    and e.func.attr in ("setdefault", "update") and "environ" in ast.unparse(e.func.value):
                return True
        return False
    return [b.lineno for b in ast.walk(arbre) if isinstance(b, ast.For)
            and ("splitlines" in ast.unparse(b.iter) or (isinstance(b.iter, ast.Name) and b.iter.id in handles))
            and ecrit(b)]


def test_aucune_nouvelle_boucle_qui_recopie_un_env_dans_l_environnement():
    trouves = set()
    for d in ("app", "tools"):
        for f in sorted((ROOT / d).glob("*.py")):
            if not f.name.startswith("tmp_") and _boucles_env_vers_environ(f):
                trouves.add("%s/%s" % (d, f.name))
    assert not trouves - set(SOCLE), (
        "NOUVEAU chargeur qui recopie un .env dans os.environ : %s -- passer par "
        "forge_secrets.injecter_env_depuis_coffre" % sorted(trouves - set(SOCLE)))
    assert not set(SOCLE) - trouves, (
        "site corrige mais encore au socle : %s -- le retirer de SOCLE" % sorted(set(SOCLE) - trouves))


def test_l_enrobage_des_chargeurs_dit_l_echec_sans_tomber(monkeypatch, capsys, tmp_path):
    """injecter_env_ou_dire (2026-10-02) : enrobage UNIQUE des chargeurs de demarrage. Une injection
    qui leve se DIT (qui, type d'erreur) et rend None ; le processus ne tombe pas."""
    fs = importlib.import_module("forge_secrets")

    def _leve(*a, **k):
        raise PermissionError("refuse")

    monkeypatch.setattr(fs, "injecter_env_depuis_coffre", _leve)
    assert fs.injecter_env_ou_dire(tmp_path / "Nokido.env", "launcher") is None
    sortie = capsys.readouterr().out
    assert "[launcher] coffre indisponible (PermissionError)" in sortie, sortie
    assert "refuse" not in sortie, "le message de l'exception n'est pas recopie (jamais une valeur)"
