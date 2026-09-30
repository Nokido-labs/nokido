"""
tests/nr/test_tuile_orpheline_nr.py - Gate « zero tuile orpheline » (niveau contract).

Doctrine GUI live-only (owner 2026-08-21) : une tuile du hub n'a que des etats
MESURES (up / down / soon / unknown) et une cible REELLE - jamais un mode demo silencieux.
Le catalogue live (/api/hub/modules, ce que le navigateur recoit) et la
declaration (SERVICES) doivent etre la MEME surface : une divergence est une
regression capacitive - backend disparu sous une tuile encore visible, ou
tuile fantome sans declaration.

Coverage :
  - bijection SERVICES <-> catalogue live (zero orpheline, zero fantome)
  - statut borne a {up, down, soon, unknown}   (borne a TROIS valeurs REVOQUEE
    le 2026-09-17, autorisation owner : elle n'avait pas de place pour « la
    sonde n'a pas pu etablir l'etat » et forcait donc a choisir entre sain et
    mort. 12 tuiles sur 18 tombaient du cote sain sans aucune mesure.) - jamais un etat simule
  - schema de tuile complet (slug/title/desc/icon/href/external/status)
  - chaque tuile interne pointe une route ou un mount FastAPI reel
  - anti-demo statique : aucun motif de donnees simulees dans app/web_hub

UN echec bloque : pas de seuil, pas de « 95 % des tuiles ».
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# -------------------------------------------------------------------
# Fixtures - meme contrat que tests/nr/test_hub_auth.py : le coffre rend,
# pendant le test, ce que l'environnement du test pose (garde de portee) ;
# sinon le test mesure le secret de production, pas le code.
# -------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _coffre_suit_l_environnement(monkeypatch):
    import os as _os

    try:
        import forge_secrets
    except Exception:  # noqa: BLE001 - muet-ok : coffre absent, l'env fait foi
        return
    monkeypatch.setattr(forge_secrets, "get_secret",
                        lambda nom, *a, **kw: _os.environ.get(nom) or None,
                        raising=False)


@pytest.fixture
def admin_token():
    return "tuile-orpheline-token-42"


@pytest.fixture
def client(monkeypatch, admin_token):
    monkeypatch.setenv("LAFORGE_ADMIN_TOKEN", admin_token)
    # Full reimport (pattern test_hub_auth) : AUTH_CFG est cree a l'import du
    # module ; en suite complete l'app est deja chargee avec le token d'un
    # AUTRE test -> login 401. Le reimport recree la config sur CET env.
    for mod in list(sys.modules):
        if mod.startswith("app.web_hub"):
            del sys.modules[mod]
    from fastapi.testclient import TestClient

    from app.web_hub.app import app
    from app.web_hub.auth import login_rate_limiter
    login_rate_limiter._by_ip.clear()  # noqa: SLF001
    c = TestClient(app)
    r = c.post("/auth/login", data={"admin_token": admin_token},
               headers={"Accept": "application/json"})
    assert r.status_code in (200, 303), f"login TestClient impossible : {r.status_code}"
    return c


def _routes_reelles() -> set[str]:
    from app.web_hub.app import app
    paths = set()
    for r in app.routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
    return paths


def _catalogue(client) -> list[dict]:
    r = client.get("/api/hub/modules")
    assert r.status_code == 200, f"/api/hub/modules rend {r.status_code}"
    data = r.json()
    assert isinstance(data, list) and data, "catalogue de tuiles vide"
    return data


# -------------------------------------------------------------------
# Surface unique : le live et le declare sont le MEME ensemble
# -------------------------------------------------------------------
class TestSurfaceUnique:
    def test_aucune_tuile_fantome(self, client):
        """Une tuile servie au navigateur sans declaration SERVICES = fantome."""
        from app.web_hub.app import SERVICES
        live = {m["slug"] for m in _catalogue(client)}
        fantomes = live - set(SERVICES)
        assert not fantomes, f"tuiles live sans declaration : {sorted(fantomes)}"

    def test_aucune_tuile_orpheline(self, client):
        """Une declaration SERVICES absente du catalogue live = la GUI a perdu
        une capacite sans que rien ne le dise."""
        from app.web_hub.app import SERVICES
        live = {m["slug"] for m in _catalogue(client)}
        orphelines = set(SERVICES) - live
        assert not orphelines, f"declarations sans tuile live : {sorted(orphelines)}"


# -------------------------------------------------------------------
# Etats honnetes : mesures, jamais simules
# -------------------------------------------------------------------
class TestEtatsHonnetes:
    def test_statut_borne(self, client):
        for m in _catalogue(client):
            assert m["status"] in {"up", "down", "soon", "unknown"}, (
                f"tuile '{m['slug']}' : statut '{m['status']}' hors contrat "
                "(up/down/soon/unknown - un etat invente est un mode demo)")

    def test_schema_complet(self, client):
        champs = {"slug", "title", "desc", "icon", "href", "external", "status"}
        for m in _catalogue(client):
            manquants = champs - set(m)
            assert not manquants, f"tuile '{m.get('slug')}' : champs absents {sorted(manquants)}"


# -------------------------------------------------------------------
# Enveloppe tracable (doctrine §6) : chaque tuile porte un etat MESURE
# et sa provenance - detecte le « dashboard decoratif ».
# -------------------------------------------------------------------
# `unknown` ajoute le 2026-09-17. Le set borne les valeurs ADMISSIBLES ; il ne
# promet pas que chacune vienne d'une sonde aboutie. `unknown` est justement
# celle qui dit le contraire -- et elle se represente par elle-meme cote front,
# jamais par un repli sur up / down / soon.
ETATS_MESURES = {"live", "degraded", "offline", "error", "soon", "unknown"}
COHERENCE = {"live": "up", "degraded": "up", "offline": "down",
             "error": "down", "soon": "soon", "unknown": "unknown"}


class TestEnveloppeTracable:
    def test_state_borne_et_trace(self, client):
        for m in _catalogue(client):
            assert m.get("state") in ETATS_MESURES, (
                f"tuile '{m['slug']}' : state {m.get('state')!r} hors contrat")
            assert "checked" in m and isinstance(m["checked"], bool), (
                f"tuile '{m['slug']}' : 'checked' absent - on ne sait pas si "
                "l'etat est MESURE ou presume")
            assert "probe_ms" in m, f"tuile '{m['slug']}' : probe_ms absent"
            assert m.get("via") in ("http", "tcp", None), (
                f"tuile '{m['slug']}' : via {m.get('via')!r} hors contrat - "
                "on doit savoir COMMENT l'etat a ete mesure")
            assert isinstance(m.get("ts"), (int, float)), (
                f"tuile '{m['slug']}' : ts absent - donnee non datee")

    def test_status_legacy_coherent(self, client):
        """Le champ legacy (up/down/soon, consomme par le front actuel) doit
        deriver du state mesure - jamais une 2e verite."""
        for m in _catalogue(client):
            attendu = COHERENCE[m["state"]]
            assert m["status"] == attendu, (
                f"tuile '{m['slug']}' : status={m['status']} incoherent avec "
                f"state={m['state']} (attendu {attendu})")


# -------------------------------------------------------------------
# Cibles reelles : chaque tuile interne est servie par une route/mount
# -------------------------------------------------------------------
class TestCiblesReelles:
    def test_tuile_interne_a_une_route(self, client):
        routes = _routes_reelles()
        for m in _catalogue(client):
            # `soon` est un etat DECLARE (ex. recon sans _RT_INSTALLED) : pas de
            # route par definition, et la tuile le DIT - pas un mode demo.
            if m["external"] or m["status"] == "soon":
                continue
            href = (m["href"] or "").rstrip("/") or "/"
            servie = href == "/" or any(
                p == href
                or p.rstrip("/") == href
                or p.startswith(href + "/")
                for p in routes)
            assert servie, (
                f"tuile interne '{m['slug']}' href={m['href']!r} : aucune route "
                "ni mount FastAPI ne la sert - tuile decorative")


# -------------------------------------------------------------------
# Anti-demo statique : pas de donnees inventees dans le chemin prod UI
# -------------------------------------------------------------------
MOTIFS_DEMO = re.compile(
    r"\b(demoData|fakeData|sampleData|mockData|placeholderData|fallbackData|staticData)\b")


class TestAntiDemo:
    def test_aucune_donnee_simulee_dans_web_hub(self):
        base = ROOT / "app" / "web_hub"
        coupables = []
        for f in base.rglob("*"):
            if (f.suffix.lower() not in {".html", ".js", ".py"}
                    or "__pycache__" in f.parts or f.name.endswith(".bak")):
                continue
            try:
                txt = f.read_text(encoding="utf-8", errors="replace")
            except OSError:  # muet-ok : fichier illisible = hors surface scannee
                continue
            for m in MOTIFS_DEMO.finditer(txt):
                coupables.append(f"{f.relative_to(ROOT)} :: {m.group(0)}")
        assert not coupables, (
            "donnees simulees dans le chemin prod UI :\n" + "\n".join(coupables))
