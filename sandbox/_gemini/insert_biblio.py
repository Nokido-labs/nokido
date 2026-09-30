
import sys, os, json
from pathlib import Path
ROOT = Path(__import__("os").path.expanduser(r"~\Script python IA\LaForge"))
sys.path.insert(0, str(ROOT / "app"))
from forge_biblio_core import insert_biblio_raw

entries = [
    {
        "type": "paper",
        "title": "AlphaFold 3 & Boltz-2 (2025) - Molecular Predictive Modeling",
        "authors": ["Google DeepMind", "Boltz Team"],
        "year": 2025,
        "url": "https://lbl.gov",
        "description": "AI models predicting binding affinities and molecular interactions beyond protein folding.",
        "triggered_by_idea_id": "veille_active_20260428",
        "source_kind": "agent_research"
    },
    {
        "type": "concept",
        "title": "SemiSynBio - DNA-based Neuromorphic Computing",
        "authors": ["NIH", "National Laboratory"],
        "year": 2024,
        "url": "https://nih.gov",
        "description": "Molecular-level neuromorphic computing using DNA to construct artificial neural networks.",
        "triggered_by_idea_id": "veille_active_20260428",
        "source_kind": "agent_research"
    },
    {
        "type": "concept",
        "title": "Agentic AI & Recursive Self-Improvement",
        "authors": ["Agentic Frameworks Team"],
        "year": 2025,
        "url": "https://technewsworld.com",
        "description": "Multi-agent teams that self-organize and refine internal logic autonomously.",
        "triggered_by_idea_id": "veille_active_20260428",
        "source_kind": "agent_research"
    }
]

results = []
for entry in entries:
    res = insert_biblio_raw(entry)
    results.append(res)

print(json.dumps(results, indent=2))
