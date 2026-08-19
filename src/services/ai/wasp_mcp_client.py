import asyncio
import os
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class WaspMCPClient:
    """
    Client for Steel Wasp using the MCP (Model Context Protocol) channel.
    Connects via Stdio to the 'mcp_server' rust binary.
    """
    def __init__(self, mcp_bin=None, cwd=None):
        from src.config.settings import Settings
        self.mcp_bin = mcp_bin or "/home/jcoronado/Desktop/dev/steel_wasp/target/debug/mcp_server"
        self.cwd = cwd or "/home/jcoronado/Desktop/dev/steel_wasp"
        self.server_params = StdioServerParameters(
            command=self.mcp_bin,
            args=[],
            cwd=self.cwd
        )
        self.model_name = self._detect_real_model() or "Steel Wasp (MCP)"
        print(f"🧬 [Wasp MCP] Initialized for {self.mcp_bin} @ {self.cwd} (Model: {self.model_name})")

    def _detect_real_model(self):
        """Intenta leer el modelo real desde el config.json de Steel Wasp."""
        try:
            from src.config.settings import Settings
            wasp_cwd = Settings.get_wasp_cwd()
            config_path = os.path.join(wasp_cwd, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    return cfg.get("model")
        except:
            pass
        return None

    async def _async_chat(self, prompt: str) -> str:
        """Internal async implementation of the MCP call."""
        self.model_name = self._detect_real_model() or "Steel Wasp (MCP)"
        try:
            print("   [Wasp MCP] Opening Stdio connection...")
            async with stdio_client(self.server_params) as (read, write):
                print("   [Wasp MCP] Stdio connected. Starting session...")
                async with ClientSession(read, write) as session:
                    print("   [Wasp MCP] Initializing session...")
                    # Initialize the session
                    await asyncio.wait_for(session.initialize(), timeout=30.0)
                    
                    print(f"   [Wasp MCP] Session initialized. Calling tool 'wasp_chat' with prompt: {prompt[:20]}...")
                    # Steel Wasp aparece como una herramienta llamada "wasp_chat"
                    result = await asyncio.wait_for(
                        session.call_tool("wasp_chat", arguments={"prompt": prompt}),
                        timeout=60.0
                    )
                    
                    print("   [Wasp MCP] Tool call completed.")
                    if hasattr(result, 'content') and len(result.content) > 0:
                        return result.content[0].text
                    return "⚠️ [Wasp MCP] Respuesta vacía del servidor."
        except Exception as e:
            return f"❌ [Wasp MCP] Error de comunicación: {str(e)}"

    def chat(self, prompt: str) -> str:
        """
        Synchronous wrapper for the async MCP call.
        Starts the server, calls the tool, and shuts down the server for each call (Stateless).
        """
        try:
            return asyncio.run(self._async_chat(prompt))
        except Exception as e:
            return f"❌ [Wasp MCP] Error en el loop de eventos: {str(e)}"

    def generate_content(self, msg, **kwargs):
        """Compatibility method for standard AI interface."""
        return self.chat(msg)

    def close(self):
        pass
