# mcp_server.py

import asyncio
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from uvicorn import Server, Config

import config
from agent_core import AgentCore

app = FastAPI(
    title=config.AGENT_NAME,
    version=config.AGENT_VERSION,
)

# Instantiate the core agent logic
agent_core = AgentCore()
tools = agent_core.get_tools()

@app.get("/")
async def root():
    """
    Root endpoint to get agent capabilities.
    """
    return JSONResponse(content=agent_core.get_capabilities())

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """
    Main MCP endpoint for tool calls.
    """
    try:
        data = await request.json()
        tool_name = data.get("tool")
        params = data.get("params", {})

        if not tool_name:
            raise HTTPException(status_code=400, detail="'tool' field is required.")

        if tool_name not in tools:
            raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found.")

        # Execute the tool
        tool_function = tools[tool_name]
        result = tool_function(**params)

        return JSONResponse(content={"result": result})

    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/mcp/sse")
async def mcp_sse_endpoint():
    """
    MCP endpoint for Server-Sent Events (SSE).
    This is a placeholder for streaming responses.
    """
    async def event_stream():
        # In a real implementation, this would subscribe to an event source
        # from the agent core and yield events.
        for i in range(5):
            await asyncio.sleep(1)
            yield f"data: {json.dumps({'event': 'ping', 'value': i})}\n\n"
        yield f"data: {json.dumps({'event': 'close'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

async def run_server():
    """
    Asynchronously run the Uvicorn server.
    """
    if config.ENABLE_HTTP:
        server_config = Config(
            app,
            host=config.HTTP_HOST,
            port=config.HTTP_PORT,
            log_level="info",
        )
        server = Server(server_config)
        print(f"MCP HTTP/SSE Server running on http://{config.HTTP_HOST}:{config.HTTP_PORT}")
        await server.serve()
    else:
        print("MCP HTTP/SSE Server is disabled.")

if __name__ == "__main__":
    # This is for direct execution.
    # The main entry point will be main.py
    asyncio.run(run_server())
