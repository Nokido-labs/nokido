# mcp_stdio.py

import sys
import json
import asyncio

from agent_core import AgentCore
import config

async def run_stdio_loop():
    """
    Run the main loop for STDIO communication.
    Reads JSON requests from stdin and writes JSON responses to stdout.
    """
    if not config.ENABLE_STDIO:
        print("MCP STDIO Interface is disabled in the configuration.")
        return

    print("MCP STDIO Interface is running. Waiting for JSON requests on stdin...")

    agent_core = AgentCore()
    tools = agent_core.get_tools()

    while True:
        try:
            line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                break  # End of stream

            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            tool_name = request.get("tool")
            params = request.get("params", {})

            response = {}

            if not tool_name:
                response = {
                    "error": "Request must include a 'tool' field.",
                    "request": request,
                }
            elif tool_name not in tools:
                response = {
                    "error": f"Tool '{tool_name}' not found.",
                    "request": request,
                }
            else:
                try:
                    tool_function = tools[tool_name]
                    result = tool_function(**params)
                    response = {"result": result}
                except Exception as e:
                    response = {
                        "error": f"Error executing tool '{tool_name}': {e}",
                        "request": request,
                    }

            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

        except json.JSONDecodeError:
            error_response = {"error": "Invalid JSON format."}
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()
        except Exception as e:
            error_response = {"error": f"An unexpected error occurred: {e}"}
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()
            # In case of a severe error, we might want to break the loop
            break

if __name__ == "__main__":
    # Example of how to use it:
    # echo '{"tool": "ping", "params": {"value": "hello stdio"}}' | python mcp_stdio.py
    asyncio.run(run_stdio_loop())