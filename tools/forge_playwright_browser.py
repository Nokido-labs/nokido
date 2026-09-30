"""
forge_playwright_browser.py — Browser headed isolé + Oracle UI pour Nokido.

Infra NEUTRE (dual-use) : wrapper navigateur async + "lunettes" UI (a11y +
set-of-mark) consommées par le gate d'acceptation UI (tools/forge_ui_campaign.py,
tools/forge_ui_oracle.py) et par les agents. Le sous-système offensif/CTF qui
l'utilisait aussi vit désormais dans le dépôt séparé `nokido-security-lab`.

Pile : Playwright Firefox bundled + profil persistent dédié.
- Profil : C:/nokido/browser-profiles/nokido-ui/ (cookies, login, history persistent)
- Cache binaires : C:/nokido/ms-playwright/

REGLE : jamais toucher au Firefox principal user.
Voir memory/feedback_firefox_main_isolated.md
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "C:/nokido/ms-playwright")

PROFILE_DIR = Path(os.environ.get("NOKIDO_UI_BROWSER_PROFILE", "C:/nokido/browser-profiles/nokido-ui"))
DEFAULT_HEADED = os.environ.get("NOKIDO_UI_BROWSER_HEADED", "1") == "1"

# Selecteur UNIQUE de « ce avec quoi on peut interagir ». Partage par la liste des
# elements visibles (set-of-mark) et par le comptage sur tout le document : deux
# selecteurs qui divergent produisent un instrument qui se contredit lui-meme.
SEL_INTERACTIF = (
    "a[href],button,input,select,textarea,summary,"
    "[role=button],[role=link],[role=checkbox],[role=tab],[role=menuitem],"
    '[role=switch],[onclick],[contenteditable=true],[tabindex]:not([tabindex="-1"])'
)


# --- Choix du moteur -------------------------------------------------------
# DEFAUT PAYE (gate `ui-acceptance` UNKNOWN depuis le 2026-09-11). Ce lanceur
# ouvrait `firefox.launch_persistent_context` EN DUR. Sous un compte sans session
# graphique, ce firefox se lance puis GELE (`RenderCompositorSWGL failed mapping
# default framebuffer`) : l'appel pend 180 s, puis rend un timeout qui ne nomme
# ni le moteur, ni le magasin, ni la cause. Le gate ne pouvait donc pas
# distinguer « pas de navigateur » de « pas de service ».
#
# ANTI-DUP : la politique portee ici est celle que `tools/forge_ui_contrat_etats.py`
# a deja MESUREE le 2026-09-11 (canal systeme + `launch` NU + borne de temps). On
# ne fonde pas une seconde politique -- on la met a l'endroit que les trois
# consommateurs partagent (ui_campaign, ui_nervous_census, ui_contrat_etats).
#
# REGLE OWNER (memory/feedback_firefox_main_isolated.md) : un canal SYSTEME
# n'emprunte que le BINAIRE. `launch` NU ne touche AUCUN profil de l'utilisateur
# -- Playwright fabrique un repertoire jetable -- et n'installe aucune extension.
# Ce que la regle interdit, c'est le profil principal et les extensions.

MOTEURS_CONNUS = ("chromium", "firefox", "webkit")

# (cle acceptee, moteur playwright, canal, origine). L'ordre EST l'ordre de
# preference quand rien n'est demande : le magasin d'abord, parce qu'il ne
# depend d'aucun binaire tiers installe par ailleurs.
CATALOGUE_LANCEMENT = (
    ("chromium", "chromium", None, "magasin"),
    ("chrome", "chromium", "chrome", "systeme"),
    ("msedge", "chromium", "msedge", "systeme"),
    ("firefox", "firefox", None, "magasin"),
    ("webkit", "webkit", None, "magasin"),
)

# firefox reste ELIGIBLE sur demande explicite, mais n'est jamais ELU par
# defaut : la mesure du 2026-09-11 dit qu'il gele SANS session graphique, pas
# qu'il est mort partout. On refuse de l'elire, on ne l'interdit pas.
_JAMAIS_ELU_PAR_DEFAUT = frozenset({"firefox"})

MAGASIN = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "C:/nokido/ms-playwright"))

# Borne alignee sur celle du module frere. Ce qui est interdit, c'est le defaut
# implicite de Playwright (180 s), pas telle ou telle valeur.
LANCEMENT_TIMEOUT_MS = int(os.environ.get("NOKIDO_UI_BROWSER_TIMEOUT_MS", "25000"))


def inventaire_magasin(racine) -> tuple:
    """Rend (moteurs presents, etat) avec etat dans LU | ABSENT | ILLISIBLE.

    Trois etats, jamais deux : un capteur qui rend la meme chose pour « pas la »
    et pour « acces refuse » fabrique des faux negatifs indetectables.
    """
    racine = Path(racine)
    try:
        entrees = list(racine.iterdir())
    except FileNotFoundError:
        return set(), "ABSENT"
    except OSError:
        # PermissionError compris : le magasin EXISTE peut-etre, on ne sait pas.
        return set(), "ILLISIBLE"
    presents = set()
    for entree in entrees:
        # `chromium-1208` -> chromium ; `chromium_headless_shell-1208` reste
        # entier et sort du lot : ce n'est PAS un chromium complet.
        tete = entree.name.rsplit("-", 1)[0]
        if tete in MOTEURS_CONNUS:
            presents.add(tete)
    return presents, "LU"


def candidats_lancement(demande, presents, etat_magasin):
    """Rend la LISTE ordonnee des (moteur, canal, origine, motif) a essayer.

    Une liste, pas un choix unique -- mesure du 2026-09-14 qui a impose cette
    forme : la presence d'un moteur dans le magasin NE PROUVE PAS qu'il se lance.
    `playwright install chromium` (CLI de la lib 1.58.0) a depose `chromium-1208`
    pendant que l'API de la MEME lib reclamait `chromium-1228` -- deux artefacts
    sous un seul nom (Chrome for Testing vs Chromium natif). Un selecteur qui
    elit un seul candidat sur la foi du magasin se trompait donc a coup sur ici,
    et se tromperait a l'inverse sur un runner ou le bundled est le seul present.
    Seul le lancement tranche : on ordonne les essais, chacun borne.

    Une demande EXPLICITE ne rend qu'un candidat : on ne replie jamais en
    silence sur autre chose que ce qui a ete demande -- sinon on mesure un autre
    navigateur que celui dont on parle.
    """
    catalogue = {cle: (m, c, o) for cle, m, c, o in CATALOGUE_LANCEMENT}

    if demande:
        cle = str(demande).strip().lower()
        if cle not in catalogue:
            raise ValueError(
                "moteur de navigateur inconnu : %r. Valeurs acceptees : %s"
                % (demande, ", ".join(catalogue))
            )
        moteur, canal, origine = catalogue[cle]
        if origine == "systeme":
            return [(moteur, canal, origine, "DEMANDE (%s, canal systeme)" % cle)]
        if etat_magasin != "LU":
            # UNKNOWN != NO : on ne declare pas l'absence, on tente en le disant.
            return [(moteur, canal, origine, (
                "DEMANDE (%s) -- magasin %s, disponibilite non verifiable, "
                "lancement tente" % (cle, etat_magasin)
            ))]
        if moteur not in presents:
            raise ValueError(
                "moteur %r demande mais absent du magasin Playwright (%s) -- "
                "presents : %s. Installer : playwright install %s"
                % (cle, MAGASIN, sorted(presents) or "aucun", moteur)
            )
        return [(moteur, canal, origine, "DEMANDE (%s, magasin)" % cle)]

    candidats = []
    for cle, moteur, canal, origine in CATALOGUE_LANCEMENT:
        if cle in _JAMAIS_ELU_PAR_DEFAUT:
            continue
        if origine == "magasin":
            if etat_magasin == "LU" and moteur in presents:
                candidats.append(
                    (moteur, canal, origine, "DEFAUT (%s du magasin)" % cle)
                )
            elif etat_magasin != "LU":
                # Magasin illisible : on ne l'ecarte pas, on le classe apres les
                # canaux systeme, qui eux ne dependent pas de sa lisibilite.
                candidats.append((moteur, canal, origine, (
                    "TENTE (%s) -- magasin %s, disponibilite non verifiable"
                    % (cle, etat_magasin)
                )))
            continue
        detail = "LU sans moteur utilisable" if etat_magasin == "LU" else etat_magasin
        candidats.append((moteur, canal, origine, (
            "REPLI (%s, canal systeme) -- magasin %s" % (cle, detail)
        )))

    # Les canaux systeme d'abord quand le magasin n'est pas lisible : un essai
    # qui pend coute le budget entier, on commence par ce qui ne depend de rien.
    if etat_magasin != "LU":
        candidats.sort(key=lambda c: 0 if c[2] == "systeme" else 1)

    if not candidats:
        raise ValueError(
            "aucun moteur de navigateur disponible -- magasin %s (%s), presents : %s"
            % (MAGASIN, etat_magasin, sorted(presents) or "aucun")
        )
    return candidats


def choisir_lancement(demande, presents, etat_magasin):
    """Premier candidat de `candidats_lancement` -- meme logique, une seule source."""
    return candidats_lancement(demande, presents, etat_magasin)[0]


class PlaywrightBrowser:
    """Wrapper async Playwright Firefox persistent isolé.

    Usage:
        async with PlaywrightBrowser() as br:
            await br.goto("http://127.0.0.1:7400/")
            png = await br.screenshot("out.png")
            txt = await br.dom_text()
    """

    def __init__(self, headed: bool = DEFAULT_HEADED, profile_dir: Path = PROFILE_DIR):
        self.headed = headed
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = None
        self._nav = None
        self._ctx = None
        self._page = None
        # Rempli par __aenter__ : de quoi AUDITER apres coup quel moteur a servi.
        self.lancement = {}

    async def __aenter__(self):
        from playwright.async_api import async_playwright

        presents, etat = inventaire_magasin(MAGASIN)
        candidats = candidats_lancement(
            os.environ.get("NOKIDO_UI_BROWSER_ENGINE"), presents, etat
        )
        persistant = os.environ.get("NOKIDO_UI_BROWSER_PERSISTANT") == "1"
        self._pw = await async_playwright().start()

        refuses = []
        for moteur, canal, origine, motif in candidats:
            type_nav = getattr(self._pw, moteur)
            try:
                # `launch` NU par defaut, JAMAIS `launch_persistent_context` :
                # mesure du 2026-09-11, le persistant pend 180 s sans rien nommer
                # sous un compte de service. Le persistant reste joignable par
                # NOKIDO_UI_BROWSER_PERSISTANT=1 pour les usages interactifs, ou
                # les cookies gardes ont un interet.
                if persistant:
                    self._ctx = await type_nav.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        headless=not self.headed,
                        channel=canal,
                        viewport={"width": 1280, "height": 800},
                        timeout=LANCEMENT_TIMEOUT_MS,
                    )
                    self._page = (
                        self._ctx.pages[0]
                        if self._ctx.pages
                        else await self._ctx.new_page()
                    )
                else:
                    self._nav = await type_nav.launch(
                        headless=not self.headed,
                        channel=canal,
                        timeout=LANCEMENT_TIMEOUT_MS,
                    )
                    self._ctx = await self._nav.new_context(
                        viewport={"width": 1280, "height": 800}
                    )
                    self._page = await self._ctx.new_page()
            except Exception as e:  # noqa: BLE001
                # Un candidat qui refuse est NOMME, pas avale : sans cette liste,
                # « le navigateur ne marche pas » ne dit pas lequel ni pourquoi.
                refuses.append(
                    "%s/%s: %s: %s"
                    % (moteur, canal or "bundled", type(e).__name__, str(e)[:120])
                )
                continue
            self.lancement = {
                "moteur": moteur,
                "canal": canal,
                "origine": origine,
                "motif": motif,
                "magasin": etat,
                "refuses": refuses,
            }
            return self

        self.lancement = {"moteur": None, "magasin": etat, "refuses": refuses}
        raise RuntimeError(
            "aucun moteur de navigateur n'a pu etre lance (magasin %s : %s) -- %s"
            % (etat, sorted(presents) or "aucun", " | ".join(refuses) or "aucun essai")
        )

    async def __aexit__(self, *exc):
        # Les trois fermetures avalent VOLONTAIREMENT : une erreur de fermeture
        # sur un navigateur deja mort masquerait l'exception d'origine du bloc
        # `async with`, c'est-a-dire la vraie cause. On ferme au mieux, en
        # ordre inverse d'ouverture, et on ne fabrique jamais d'echec ici.
        try:
            if self._ctx:
                await self._ctx.close()
        except Exception:  # muet-ok : fermeture au mieux, ne doit pas masquer exc
            pass
        try:
            if self._nav:
                await self._nav.close()
        except Exception:  # muet-ok : fermeture au mieux, ne doit pas masquer exc
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:  # muet-ok : fermeture au mieux, ne doit pas masquer exc
            pass

    @property
    def page(self):
        return self._page

    async def goto(self, url: str, wait_until: str = "networkidle") -> str:
        await self._page.goto(url, wait_until=wait_until)
        return self._page.url

    async def wait_for_challenge(self, max_seconds: float = 30.0) -> bool:
        """Attend qu'un challenge anti-bot (JS) termine. Retourne True si passé."""
        deadline_ms = int(max_seconds * 1000)
        try:
            await self._page.wait_for_function(
                '() => !document.body.innerText.includes("Making sure you\'re not a bot")',
                timeout=deadline_ms,
            )
            return True
        except Exception:
            return False

    async def screenshot(self, path: str | Path, full_page: bool = True) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(p), full_page=full_page)
        return str(p)

    async def dom_text(self) -> str:
        return await self._page.evaluate("() => document.body.innerText")

    async def dom_html(self) -> str:
        return await self._page.content()

    async def click(self, selector: str, timeout_ms: int = 5000) -> None:
        await self._page.click(selector, timeout=timeout_ms)

    async def fill(self, selector: str, text: str, timeout_ms: int = 5000) -> None:
        await self._page.fill(selector, text, timeout=timeout_ms)

    async def press(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def wait(self, seconds: float) -> None:
        await self._page.wait_for_timeout(int(seconds * 1000))

    async def url(self) -> str:
        return self._page.url

    async def cookies(self) -> list[dict[str, Any]]:
        return await self._ctx.cookies()

    async def dump_cookies(self, path: str | Path) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(await self.cookies(), indent=2), encoding="utf-8")
        return str(p)

    async def eval_js(self, expr: str) -> Any:
        return await self._page.evaluate(expr)

    # ── "Lunettes" UI : a11y + Set-of-Mark (au lieu de pixels bruts) ───────────
    # Donne au LLM le SQUELETTE sémantique de l'interface (texte = sa zone de
    # génie) au lieu d'une capture qu'il doit deviner. Clic par index déterministe,
    # pas par "le bouton bleu en bas" (zéro hallucination spatiale).

    # Le selecteur est PARTAGE (voir SEL_INTERACTIF, niveau module) : tout compteur
    # « total » doit etre un SUR-ENSEMBLE des visibles. Deux selecteurs distincts ont
    # fait sortir « 2 visibles / 1 au total » sur /swarm — un instrument qui se
    # contredit ne mesure rien.
    _INTERACTIVE_JS = r"""
    () => {
      const sel = '""" + SEL_INTERACTIF + r"""';
      const out = []; let i = 0;
      for (const e of document.querySelectorAll(sel)) {
        const r = e.getBoundingClientRect();
        if (r.width <= 1 || r.height <= 1) continue;
        const st = getComputedStyle(e);
        if (st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0') continue;
        if (r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) continue;
        const name = (e.getAttribute('aria-label') || e.innerText || e.value || e.getAttribute('placeholder') || e.getAttribute('title') || e.getAttribute('name') || '').trim().replace(/\s+/g,' ').slice(0,90);
        out.push({i: i++, role: e.getAttribute('role') || e.tagName.toLowerCase(),
                  name, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
                  href: e.getAttribute('href') || null, disabled: !!e.disabled});
      }
      return out;
    }"""

    async def get_interactive_elements(self) -> list[dict[str, Any]]:
        """Liste JSON PURE des éléments interactifs visibles (index, role, nom,
        bbox, href). C'est ce que le LLM manipule — pas les pixels.

        ⚠️ VISIBLES DANS LE VIEWPORT uniquement : ce qui est sous la ligne de
        flottaison est ecarte. Pour « la page porte-t-elle des controles ? », c'est
        `count_interactive_document` qu'il faut — sinon un zero se lit « page morte ».
        """
        return await self._page.evaluate(self._INTERACTIVE_JS)

    async def count_interactive_document(self) -> int | None:
        """Nombre de controles dans TOUT le document, defilement compris.

        Rend None si la mesure n'a pas pu etre prise — jamais 0 par defaut : « je
        n'ai pas pu compter » et « il n'y en a aucun » sont deux etats distincts.
        """
        try:
            return int(await self._page.evaluate(
                "() => document.querySelectorAll('" + SEL_INTERACTIF + "').length"))
        except Exception:  # noqa: BLE001
            return None

    async def accessibility_tree(self) -> dict[str, Any] | None:
        """Arbre d'accessibilité (sémantique pur, sans le bruit <div>/CSS)."""
        try:
            return await self._page.accessibility.snapshot(interesting_only=True)
        except Exception:
            return None

    async def set_of_mark(self, path: str | Path, elements: list[dict[str, Any]] | None = None) -> str:
        """Dessine des boîtes numérotées sur les interactifs puis screenshot
        (viewport — coords getBoundingClientRect). Index = ceux de get_interactive_elements."""
        els = elements if elements is not None else await self.get_interactive_elements()
        await self._page.evaluate(
            r"""(els) => {
              document.getElementById('__som__')?.remove();
              const c=document.createElement('div'); c.id='__som__';
              c.style.cssText='position:fixed;inset:0;pointer-events:none;z-index:2147483647';
              const col=['#e6194B','#3cb44b','#4363d8','#f58231','#911eb4','#42d4f4','#f032e6','#bfef45'];
              for(const e of els){const k=col[e.i%col.length];
                const b=document.createElement('div');
                b.style.cssText=`position:absolute;left:${e.x}px;top:${e.y}px;width:${e.w}px;height:${e.h}px;border:2px solid ${k};box-sizing:border-box`;
                const l=document.createElement('div'); l.textContent=e.i;
                l.style.cssText=`position:absolute;left:${e.x}px;top:${Math.max(0,e.y-15)}px;background:${k};color:#fff;font:bold 11px monospace;padding:0 3px;border-radius:2px`;
                c.appendChild(b); c.appendChild(l);}
              document.body.appendChild(c);
            }""", els,
        )
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(p), full_page=False)
        await self._page.evaluate("() => document.getElementById('__som__')?.remove()")
        return str(p)

    async def dom_hash(self, elements: list[dict[str, Any]] | None = None) -> str:
        """Empreinte de l'état UI (roles+noms+positions des interactifs) — pour
        state-diff avant/après action (boucle active-inference, pas compréhension d'image)."""
        import hashlib

        els = elements if elements is not None else await self.get_interactive_elements()
        sig = [(e["role"], e["name"], e["x"], e["y"]) for e in els]
        return hashlib.sha256(json.dumps(sig, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]

    async def click_index(self, idx: int, elements: list[dict[str, Any]] | None = None) -> bool:
        """Clic déterministe par index Set-of-Mark (centre de la bbox). Retourne
        False si index absent. Pas de sélecteur fragile, pas de spatial."""
        els = elements if elements is not None else await self.get_interactive_elements()
        m = next((e for e in els if e["i"] == idx), None)
        if not m:
            return False
        await self._page.mouse.click(m["x"] + m["w"] / 2, m["y"] + m["h"] / 2)
        return True


async def ui_observe(url: str, mark_png: str | Path | None = None, headed: bool = False,
                     a11y: bool = False) -> dict[str, Any]:
    """ORACLE UI — traduit une page web en format hybride pour LLM (cf. essai
    "donner des lunettes à l'IA"). Retourne {url, n, elements[JSON], dom_hash,
    marks_png?, a11y?}. Le LLM lit `elements` (texte = génie), clique par index.

    Usage hors-hub (env playwright) :
        from forge_playwright_browser import ui_observe
        obs = await ui_observe("http://127.0.0.1:7400/", mark_png="sandbox/ui/obs.png")
    """
    async with PlaywrightBrowser(headed=headed) as br:
        await br.goto(url)
        els = await br.get_interactive_elements()
        # Détection canvas/WebGL : si l'a11y/DOM est quasi vide MAIS la page rend du
        # canvas/svg → l'arbre sémantique échoue, il faut un fallback VISION (SoM
        # sur pixels via forge_vision_som / OmniParser). Cf. essai "a11y vide".
        _r = await br.eval_js(
            "() => ({canvas: document.querySelectorAll('canvas').length,"
            " svg: document.querySelectorAll('svg').length})"
        )
        out: dict[str, Any] = {
            "url": await br.url(),
            "n": len(els),
            "elements": els,
            "dom_hash": await br.dom_hash(els),
            "vision_fallback": len(els) < 3 and (_r.get("canvas", 0) > 0 or _r.get("svg", 0) > 2),
        }
        if mark_png:
            out["marks_png"] = await br.set_of_mark(mark_png, els)
        if a11y:
            out["a11y"] = await br.accessibility_tree()
        return out


async def _demo() -> None:
    out_dir = Path(__file__).resolve().parent.parent / "sandbox" / "ui-playwright-demo"
    out_dir.mkdir(parents=True, exist_ok=True)
    async with PlaywrightBrowser() as br:
        await br.goto("http://127.0.0.1:7400/")
        png = await br.screenshot(out_dir / "home.png")
        txt = await br.dom_text()
        html = await br.dom_html()
        (out_dir / "home.txt").write_text(txt, encoding="utf-8")
        (out_dir / "home.html").write_text(html, encoding="utf-8")
        print(
            json.dumps(
                {
                    "url": await br.url(),
                    "screenshot": png,
                    "text_chars": len(txt),
                    "html_chars": len(html),
                    "profile": str(PROFILE_DIR),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    import argparse
    import sys

    _ap = argparse.ArgumentParser(description="Browser isolé + Oracle UI (a11y/set-of-mark).")
    _ap.add_argument("--observe", metavar="URL", help="Oracle UI : dump JSON des interactifs + dom_hash")
    _ap.add_argument("--mark", metavar="PNG", default=None, help="écrit un screenshot Set-of-Mark")
    _ap.add_argument("--a11y", action="store_true", help="inclut l'arbre d'accessibilité")
    _ap.add_argument("--headed", action="store_true", help="fenêtre visible (défaut headless ici)")
    _a = _ap.parse_args()
    if _a.observe:
        _obs = asyncio.run(ui_observe(_a.observe, mark_png=_a.mark, headed=_a.headed, a11y=_a.a11y))
        sys.stdout.write(json.dumps(_obs, ensure_ascii=False))
    else:
        asyncio.run(_demo())
