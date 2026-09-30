
# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "metabolisme/ollama : un modele local repond sur le contenu d'un fichier"  # organe declare le 2026-09-06 (audit de raccordement)
from pathlib import Path
import json
import asyncio
import logging

# Assuming forge_ollama.py is in the same 'app' directory
from nokido_agent.app.forge_ollama import ollama_call

logger = logging.getLogger("Nokido.LocalScout")

async def ask_local_scout(
    file_path: str,
    question: str,
    model: str = "qwen2:7b", # Default local scout model
    max_tokens: int = 500,
    system_prompt: str = "You are a concise AI assistant. Summarize the provided document in response to the user's question."
) -> dict:
    """
    Uses a local Ollama model to answer questions about a given file's content.

    Args:
        file_path: The absolute path to the file to read.
        question: The question to ask about the file's content.
        model: The Ollama model to use for the query.
        max_tokens: The maximum number of tokens for the model's response.
        system_prompt: The system prompt to guide the LLM.

    Returns:
        A dictionary containing the model's response or an error message.
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}"}
        if not path.is_file():
            return {"error": f"Path is not a file: {file_path}"}

        # Read file content, limit to a reasonable size to avoid overwhelming LLM
        file_content = path.read_text(encoding="utf-8", errors="replace")
        # Truncate content if it's too large, e.g., to 10k characters
        if len(file_content) > 10000:
            file_content = file_content[:5000] + "\n[... Content truncated ...]\n" + file_content[-5000:]
            logger.warning(f"File content truncated for LLM: {file_path}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"File: {path.name}\nContent:\n{file_content}\n\nQuestion: {question}"}
        ]

        logger.info(f"Calling local scout model '{model}' for file '{path.name}' with question: '{question}'")
        response_text = await ollama_call(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            timeout=180.0 # Increased timeout for LLM inference
        )
        return {"response": response_text}

    except Exception as e:
        logger.error(f"Error in ask_local_scout: {e}")
        return {"error": f"An unexpected error occurred: {str(e)}"}

# Example usage (for testing purposes, will be removed later)
if __name__ == "__main__":
    async def main():
        # Create a dummy file
        dummy_file_content = """
        This is a test document.
        It talks about local models and how they can be used for summarization.
        The main idea is to process data locally to save tokens and latency.
        """
        Path("dummy_doc.txt").write_text(dummy_file_content)

        # Example question
        question = "What is the main idea of this document?"

        print("Asking local scout:")
        result = await ask_local_scout("dummy_doc.txt", question)
        print(json.dumps(result, indent=2))

        # Cleanup
        Path("dummy_doc.txt").unlink()

    asyncio.run(main())
