# main.py

import argparse
import asyncio
import sys

import config
from mcp_server import run_server
from mcp_stdio import run_stdio_loop

def main():
    """
    Main entry point for the specialized agent.
    Parses command-line arguments to decide which communication mode to start.
    """
    parser = argparse.ArgumentParser(
        description=f"{config.AGENT_NAME} - A Specialized MCP Agent"
    )

    # Determine the default mode. If stdin is a TTY, default to server.
    # Otherwise, default to stdio (e.g., when piped).
    default_mode = "server" if sys.stdin.isatty() else "stdio"

    parser.add_argument(
        "mode",
        nargs="?",
        default=default_mode,
        choices=["server", "stdio"],
        help="The communication mode to run the agent in. "
             "'server' starts an HTTP/SSE server. "
             "'stdio' uses standard input/output for JSON-based communication. "
             "Defaults to 'stdio' if input is piped, otherwise 'server'."
    )

    args = parser.parse_args()

    print(f"Starting {config.AGENT_NAME} v{config.AGENT_VERSION} in '{args.mode}' mode...")

    if args.mode == "server":
        if not config.ENABLE_HTTP and not config.ENABLE_SSE:
            print("ERROR: Both HTTP and SSE are disabled in the configuration.", file=sys.stderr)
            print("Enable at least one to run in 'server' mode.", file=sys.stderr)
            sys.exit(1)
        asyncio.run(run_server())
    
    elif args.mode == "stdio":
        if not config.ENABLE_STDIO:
            print("ERROR: STDIO mode is disabled in the configuration.", file=sys.stderr)
            sys.exit(1)
        asyncio.run(run_stdio_loop())

if __name__ == "__main__":
    main()
