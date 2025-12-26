import asyncio
import logger
from mcrcon import MCRcon

class RCONAdapter:
    def __init__(self, host, port, password):
        self.host = host
        self.port = int(port)
        self.password = password

    async def send_command(self, command: str) -> str:
        """
        Sends an RCON command asynchronously using mcrcon.
        """
        try:
            # MCRcon is synchronous, so we run it in an executor
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, self._send_sync, command)
            return response
        except Exception as e:
            logger.error(f"RCON Error: {e}")
            return f"Error: {e}"

    def _send_sync(self, command: str) -> str:
        try:
            with MCRcon(self.host, self.password, port=self.port, timeout=10) as mcr:
                resp = mcr.command(command)
                return resp
        except Exception as e:
            logger.error(f"RCON Sync Error: {e}")
            raise e
