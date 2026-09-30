"""
app/forge_spec_clarifier.py — Clarification dialogue structuré (software creator gap#7)
spec ambiguë → questions ciblées → spec YAML formalisée
"""

import json, sys
from typing import List, Dict

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

try:
    import requests as _req

    def _ollama(prompt: str, model: str = "laforge-qwen:latest") -> str:
        r = _req.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.3}},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["response"].strip()
except ImportError:

    def _ollama(prompt: str, **kw) -> str:
        raise ImportError("pip install requests")


def detect_ambiguities(spec_text: str) -> List[str]:
    prompt = f"""Analyze this specification. Return a JSON array of ambiguity strings (max 7).
Focus on: vague terms, missing constraints, undefined edge cases, inconsistencies.
Spec:\n{spec_text[:3000]}
Return ONLY a JSON array."""
    raw = _ollama(prompt)
    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        return json.loads(raw[start:end]) if start >= 0 else [raw[:200]]
    except Exception:
        return [raw[:200]]


def generate_questions(ambiguities: List[str]) -> List[str]:
    prompt = f"""Given these spec ambiguities, generate up to 5 targeted clarification questions.
Return ONLY a JSON array of question strings.
Ambiguities: {json.dumps(ambiguities[:7])}"""
    raw = _ollama(prompt)
    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        return json.loads(raw[start:end]) if start >= 0 else []
    except Exception:
        return []


def formalize_spec(spec_text: str, answers: Dict[str, str]) -> str:
    prompt = f"""Transform this spec + answers into a structured YAML specification.
Sections: purpose, inputs, outputs, behaviors, constraints, error_handling.
Return ONLY valid YAML.

Original spec:\n{spec_text[:2000]}

Clarification answers:\n{json.dumps(answers)}"""
    return _ollama(prompt)


class ClarificationDialog:
    def run_interactive(self, spec_text: str) -> str:
        steps = ["detect ambiguities", "generate questions", "formalize spec"]
        with tqdm(total=3, desc="clarifying spec") as pbar:
            pbar.set_postfix(step=steps[0])
            ambiguities = detect_ambiguities(spec_text)
            pbar.update(1)

            pbar.set_postfix(step=steps[1])
            questions = generate_questions(ambiguities)
            pbar.update(1)

            answers: Dict[str, str] = {}
            for i, q in enumerate(questions, 1):
                print(f"\nQ{i}/{len(questions)}: {q}")
                answers[q] = input("→ ").strip()

            pbar.set_postfix(step=steps[2])
            result = formalize_spec(spec_text, answers)
            pbar.update(1)

        return result

    def run_headless(self, spec_text: str, answers: Dict[str, str]) -> str:
        return formalize_spec(spec_text, answers)


if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "Build a REST API for user management."
    dialog = ClarificationDialog()
    result = dialog.run_interactive(spec)
    print("\n=== Formalized Spec ===")
    print(result)
