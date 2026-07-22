"""
Gateway proxy routes for Entertainment service (/api/v1/entertainment).
Supports JSON APIs plus streaming / M3U / XMLTV passthrough.
"""
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

router = APIRouter(prefix="/api/v1/entertainment", tags=["Entertainment"])
ENT_BASE = "http://entertainment-service:8012"


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def entertainment_proxy(path: str, request: Request):
    url = f"{ENT_BASE}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()
    headers = {}
    if "range" in request.headers:
        headers["Range"] = request.headers["range"]
    if "content-type" in request.headers:
        headers["Content-Type"] = request.headers["content-type"]

    is_stream = path.startswith("stream/")
    timeout = None if is_stream else 120.0

    client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        req = client.build_request(
            request.method,
            url,
            content=body if body else None,
            headers=headers,
        )
        upstream = await client.send(req, stream=is_stream)
    except Exception as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"entertainment-service unavailable: {exc}") from exc

    if not is_stream:
        content = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        if upstream.status_code >= 400:
            raise HTTPException(status_code=upstream.status_code, detail=content.decode("utf-8", errors="ignore"))
        media_type = upstream.headers.get("content-type", "application/json")
        return Response(content=content, status_code=upstream.status_code, media_type=media_type)

    if upstream.status_code >= 400:
        err = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=upstream.status_code, detail=err.decode("utf-8", errors="ignore"))

    media_type = upstream.headers.get("content-type", "application/octet-stream")
    out_headers = {}
    for key in ("content-length", "content-range", "accept-ranges"):
        if key in upstream.headers:
            out_headers[key.title()] = upstream.headers[key]

    async def body_iter():
        try:
            async for chunk in upstream.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body_iter(),
        status_code=upstream.status_code,
        media_type=media_type,
        headers=out_headers,
    )
