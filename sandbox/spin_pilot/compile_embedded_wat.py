import wasmtime
from pathlib import Path

wat_content = """(module
  ;; Define linear memory
  (memory (export "memory") 1)

  ;; Store our JSON string in memory at offset 0
  (data (i32.const 0) "{\\"status\\":\\"ok\\",\\"version\\":\\"wasm-embedded-0.1.0\\"}")

  ;; Export a function that returns the offset of the string
  (func (export "get_string_ptr") (result i32)
    (i32.const 0)
  )

  ;; Export a function that returns the length of the string
  (func (export "get_string_len") (result i32)
    (i32.const 47)
  )
)"""

print("Compiling embedded WAT to WASM...")
wasm_bytes = wasmtime.wat2wasm(wat_content)

output_path = Path("sandbox/spin_pilot/health_embedded.wasm")
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_bytes(wasm_bytes)
print(f"Successfully compiled to {output_path} (size: {len(wasm_bytes)} bytes)")
