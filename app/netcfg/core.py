import os
import re
import yaml
import json
import jsonschema
from pathlib import Path
from typing import List, Dict, Any, Optional
from netmiko import ConnectHandler
from jinja2 import Template

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
SCHEMA_PATH = TEMPLATES_DIR / "_schema.json"

# Blacklist globale hardcodée (fail-closed)
GLOBAL_DESTRUCTIVE = [
    r"^\s*factory[- ]?reset",
    r"^\s*erase\s+(startup|running|flash)",
    r"^\s*reload\b",
    r"^\s*write\s+erase",
    r"^\s*boot\s+system\s+.*tftp://",
]


class Safety:
    @staticmethod
    def is_safe(command: str, local_blacklist: List[str] = None) -> bool:
        """Vérifie si une commande est autorisée."""
        # 1. Check global
        for pattern in GLOBAL_DESTRUCTIVE:
            if re.search(pattern, command, re.IGNORECASE):
                return False
        # 2. Check local vendor
        if local_blacklist:
            for pattern in local_blacklist:
                if re.search(pattern, command, re.IGNORECASE):
                    return False
        return True


class VendorTemplate:
    def __init__(self, vendor_key: str):
        self.path = TEMPLATES_DIR / f"{vendor_key}.yml"
        if not self.path.exists():
            self.path = TEMPLATES_DIR / "_generic.yml"

        with open(self.path, "r", encoding="utf-8") as f:
            self.data = yaml.safe_all_load(f) if vendor_key == "multiple" else yaml.safe_load(f)

        # Validation auto
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=self.data, schema=schema)


class Equipment:
    def __init__(self, ip: str, hostname: str, vendor_key: str):
        self.ip = ip
        self.hostname = hostname
        self.vendor_template = VendorTemplate(vendor_key)
        self.connection = None

    def connect(self, username, password, secret=None):
        """Établit la connexion Netmiko."""
        device_params = {
            "device_type": self.vendor_template.data["netmiko_device_type"],
            "host": self.ip,
            "username": username,
            "password": password,
            "secret": secret,
        }
        self.connection = ConnectHandler(**device_params)
        return self.connection

    def get_running_config(self) -> str:
        if not self.connection:
            raise ConnectionError("Non connecté")
        cmd = self.vendor_template.data["commands"]["show_running"]
        return self.connection.send_command(cmd)

    def disconnect(self):
        if self.connection:
            self.connection.disconnect()
            self.connection = None


class VendorDetector:
    @staticmethod
    def detect_via_ssh(banner: str) -> str:
        """Détecte le vendor_key via la bannière SSH."""
        for file in TEMPLATES_DIR.glob("*.yml"):
            if file.name.startswith("_"):
                continue
            with open(file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                patterns = data.get("detection", {}).get("ssh_banner_match", [])
                for p in patterns:
                    if re.search(p, banner, re.IGNORECASE):
                        return data["vendor"]
        return "_generic"
