import json

import r2pipe


class BinaryGraph:
    def __init__(self, binary_path: str):
        self.binary_path = binary_path
        self.graph = {}

    def analyze(self) -> dict:
        try:
            r2 = r2pipe.open(self.binary_path, flags=["-2"])
            r2.cmd("aaa")
            functions = r2.cmdj("aflj")
            for fn in functions:
                callers = r2.cmdj(f"axtj @ {fn['offset']}")
                callers = [c["from"] for c in callers]
                self.graph[fn["name"]] = {
                    "callers": callers,
                    "size": fn["size"],
                    "offset": hex(fn["offset"]),
                }
            r2.quit()
            return {
                "nodes": len(self.graph),
                "edges": sum(len(callers) for callers in self.graph.values()),
                "graph": self.graph,
            }
        except ImportError:
            return {"error": "r2pipe not installed"}

    def top_functions(self, n: int = 10) -> list[dict]:
        sorted_functions = sorted(
            self.graph.items(), key=lambda x: len(x[1]["callers"]), reverse=True
        )
        return [
            {"name": fn[0], "callers_count": len(fn[1]["callers"]), "size": fn[1]["size"]}
            for fn in sorted_functions[:n]
        ]

    def save_json(self, output_path: str) -> None:
        with open(output_path, "w") as f:
            json.dump(self.graph, f)


# Exemple d'utilisation
if __name__ == "__main__":
    bg = BinaryGraph("path/to/binary")
    result = bg.analyze()
    print(result)
    top_fn = bg.top_functions()
    print(top_fn)
    bg.save_json("output.json")
