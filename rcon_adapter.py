import asyncio
import struct
import logger

# Source RCON Constants
SERVERDATA_AUTH = 3
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_RESPONSE_VALUE = 0

class AsyncRCON:
    def __init__(self, host, port, password, timeout=10.0):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout
        self.reader = None
        self.writer = None
        self._seq = 0

    async def connect(self):
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=self.timeout
        )

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except:
                pass
        self.reader = None
        self.writer = None

    async def _send_packet(self, packet_type, body):
        self._seq += 1
        packet_id = self._seq

        # Packet Structure: Size(4), ID(4), Type(4), Body(null-term), Empty(null-term)
        # Size = 4 (ID) + 4 (Type) + len(body) + 1 (null) + 1 (null)
        body_bytes = body.encode('utf-8')
        size = 4 + 4 + len(body_bytes) + 2

        # Little-endian integers
        packet = struct.pack('<iii', size, packet_id, packet_type) + body_bytes + b'\x00\x00'
        self.writer.write(packet)
        await self.writer.drain()
        return packet_id

    async def _read_packet(self):
        # Read Size (4 bytes)
        size_bytes = await self.reader.readexactly(4)
        size = struct.unpack('<i', size_bytes)[0]

        # Read Remaining Packet
        data = await self.reader.readexactly(size)

        # Unpack ID(4), Type(4)
        packet_id, packet_type = struct.unpack('<ii', data[:8])

        # Body is the rest, excluding the last 2 null bytes (usually)
        # But wait, data is `ID + Type + Body + Null + Null`
        # Let's extract body carefully.
        # Body starts at offset 8. Ends at size - 2?
        # Standard says Body is null terminated, then Empty string null terminated.
        # So we split by null?
        raw_body = data[8:]
        # Remove trailing nulls
        body = raw_body.split(b'\x00')[0].decode('utf-8', errors='replace')

        return packet_id, packet_type, body

    async def authenticate(self):
        packet_id = await self._send_packet(SERVERDATA_AUTH, self.password)

        # Read Response
        resp_id, resp_type, resp_body = await self._read_packet()

        # Check Auth Failure (ID = -1)
        if resp_id == -1:
            raise Exception("Authentication Failed (Bad Password)")

        # Sometimes connection sends an empty packet before auth response?
        # But usually for Auth, we get Auth Response.
        # Note: If we get ID matching packet_id and Type 2, we are good.
        if resp_id == packet_id and resp_type == SERVERDATA_AUTH_RESPONSE:
            return True

        # If we got something else, try reading again (sometimes servers send junk)
        # But for simple logic, let's assume auth packet is the first important one.
        # Wait, Source RCON might send a "Response Value" packet first if we re-connected fast?
        # Let's verify ID.
        if resp_id != packet_id:
             # Try one more read?
             resp_id, resp_type, resp_body = await self._read_packet()
             if resp_id == -1: raise Exception("Authentication Failed")
             if resp_id == packet_id and resp_type == SERVERDATA_AUTH_RESPONSE: return True

        return False

    async def send_command_raw(self, command):
        packet_id = await self._send_packet(SERVERDATA_EXECCOMMAND, command)

        # Read Response
        # Ark RCON (and Source) might split packets.
        # But typically we read until we get a response with ID matching.
        # However, EXECCOMMAND response ID is matching the request ID.
        # Type should be 0 (RESPONSE_VALUE).

        try:
            resp_id, resp_type, resp_body = await asyncio.wait_for(self._read_packet(), timeout=self.timeout)

            # Note: Server might send multiple packets.
            # Usually we handle "Multi-packet response" logic.
            # But "GiveItem" usually returns one packet or empty packet.

            if resp_id == packet_id and resp_type == SERVERDATA_RESPONSE_VALUE:
                return resp_body

            # If ID doesn't match, maybe it's an old packet?
            # Ignore?
            return resp_body # Return whatever we got for now

        except asyncio.TimeoutError:
            # Timeout implies either no response (success?) or lag.
            # We return a specific string to indicate this.
            return "Command Sent (No Output)"

class RCONAdapter:
    def __init__(self, host, port, password):
        self.host = host
        self.port = port
        self.password = password

    async def send_command(self, command: str) -> str:
        client = AsyncRCON(self.host, self.port, self.password)
        try:
            await client.connect()
            await client.authenticate()
            response = await client.send_command_raw(command)
            return response
        except Exception as e:
            logger.error(f"Async RCON Error: {e}")
            return f"Error: {e}"
        finally:
            await client.close()
