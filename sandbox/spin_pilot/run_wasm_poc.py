import wasmtime
import sys

def run_wasi_route(wasm_path: str) -> str:
    # 1. Initialize Wasmtime Engine and Store
    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    
    # 2. Configure WASI: redirect stdout to a file/pipe we can capture
    wasi_config = wasmtime.WasiConfig()
    wasi_config.inherit_env()
    
    # We will capture stdout into a temporary file or use wasmtime's stdout capture
    import tempfile
    stdout_file = tempfile.NamedTemporaryFile(delete=False)
    wasi_config.stdout_file = stdout_file.name
    
    store.set_wasi(wasi_config)
    
    # 3. Load the compiled WASM module
    module = wasmtime.Module.from_file(engine, wasm_path)
    
    # 4. Link the WASI functions
    linker = wasmtime.Linker(engine)
    linker.define_wasi()
    
    # 5. Instantiate and run
    instance = linker.instantiate(store, module)
    
    # Lookup the entry point (_start)
    start_func = instance.exports(store)["_start"]
    
    print("Executing WASM route handler...")
    start_func(store)
    
    # Read the captured stdout
    stdout_file.close()
    with open(stdout_file.name, "r") as f:
        output = f.read()
    
    import os
    os.unlink(stdout_file.name)
    
    return output

if __name__ == "__main__":
    wasm_file = "sandbox/spin_pilot/health_poc.wasm"
    try:
        json_output = run_wasi_route(wasm_file)
        print("--- WASM Out ---")
        print(json_output.strip())
        print("----------------")
    except Exception as e:
        print(f"Error executing WASM: {e}")
        sys.exit(1)
