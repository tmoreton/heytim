"""Public-address-only MCP transport, including the actual TCP connection."""
from __future__ import annotations

import ipaddress
import socket
import ssl

import anyio
import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self.backend = AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if port != 443:
            raise httpcore.ConnectError("MCP requires HTTPS port 443")
        with anyio.fail_after(timeout):
            addresses = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
                raise httpcore.ConnectError("MCP endpoint must resolve publicly")
            # HTTPcore retains the original origin hostname for TLS SNI/certificate checks.
            return await self.backend.connect_tcp(
                addresses[0][4][0], port, timeout=timeout, local_address=local_address,
                socket_options=socket_options,
            )

    async def connect_unix_socket(self, *args, **kwargs):
        raise httpcore.ConnectError("MCP Unix sockets are unavailable")

    async def sleep(self, seconds):
        await anyio.sleep(seconds)


class CoreStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        total = 0
        try:
            async for chunk in self.stream:
                total += len(chunk)
                if total > 8_000_000:
                    raise httpx.ReadError("MCP response exceeded the size limit")
                yield chunk
        except httpcore.TimeoutException as exc:
            raise httpx.ReadTimeout("MCP response timed out") from exc
        except httpcore.NetworkError as exc:
            raise httpx.ReadError("MCP response could not be read") from exc

    async def aclose(self):
        await self.stream.aclose()


class PublicMCPTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl.create_default_context(), network_backend=PublicNetworkBackend(),
            max_connections=4, max_keepalive_connections=2, retries=0,
        )

    async def handle_async_request(self, request):
        if request.url.scheme != "https" or request.url.port not in {None, 443}:
            raise httpx.ConnectError("MCP requires a public HTTPS endpoint", request=request)
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                             port=request.url.port, target=request.url.raw_path),
            headers=request.headers.raw, content=request.stream, extensions=request.extensions,
        )
        try:
            response = await self.pool.handle_async_request(core_request)
        except (httpcore.TimeoutException, TimeoutError) as exc:
            raise httpx.ConnectTimeout("MCP connection timed out", request=request) from exc
        except (httpcore.NetworkError, httpcore.ProtocolError) as exc:
            raise httpx.ConnectError("MCP connection unavailable", request=request) from exc
        return httpx.Response(response.status, headers=response.headers,
                              stream=CoreStream(response.stream), extensions=response.extensions)

    async def aclose(self):
        await self.pool.aclose()
