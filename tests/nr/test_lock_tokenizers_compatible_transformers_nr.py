"""NR -- le verrouillage Python respecte la contrainte que `transformers` declare sur `tokenizers` (owner 18/10).

Mesure du 18/10 : requirements.nokido_py314.lock epinglait tokenizers==0.23.1 avec transformers==5.10.1, qui exige
tokenizers>=0.22.0,<=0.23.0 -- tout `import transformers` levait ImportError (dependency_versions_check). Le mode
latent de RecursiveMAS (forge_recursive_link) en est mort (job_1201ebb0037f). Decision owner : redescendre tokenizers.
La contrainte est LUE dans les metadonnees de transformers, jamais recopiee ici.
"""
from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "requirements.nokido_py314.lock"


def _epingle(nom):
    m = re.search(r"(?mi)^%s==([^\s;#]+)" % re.escape(nom), LOCK.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def test_le_lock_respecte_la_contrainte_de_transformers_sur_tokenizers():
    specifiers = pytest.importorskip("packaging.specifiers")
    try:
        exig = [r for r in (metadata.requires("transformers") or []) if r.lower().startswith("tokenizers")
                and "extra ==" not in r]
    except metadata.PackageNotFoundError:
        pytest.skip("transformers absent de cet environnement : contrainte illisible ici, pas un vert")
    assert exig, "transformers ne declare plus de contrainte sur tokenizers : relire le test"
    spec = specifiers.SpecifierSet(re.sub(r"(?i)^tokenizers\s*", "", exig[0].split(";")[0]).strip(" ()"))
    tok = _epingle("tokenizers")
    assert tok and tok in spec, "lock tokenizers==%s hors de %s (exige par transformers)" % (tok, spec)
