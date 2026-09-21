import asyncio
import gzip
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from api_sentinel.admission import Admission
from api_sentinel.erp import ERP
from api_sentinel.errors import Problem


def test_admission_rejects_immediately_and_releases_on_failure() -> None:
    admission = Admission(2, "tenant", 1)
    with admission.enter(1):
        with pytest.raises(Problem) as error:
            with admission.enter(1):
                pass
        assert error.value.status == 503
        with admission.enter(2):
            assert admission.active == 2
    assert admission.active == 0
    assert admission.tenants == {}


@pytest.mark.asyncio
async def test_cancellation_releases_admission() -> None:
    admission = Admission(1, "tenant")
    started = asyncio.Event()

    async def work() -> None:
        with admission.enter():
            started.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(work())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert admission.active == 0


@pytest.mark.asyncio
async def test_erp_rejects_schema_and_never_follows_redirects() -> None:
    seen: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://controlled.invalid/"})

    erp = ERP("http://local.test")
    await erp.client.aclose()
    erp.client = httpx.AsyncClient(
        base_url="http://local.test", transport=httpx.MockTransport(respond), follow_redirects=False
    )
    try:
        with pytest.raises(Problem) as error:
            await erp.availability(1, "SKU-001")
        assert error.value.code == "erp_status"
        assert seen == ["http://local.test/availability/1/SKU-001"]
    finally:
        await erp.close()


class Trickle(httpx.AsyncByteStream):
    async def __aiter__(self):
        for _ in range(30):
            await asyncio.sleep(0.05)
            yield b" "


@pytest.mark.asyncio
async def test_erp_total_deadline_stops_continuous_chunks() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=Trickle())

    erp = ERP("http://local.test")
    await erp.client.aclose()
    erp.client = httpx.AsyncClient(
        base_url="http://local.test", transport=httpx.MockTransport(respond)
    )
    started = asyncio.get_running_loop().time()
    try:
        with pytest.raises(Problem) as error:
            await erp.availability(1, "SKU-001")
        assert error.value.status == 504
        assert asyncio.get_running_loop().time() - started < 1.2
        assert erp.admission.active == 0
    finally:
        await erp.close()


@pytest.mark.asyncio
async def test_erp_rejects_large_actual_body() -> None:
    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-length": "1"},
            content=json.dumps({"data": "x" * 9000}),
        )

    erp = ERP("http://local.test")
    await erp.client.aclose()
    erp.client = httpx.AsyncClient(
        base_url="http://local.test", transport=httpx.MockTransport(respond)
    )
    try:
        with pytest.raises(Problem) as error:
            await erp.availability(1, "SKU-001")
        assert error.value.code == "erp_response_size"
    finally:
        await erp.close()


class ERPBody(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read_count = 0
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.read_count += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "identity, gzip", "gzip, identity"])
async def test_erp_refuses_compression_before_reading(encoding: str) -> None:
    stream = ERPBody([gzip.compress(b" " * 1_000_000)])

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": encoding},
            stream=stream,
        )

    erp = ERP("http://local.test")
    await erp.client.aclose()
    erp.client = httpx.AsyncClient(
        base_url="http://local.test", transport=httpx.MockTransport(respond)
    )
    try:
        with pytest.raises(Problem) as error:
            await erp.availability(1, "SKU-001")
        assert error.value.status == 502
        assert error.value.code == "erp_contract"
        assert stream.read_count == 0
        assert stream.closed
        assert erp.admission.active == 0
    finally:
        await erp.close()


@pytest.mark.parametrize("extra_byte", [False, True])
async def test_erp_response_limit_across_chunks_closes_stream(extra_byte: bool) -> None:
    expected = {"store_id": 1, "sku": "SKU-001", "available": 3}
    body = json.dumps(expected).encode().ljust(8192, b" ")
    chunks = [body[:4096], body[4096:] + (b" " if extra_byte else b"")]
    if extra_byte:
        chunks.append(b"must not be read")
    stream = ERPBody(chunks)

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": "identity"},
            stream=stream,
        )

    erp = ERP("http://local.test")
    await erp.client.aclose()
    erp.client = httpx.AsyncClient(
        base_url="http://local.test", transport=httpx.MockTransport(respond)
    )
    try:
        if extra_byte:
            with pytest.raises(Problem) as error:
                await erp.availability(1, "SKU-001")
            assert error.value.code == "erp_response_size"
        else:
            assert await erp.availability(1, "SKU-001") == expected
        assert stream.read_count == 2
        assert stream.closed
        assert erp.admission.active == 0
    finally:
        await erp.close()
