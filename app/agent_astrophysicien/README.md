# MCP Agent Template

This directory contains a reusable template for creating specialized MCP (Model-Context-Protocol) agents within the Nokido ecosystem. It provides the necessary boilerplate for communication over HTTP, Server-Sent Events (SSE), and STDIO.

## Structure

- `main.py`: The main entry point for the agent. It parses command-line arguments to determine the communication mode (`server` or `stdio`).
- `config.py`: Configuration file for the agent. Here you can set the agent's name, version, and communication settings.
- `agent_core.py`: This is the heart of your agent. You should implement your agent's specific logic and tools in this file.
- `mcp_server.py`: A FastAPI server that exposes the agent's tools over HTTP and SSE. You generally won't need to modify this file.
- `mcp_stdio.py`: Handles communication over STDIO. You generally won't need to modify this file.
- `Dockerfile`: A Dockerfile to containerize the agent for easy deployment.
- `README.md`: This file.

## How to Use This Template

1.  **Copy the Template**: Copy this entire directory (`mcp_agent_template`) to a new directory, for example, `LaForge/app/my_specialized_agent`.

2.  **Customize the Configuration**: Open `config.py` and change the `AGENT_NAME` and other settings as needed.

3.  **Implement Your Agent's Logic**:
    - Open `agent_core.py`.
    - Modify the `AgentCore` class to add your agent's specific logic.
    - Add new methods that will become your agent's tools.
    - In the `get_tools` method, add your new methods to the dictionary to expose them as tools. The key is the tool name (as called by the MCP client), and the value is the method itself.

    ```python
    # Example of adding a new tool in agent_core.py

    class AgentCore:
        # ... (initialization)

        def get_tools(self):
            return {
                "ping": self.ping,
                "get_capabilities": self.get_capabilities,
                "my_new_tool": self.my_new_tool, # Add your new tool here
            }

        # ... (ping and get_capabilities methods)

        def my_new_tool(self, parameter1: str, parameter2: int = 10) -> dict:
            """
            This is a new tool.
            It takes a string and an optional integer, and returns a dictionary.
            """
            # Implement your logic here
            return {"status": "success", "input": f"{parameter1}, {parameter2}"}
    ```

4.  **Run the Agent**: You can run the agent in two modes:

    - **Server Mode (HTTP/SSE)**:
      ```bash
      python main.py server
      ```
      This will start the FastAPI server. You can then interact with it using an HTTP client.
      - `GET http://127.0.0.1:8999/`: Get agent capabilities.
      - `POST http://127.0.0.1:8999/mcp`: Call a tool.

        **Example Tool Call with `curl`**:
        ```bash
        curl -X POST http://127.0.0.1:8999/mcp -H "Content-Type: application/json" -d '{"tool": "my_new_tool", "params": {"parameter1": "test"}}'
        ```

    - **STDIO Mode**:
      ```bash
      python main.py stdio
      ```
      The agent will listen for JSON requests on standard input and print JSON responses to standard output.

        **Example Tool Call with `echo`**:
        ```bash
        echo '{"tool": "ping", "params": {"value": "hello"}}' | python main.py stdio
        ```

5.  **Build the Docker Image**:
    From the root of the `Nokido` project, run:
    ```bash
    docker build -t my-specialized-agent:latest -f app/my_specialized_agent/Dockerfile .
    ```
    Then run the container:
    ```bash
    docker run -p 8999:8999 my-specialized-agent:latest
    ```
