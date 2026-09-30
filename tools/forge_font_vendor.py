"""forge_font_vendor.py — vendore les webfonts du portail web_hub :7400 en local.

Souveraineté : 0 egress runtime. Résout les woff2 courants via l'API Google
css2 (les URLs hashées codées en dur pourrissent -> 404), télécharge le sous-
ensemble `latin` (couvre le français : accents en Latin-1 U+00E0-00FF), et place
les fichiers dans app/web_hub/static/fonts/. Réutilisable/idempotent.

Lancer privilégié (owner) pour pouvoir écrire dans static/ (user-owned) :
  hub run action=trusted_script path=tools/forge_font_vendor.py
"""

__FORGE_COLOR__ = "interface/ui_ : vendore les webfonts du portail web_hub"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import re
import json
import urllib.request
import shutil

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
STAGE = r"C:/tmp/nokido_font_vendor"
_HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.abspath(os.path.join(_HERE, "..", "app", "web_hub", "static", "fonts"))

FAMILIES = {"Inter": [400, 500, 600, 700], "JetBrains Mono": [400, 500, 700]}


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _css2_url(family, weights):
    fam = family.replace(" ", "+")
    w = ";".join(str(x) for x in weights)
    return f"https://fonts.googleapis.com/css2?family={fam}:wght@{w}&display=swap"


def _slug(family):
    return family.lower().replace(" ", "-")


def main():
    os.makedirs(STAGE, exist_ok=True)
    report = {"resolved": {}, "downloaded": {}, "errors": {}, "placed": None, "dest": DEST}
    want = {}

    for family, weights in FAMILIES.items():
        try:
            css = _fetch(_css2_url(family, weights)).decode("utf-8", "replace")
        except Exception as e:
            report["errors"][family] = f"css2 fetch: {e!r}"
            continue
        for m in re.finditer(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{([^}]*)\}", css):
            subset, body = m.group(1), m.group(2)
            if subset != "latin":
                continue
            wm = re.search(r"font-weight:\s*(\d+)", body)
            um = re.search(r"src:\s*url\((https://[^)]+\.woff2)\)", body)
            if not (wm and um):
                continue
            weight = int(wm.group(1))
            if weight not in weights:
                continue
            fn = f"{_slug(family)}-{weight}.woff2"
            want[fn] = um.group(1)
            report["resolved"][fn] = um.group(1)

    for fn, url in want.items():
        try:
            data = _fetch(url)
            if data[:4] != b"wOF2":
                report["errors"][fn] = f"not woff2 (magic={data[:4]!r}, size={len(data)})"
                continue
            with open(os.path.join(STAGE, fn), "wb") as f:
                f.write(data)
            report["downloaded"][fn] = len(data)
        except Exception as e:
            report["errors"][fn] = repr(e)

    try:
        os.makedirs(DEST, exist_ok=True)
        staged = [f for f in os.listdir(STAGE) if f.endswith(".woff2")]
        for fn in staged:
            shutil.copy2(os.path.join(STAGE, fn), os.path.join(DEST, fn))
        report["placed"] = {"ok": staged}
    except Exception as e:
        report["placed"] = f"FAIL: {e!r}"

    with open(os.path.join(STAGE, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
