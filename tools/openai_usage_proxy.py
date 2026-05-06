"""openai_usage_proxy.py — minimal pass-through proxy for an OpenAI-compatible
chat-completions endpoint that recovers per-request token usage data that
intermediate routers (e.g. claude-code-router) drop.

Why this exists. ccr 2.0 has a `streamoptions` transformer that *should*
inject `stream_options.include_usage=true` into outbound OpenAI requests,
but it runs as `transformRequestIn` (mutates the inbound Anthropic body)
and its mutation is dropped by the Anthropic→OpenAI translator. Custom
transformers can't fix this either: ccr's hook surface doesn't expose
`transformRequestOut` for the OpenAI body. Verified empirically by probing
ccr's transformer pipeline with markers — see
sim-benchmark/IMPROVEMENTS.md for the trace.

This proxy sits between ccr and the real upstream. It:

  1. Forces `stream_options.include_usage=true` on every streaming request,
     so the upstream returns the per-request token counts in the SSE tail.
  2. Captures the upstream `usage` field as the stream flows back, and
     appends one JSONL record per request to USAGE_LOG. cost_meter.py
     consumes this file to populate agent token counts on ccr-routed trials
     (where Claude Code itself sees `usage: {input_tokens: 0, ...}`).
  3. Otherwise passes the request and response through unchanged — including
     SSE chunk boundaries — so it's transparent to ccr's stream parser.

Usage:
  UPSTREAM_BASE=https://llmapi.paratera.com/v1/chat/completions \\
  UPSTREAM_KEY=sk-... \\
  UPSTREAM_PROXY_PORT=3457 \\
  USAGE_LOG=/logs/agent/proxy-usage.jsonl \\
  python3 tools/openai_usage_proxy.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

# Claude Code injects a per-request random `cch=<5-hex>` token into the
# `x-anthropic-billing-header` line of the first system message. On Anthropic
# native that's harmless (caching uses cache_control markers). But on
# OpenAI-compat upstreams (paratera) caching is pure prefix matching — and
# the cch breaks the prefix at byte ~143 of every request, killing all
# downstream cache potential. Empirically this turned a 0% hit rate into
# 90%+ on cavity_re100 trials. Stripping is safe: cch is metadata for
# Anthropic's own billing pipeline, not for the upstream provider.
_CCH_PATTERN = re.compile(r"cch=[a-f0-9]+")


def _strip_cache_busters(body: dict) -> None:
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return
    for m in msgs:
        c = m.get("content")
        if isinstance(c, str):
            m["content"] = _CCH_PATTERN.sub("cch=stable", c)
        elif isinstance(c, list):
            for block in c:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    block["text"] = _CCH_PATTERN.sub("cch=stable", block["text"])

UPSTREAM_BASE = os.environ.get("UPSTREAM_BASE", "")
UPSTREAM_KEY = os.environ.get("UPSTREAM_KEY", "")
PORT = int(os.environ.get("UPSTREAM_PROXY_PORT", "3457"))
USAGE_LOG = Path(
    os.environ.get(
        "USAGE_LOG",
        str(Path.home() / ".openai-usage-proxy" / "usage.jsonl"),
    )
)


def _append_usage(usage: dict, model: str) -> None:
    record = {"ts": time.time(), "model": model, "usage": usage}
    try:
        USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with USAGE_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        # Never let logging break the proxy path.
        print(f"[proxy] usage log write failed: {exc}", file=sys.stderr)


async def handle_completions(request: web.Request) -> web.StreamResponse:
    raw = await request.read()
    try:
        body = json.loads(raw)
    except Exception:
        return web.Response(status=400, text="invalid JSON in request body")

    # Inject include_usage for streaming requests; non-streaming responses
    # already carry `usage` natively.
    if body.get("stream") is True:
        opts = body.setdefault("stream_options", {})
        opts["include_usage"] = True

    # Normalize per-request cache-busting tokens (see _strip_cache_busters).
    _strip_cache_busters(body)

    headers_out = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {UPSTREAM_KEY}",
    }

    timeout = ClientTimeout(total=600)
    async with ClientSession(timeout=timeout) as session:
        async with session.post(UPSTREAM_BASE, json=body, headers=headers_out) as upstream:
            content_type = upstream.headers.get("content-type", "")

            # ── streaming SSE branch ──
            if "text/event-stream" in content_type:
                resp = web.StreamResponse(
                    status=upstream.status,
                    headers={"Content-Type": content_type},
                )
                await resp.prepare(request)

                final_usage: dict | None = None
                model = body.get("model", "")
                buffer = b""

                async for chunk in upstream.content.iter_any():
                    # Pass-through immediately so the downstream stream parser
                    # (ccr) sees byte-identical chunks.
                    await resp.write(chunk)

                    # Sniff for usage in any complete `data: …\n` line.
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if not line.startswith(b"data: "):
                            continue
                        payload = line[6:].strip()
                        if not payload or payload == b"[DONE]":
                            continue
                        try:
                            evt = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(evt.get("usage"), dict):
                            final_usage = evt["usage"]
                            model = evt.get("model", model)

                await resp.write_eof()

                if final_usage:
                    _append_usage(final_usage, model)

                return resp

            # ── non-streaming JSON branch ──
            data = await upstream.json()
            if isinstance(data, dict) and isinstance(data.get("usage"), dict):
                _append_usage(data["usage"], data.get("model", body.get("model", "")))
            return web.json_response(data, status=upstream.status)


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "upstream": UPSTREAM_BASE})


def main() -> int:
    if not UPSTREAM_BASE or not UPSTREAM_KEY:
        print("UPSTREAM_BASE and UPSTREAM_KEY env vars required", file=sys.stderr)
        return 1
    app = web.Application()
    app.router.add_post("/v1/chat/completions", handle_completions)
    app.router.add_get("/health", health)
    print(f"[proxy] listening 127.0.0.1:{PORT} → {UPSTREAM_BASE}; usage→{USAGE_LOG}")
    web.run_app(app, host="127.0.0.1", port=PORT, access_log=None, print=lambda _: None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
