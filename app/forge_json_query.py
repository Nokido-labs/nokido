
__FORGE_COLOR__ = "infra/util : requete JSON et JSONL par chemin"  # organe declare le 2026-09-06 (audit de raccordement)
from pathlib import Path
import json

class JsonQueryTool:
    def query_json(self, file_path: str, query: str) -> dict:
        """
        Queries a JSON or JSONL file using a basic key-based query.
        Returns the value at the specified path or an error if not found.
        """
        try:
            path = Path(file_path)
            if not path.exists():
                return {"error": f"File not found: {file_path}"}

            content = path.read_text(encoding="utf-8")
            data = None

            if path.suffix == ".jsonl":
                # For JSONL, we'll assume the query applies to each line/object
                # and return the first match for simplicity in this initial version.
                # A more robust version would iterate or allow aggregation.
                for line in content.splitlines():
                    if line.strip():
                        obj = json.loads(line)
                        try:
                            # Basic dot-notation traversal for query
                            result = obj
                            for key in query.split('.'):
                                if isinstance(result, dict) and key in result:
                                    result = result[key]
                                elif isinstance(result, list) and key.isdigit() and int(key) < len(result):
                                    result = result[int(key)]
                                else:
                                    raise KeyError(f"Key '{key}' not found in path.")
                            return {"result": result}
                        except (KeyError, IndexError, TypeError):
                            continue # Try next line if key not found in current object
                return {"error": f"Query '{query}' not found in any object in {file_path}"}
            else: # Assume .json
                data = json.loads(content)
                # Basic dot-notation traversal for query
                result = data
                for key in query.split('.'):
                    if isinstance(result, dict) and key in result:
                        result = result[key]
                    elif isinstance(result, list) and key.isdigit() and int(key) < len(result):
                        result = result[int(key)]
                    else:
                        return {"error": f"Query path '{query}' not found in {file_path}"}
                return {"result": result}

        except json.JSONDecodeError:
            return {"error": f"Invalid JSON in file: {file_path}"}
        except Exception as e:
            return {"error": f"An unexpected error occurred: {str(e)}"}

# Example usage (for testing purposes, will be removed)
if __name__ == "__main__":
    tool = JsonQueryTool()

    # Create a dummy JSON file
    dummy_json_content = """
    {
        "system": {
            "cpu_load": 85,
            "memory_usage": 70
        },
        "status": "operational",
        "logs": [
            {"id": 1, "message": "Startup complete", "level": "INFO"},
            {"id": 2, "message": "Disk usage high", "level": "WARNING"}
        ]
    }
    """
    Path("dummy.json").write_text(dummy_json_content)

    # Create a dummy JSONL file
    dummy_jsonl_content = """
    {"event": "login", "user": "alice", "timestamp": "2026-06-16T10:00:00Z"}
    {"event": "logout", "user": "bob", "timestamp": "2026-06-16T10:05:00Z"}
    {"event": "error", "message": "Failed to connect", "code": 500}
    """
    Path("dummy.jsonl").write_text(dummy_jsonl_content)


    print("Querying dummy.json:")
    print(tool.query_json("dummy.json", "system.cpu_load"))
    print(tool.query_json("dummy.json", "status"))
    print(tool.query_json("dummy.json", "logs.0.message"))
    print(tool.query_json("dummy.json", "logs.1.level"))
    print(tool.query_json("dummy.json", "non_existent.key"))

    print("\nQuerying dummy.jsonl:")
    print(tool.query_json("dummy.jsonl", "user")) # Should find 'alice' from the first line
    print(tool.query_json("dummy.jsonl", "message")) # Should find 'Failed to connect' from the error line
    print(tool.query_json("dummy.jsonl", "code"))
    print(tool.query_json("dummy.jsonl", "event"))

    # Cleanup
    Path("dummy.json").unlink()
    Path("dummy.jsonl").unlink()
