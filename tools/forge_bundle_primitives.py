import base64
import json
import os
import zlib

import requests

# Bornes de l'appel sortant. Reglables par l'environnement parce qu'un lot lourd
# n'a pas la meme duree legitime qu'un `poll` ; la valeur par defaut vise le hub
# LOCAL, seul destinataire connu de ce client.
CONNEXION_S = float(os.environ.get("LAFORGE_BUNDLE_CONNECT_S", "5"))
LECTURE_S = float(os.environ.get("LAFORGE_BUNDLE_READ_S", "120"))


class BundleSession:
    def __init__(self, endpoint=None, token=None):
        self.endpoint = endpoint or os.environ.get(
            "LAFORGE_HUB_BUNDLE_URL", "http://127.0.0.1:8766/bundle"
        )
        self.token = token or os.environ.get("FORGE_MCP_TOKEN", "")
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.calls:
            self.commit()

    def add_call(self, tool: str, args: dict):
        self.calls.append({"tool": tool, "args": args})

    def commit(self):
        if not self.calls:
            return []

        payload = json.dumps({"calls": self.calls}).encode("utf-8")
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        if len(payload) > 10240:
            compressed = zlib.compress(payload)
            body = base64.b64encode(compressed).decode("ascii")
            req_json = {"bundle_zlib": body}
        else:
            req_json = {"bundle_raw": self.calls}

        # ECHEANCE OBLIGATOIRE (audit securite 2026-09-18, finding #3).
        #
        # L'appel partait sans `timeout=`. `requests` attend alors INDEFINIMENT :
        # un pair muet — hub gele, port qui accepte sans repondre — suspend
        # l'appelant sans borne, et la ligne suivante (`raise_for_status`) n'est
        # jamais atteinte. Un appel qui ne rend jamais la main est indiscernable
        # d'un appel lent : personne ne vient le debloquer.
        #
        # Deux bornes, pas une : la connexion doit s'etablir vite (un hub local
        # repond en millisecondes, ou il n'est pas la), l'execution du lot peut
        # legitimement durer. Les confondre obligerait a choisir entre detecter
        # un port mort tard et tuer un lot qui travaille.
        r = requests.post(self.endpoint, json=req_json, headers=headers,
                          timeout=(CONNEXION_S, LECTURE_S))
        r.raise_for_status()
        self.calls = []
        return r.json().get("results", [])


if __name__ == "__main__":
    # Test example
    with BundleSession() as b:
        b.add_call("hub", {"action": "poll"})
    print("Bundle executed successfully.")
