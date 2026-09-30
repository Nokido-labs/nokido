import wasmtime
from pathlib import Path

wat_content = """(module
  ;; Import WASI fd_write
  (import "wasi_snapshot_preview1" "fd_write" (func $fd_write (param i32 i32 i32 i32) (result i32)))

  ;; Define linear memory
  (memory (export "memory") 1)

  ;; Store iovec at address 0: pointer to data (offset 8), length of data (46)
  (data (i32.const 0) "\\08\\00\\00\\00\\2e\\00\\00\\00")
  ;; JSON string at address 8:
  (data (i32.const 8) "{\\"status\\":\\"ok\\",\\"version\\":\\"wasm-wat-0.1.0\\"}\\n")

  ;; Define the WASI entrypoint
  (func (export "_start")
    (call $fd_write
      (i32.const 1)  ;; fd 1 = stdout
      (i32.const 0)  ;; iovs pointer
      (i32.const 1)  ;; iovs count
      (i32.const 60) ;; nwritten pointer
    )
    drop
  )
)"""

print("Compiling WAT to WASM...")
wasm_bytes = wasmtime.wat2wasm(wat_content)

output_path = Path("sandbox/spin_pilot/health_poc.wasm")
output_path.parent.mkdir(parents=True, exist_ok=True)
output_path.write_bytes(wasm_bytes)
print(f"Successfully compiled to {output_path} (size: {len(wasm_bytes)} bytes)")
