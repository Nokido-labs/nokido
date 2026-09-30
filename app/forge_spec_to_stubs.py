import re
import ast
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Union


@dataclass
class StubResult:
    stubs_written: bool = False
    symbols_count: int = 0
    warnings: List[str] = field(default_factory=list)


def spec_to_stubs(spec_md: str, output_path: Union[str, Path]) -> StubResult:
    out_path = Path(output_path)
    warnings = []
    symbols = 0

    stubs = ["from typing import *", "import typing", ""]

    # Split by ## sections
    sections = re.split(r"^##\s+", spec_md, flags=re.MULTILINE)

    for section in sections:
        if not section.strip():
            continue
        lines = section.split("\n")
        section_title = lines[0].strip().lower()

        if section_title not in ("interface", "types", "behaviors", "api"):
            continue

        current_def = None
        current_doc = []

        for line in lines[1:]:
            clean_line = line.strip()

            # Match python definitions
            match = re.search(
                r"(?:^|`)(def \w+\([^)]*\)(?:\s*->\s*[^:`]+)?|class \w+(?:\([^)]*\))?)(?::|`|$)", clean_line
            )
            if match:
                if current_def:
                    stubs.append(current_def + ":")
                    if current_doc:
                        stubs.append(f'    """{" ".join(current_doc)}"""')
                    stubs.append("    ...")
                    stubs.append("")
                    symbols += 1

                current_def = match.group(1)
                current_doc = []
            elif current_def and clean_line and not clean_line.startswith("`") and not clean_line.startswith("#"):
                current_doc.append(clean_line.replace('"', "'"))

        if current_def:
            stubs.append(current_def + ":")
            if current_doc:
                stubs.append(f'    """{" ".join(current_doc)}"""')
            stubs.append("    ...")
            stubs.append("")
            symbols += 1

    # Fallback to code blocks
    if symbols == 0:
        code_blocks = re.findall(r"```(?:python|py)\n(.*?)\n```", spec_md, re.DOTALL)
        for block in code_blocks:
            for line in block.split("\n"):
                if line.strip().startswith("def ") or line.strip().startswith("class "):
                    if not line.strip().endswith(":"):
                        line += ":"
                    stubs.append(line)
                    stubs.append("    ...")
                    symbols += 1

    if symbols == 0:
        warnings.append("No Python definitions found in spec.")
        return StubResult(False, 0, warnings)

    stub_content = "\n".join(stubs)

    try:
        ast.parse(stub_content, filename=str(out_path))
    except SyntaxError as e:
        warnings.append(f"Generated stub is invalid Python: {e}")
        return StubResult(False, symbols, warnings)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(stub_content, encoding="utf-8")

    return StubResult(True, symbols, warnings)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 2:
        res = spec_to_stubs(Path(sys.argv[1]).read_text(encoding="utf-8"), Path(sys.argv[2]))
        print(res)
