import zipfile
import lxml.etree as ET
from pathlib import Path
from typing import List, Dict, Any


class VisioParser:
    """
    Parser minimal pour fichiers .vsdx (Visio).
    Extrait les shapes et leurs métadonnées (Custom Properties).
    """

    # Whitelist d'attributs autorisés pour éviter l'injection via Visio
    ALLOWED_PROPS = {"IP", "Hostname", "Vendor", "Model", "Location", "KeePassEntry", "VLAN", "Interface"}

    def __init__(self, file_path: str | Path):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"Fichier Visio introuvable: {file_path}")

    def parse_minimal(self) -> List[Dict[str, Any]]:
        """
        Extrait une liste d'équipements depuis le premier onglet (page1.xml).
        """
        equipments = []

        try:
            with zipfile.ZipFile(self.file_path, "r") as z:
                # Page 1 est généralement dans visio/pages/page1.xml
                # Les noms de shapes/données sont dans visio/pages/page1.xml
                # Les propriétés sont souvent dans visio/pages/_rels/page1.xml.rels
                # ou directement dans les Data de la shape.

                try:
                    page_content = z.read("visio/pages/page1.xml")
                except KeyError:
                    # Tenter de lister pour trouver le bon chemin si différent
                    pages = [f for f in z.namelist() if f.startswith("visio/pages/page") and f.endswith(".xml")]
                    if not pages:
                        raise ValueError("Aucune page trouvée dans le fichier VSDX")
                    page_content = z.read(pages[0])

                root = ET.fromstring(page_content)

                # Namespace Visio
                ns = {"v": "http://schemas.microsoft.com/office/visio/2012/main"}

                # On cherche tous les Shapes
                for shape in root.xpath("//v:Shape", namespaces=ns):
                    shape_id = shape.get("ID")

                    # Extraction des "Data1", "Data2"... ou "Cell" de type User/Prop
                    # Dans le format XML moderne, les propriétés sont dans <Cell N='Prop.XYZ'>
                    eq_data = {"visio_shape_id": shape_id, "raw_props": {}}

                    # On cherche les cellules de propriétés personnalisées
                    for cell in shape.xpath(".//v:Cell[starts-with(@N, 'Prop.')]", namespaces=ns):
                        prop_name = cell.get("N").replace("Prop.", "")
                        prop_value = cell.get("V")

                        if prop_name in self.ALLOWED_PROPS:
                            eq_data["raw_props"][prop_name] = prop_value

                    if eq_data["raw_props"]:
                        # Normalisation minimale
                        eq_data["ip_mgmt"] = eq_data["raw_props"].get("IP")
                        eq_data["hostname"] = eq_data["raw_props"].get("Hostname", f"Shape_{shape_id}")
                        eq_data["vendor_key"] = eq_data["raw_props"].get("Vendor")

                        if eq_data["ip_mgmt"]:
                            equipments.append(eq_data)

        except Exception as e:
            raise ValueError(f"Erreur lors du parsing Visio: {e}")

        return equipments


if __name__ == "__main__":
    # Test rapide si lancé en solo
    import sys

    if len(sys.argv) > 1:
        parser = VisioParser(sys.argv[1])
        print(parser.parse_minimal())
