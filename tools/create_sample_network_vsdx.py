"""
Genere un fichier .vsdx de demonstration pour le dossier Sample Network.
"""

__FORGE_COLOR__ = "reseau/topology : genere un .vsdx de demonstration (Sample Network)"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import zipfile
from pathlib import Path

from netcfg.visio import parse_excel

# Chemins
REPO_ROOT = Path.cwd()
DEMO_DIR = REPO_ROOT / "netcfg-agent" / "demo"
TPL_DIR = DEMO_DIR / "vsdx_templates"
MAPS_DIR = DEMO_DIR / "site_maps"
EXCEL_PATH = (
    REPO_ROOT / "Nokido" / "Template visio" / "Sample Network" / "Visio sample network.xlsx"
)
OUTPUT_PATH = (
    REPO_ROOT / "Nokido" / "Template visio" / "Sample Network" / "Sample Network Demo.vsdx"
)


def build():
    print(f"Parsing Excel: {EXCEL_PATH}...")
    network = parse_excel(EXCEL_PATH)

    # Enrichissement manuel pour la demo
    network["site"] = "Corporate Office - Sample Network"
    network["pages"][0]["name"] = "HQ Office Plan"
    network["pages"][0]["map_image"] = "map_hq.png"

    # On positionne les 5 premiers équipements en arc de cercle
    coords = [
        {"x": 250, "y": 200},
        {"x": 450, "y": 150},
        {"x": 650, "y": 200},
        {"x": 450, "y": 350},
        {"x": 250, "y": 350},
    ]

    for i, eq in enumerate(network["equipment"][:5]):
        eq["position"] = coords[i]
        eq["page_id"] = "p1"
        # On assigne des vendors reels pour la demo
        if "hp" in eq["vendor_key"]:
            eq["vendor_key"] = "hp_procurve"
        elif "netgear" in eq["vendor_key"]:
            eq["vendor_key"] = "netgear_prosafe"
        else:
            eq["vendor_key"] = "cisco_ios"

    network["pages"][0]["id"] = "p1"
    for eq in network["equipment"]:
        eq["page_id"] = "p1"

    # Ajout d'un lien pour le visuel
    if len(network["equipment"]) >= 2:
        network["links"].append(
            {
                "src": network["equipment"][0]["shape_id"],
                "src_interface": "Gig1/0/1",
                "dst": network["equipment"][1]["shape_id"],
                "dst_interface": "Gig1/0/1",
                "link_type": "trunk",
                "allowed_vlans": [1],
            }
        )

    ZIP_MAP = {
        "[Content_Types].xml": "[Content_Types].xml",
        "_rels__.rels": "_rels/.rels",
        "docProps__app.xml": "docProps/app.xml",
        "docProps__core.xml": "docProps/core.xml",
        "visio__document.xml": "visio/document.xml",
        "visio___rels__document.xml.rels": "visio/_rels/document.xml.rels",
        "visio__pages__pages.xml": "visio/pages/pages.xml",
        "visio__pages___rels__pages.xml.rels": "visio/pages/_rels/pages.xml.rels",
        "visio__pages__page1.xml": "visio/pages/page1.xml",
    }

    print(f"Construction de {OUTPUT_PATH}...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Templates Visio
        for fname, arcname in ZIP_MAP.items():
            zf.writestr(arcname, (TPL_DIR / fname).read_text(encoding="utf-8"))

        # 2. JSON Source de verite
        zf.writestr("netcfg/network.json", json.dumps(network, indent=2))

        # 3. Map
        zf.writestr("netcfg/maps/map_hq.png", (MAPS_DIR / "map_hq.png").read_bytes())

    print("Succes !")


if __name__ == "__main__":
    build()
