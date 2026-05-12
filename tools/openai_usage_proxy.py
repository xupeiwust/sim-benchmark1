"""openai_usage_proxy.py — proxy for an OpenAI-compatible chat-completions
endpoint that (a) recovers per-request token usage data and (b) sanitises
upstream-specific fields that downstream Anthropic-protocol consumers
cannot map to a valid content-block type.

Why this exists. ccr 2.0 has a `streamoptions` transformer that *should*
inject `stream_options.include_usage=true` into outbound OpenAI requests,
but it runs as `transformRequestIn` (mutates the inbound Anthropic body)
and its mutation is dropped by the Anthropic→OpenAI translator. Custom
transformers can't fix this either: ccr's hook surface doesn't expose
`transformRequestOut` for the OpenAI body.

Reasoning-block sanitisation. Reasoning models (MiniMax-M2.7, DeepSeek-R1,
Qwen3-Thinking, ...) emit `reasoning_content` deltas separately from
`content` deltas in their OpenAI-format SSE stream. ccr's OpenAI→Anthropic
response converter forwards these as a non-`text` content block; claude-code
then errors out with `API Error: Content block is not a text block` on
the very first turn that contains a pure-reasoning chunk. The bug
manifests as 1-/5-/11-turn early-exits with stop_reason=stop_sequence.
We strip reasoning_content from every SSE delta before it reaches ccr.
Reasoning is ephemeral anyway (not part of the model's own context after
the turn ends), so dropping it is loss-free for downstream behaviour.

This proxy sits between ccr and the real upstream. It:

  1. Forces `stream_options.include_usage=true` on every streaming request,
     so the upstream returns the per-request token counts in the SSE tail.
  2. Captures the upstream `usage` field as the stream flows back, and
     appends one JSONL record per request to USAGE_LOG. cost_meter.py
     consumes this file to populate agent token counts on ccr-routed trials
     (where Claude Code itself sees `usage: {input_tokens: 0, ...}`).
  3. Strips `reasoning_content` from streaming SSE deltas + non-streaming
     `choices[*].message`, so reasoning models don't break Anthropic-protocol
     downstream consumers.
  4. Otherwise passes the request and response through unchanged — including
     SSE event framing — so it's transparent to ccr's stream parser.

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


def _estimate_prompt_tokens(messages) -> int:
    """Estimate prompt tokens from an OpenAI-format messages array.

    Upstreams like MiniMax M2.5-highspeed return `{"total_tokens": 0,
    "total_characters": 0}` in their SSE final usage event regardless of
    stream_options.include_usage. Without a non-zero input_tokens value,
    Claude Code's auto-compact can't trigger and the conversation grows
    until the upstream itself 400s with "context window exceeds limit".
    We approximate at chars/3 (intentionally pessimistic — over-estimating
    triggers compact a bit early, which is safe; under-estimating lets
    the upstream blow). Counts message bodies, tool calls, and tool
    results, all of which the upstream sees in its rendered prompt.
    """
    if not isinstance(messages, list):
        return 0
    total = 0
    for m in messages:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, str):
            total += len(c)
        elif isinstance(c, list):
            for block in c:
                if isinstance(block, dict):
                    for v in block.values():
                        if isinstance(v, str):
                            total += len(v)
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    total += len(args)
        # Per-message overhead (role markers, separators) ~ 10 chars.
        total += 10
    return total // 3


def _strip_reasoning_content(evt: dict) -> bool:
    """Drop `reasoning_content` from streaming delta or non-streaming message.

    OpenAI-compat upstreams that expose reasoning models emit a separate
    `reasoning_content` field alongside `content` and `tool_calls`.
    ccr's OpenAI→Anthropic translator then forwards this as a content block
    that claude-code refuses with `API Error: Content block is not a text
    block`. Stripping the field before ccr sees it is loss-free at the
    behavioural level — reasoning chunks are not part of the model's
    next-turn context anyway.

    Returns True iff the event was modified.
    """
    modified = False
    for choice in evt.get("choices") or []:
        for key in ("delta", "message"):
            block = choice.get(key)
            if isinstance(block, dict) and "reasoning_content" in block:
                del block["reasoning_content"]
                modified = True
    return modified


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

    # Estimate prompt tokens from the rendered messages. Used to backfill
    # zero usage from upstreams that don't honor include_usage (e.g.
    # MiniMax M2.5-highspeed returns `{"total_tokens": 0}` regardless).
    estimated_prompt = _estimate_prompt_tokens(body.get("messages"))

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
                # Track output-side chars to estimate completion_tokens
                # when the upstream returns zeros.
                completion_chars = 0

                async for chunk in upstream.content.iter_any():
                    buffer += chunk
                    # Emit every complete line; rewrite any `data: <json>` line
                    # whose payload includes a reasoning-content field. SSE
                    # framing (line-delimited, double-newline event separator)
                    # stays valid since we preserve trailing newlines.
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        out = line + b"\n"
                        stripped = line.strip()
                        if stripped.startswith(b"data: "):
                            payload = stripped[6:]
                            if payload and payload != b"[DONE]":
                                try:
                                    evt = json.loads(payload)
                                except json.JSONDecodeError:
                                    evt = None
                                if isinstance(evt, dict):
                                    modified = _strip_reasoning_content(evt)
                                    # Count output chars from streamed deltas.
                                    has_finish_reason = False
                                    for choice in evt.get("choices") or []:
                                        delta = choice.get("delta") or {}
                                        c = delta.get("content")
                                        if isinstance(c, str):
                                            completion_chars += len(c)
                                        for tc in delta.get("tool_calls") or []:
                                            fn = (tc or {}).get("function") or {}
                                            args = fn.get("arguments")
                                            if isinstance(args, str):
                                                completion_chars += len(args)
                                        if choice.get("finish_reason"):
                                            has_finish_reason = True
                                    # CCR's OpenAI→Anthropic stream translator
                                    # `break`s on the finish_reason chunk and
                                    # emits its message_delta from THAT chunk's
                                    # `usage`. MiniMax puts usage in a separate
                                    # trailing chunk that CCR never reads. So
                                    # we must inject usage onto the
                                    # finish_reason chunk for CCR to forward
                                    # it to claude-code's auto-compact logic.
                                    if has_finish_reason:
                                        u = evt.get("usage") if isinstance(evt.get("usage"), dict) else {}
                                        if not u.get("prompt_tokens"):
                                            u["prompt_tokens"] = estimated_prompt
                                        if not u.get("completion_tokens"):
                                            u["completion_tokens"] = completion_chars // 3
                                        if not u.get("total_tokens"):
                                            u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]
                                        evt["usage"] = u
                                        final_usage = u
                                        model = evt.get("model", model)
                                        modified = True
                                    # Backfill the trailing usage-only chunk
                                    # too — costs nothing and keeps the JSONL
                                    # log accurate when upstream returns zero.
                                    elif isinstance(evt.get("usage"), dict):
                                        u = evt["usage"]
                                        if not u.get("prompt_tokens"):
                                            u["prompt_tokens"] = estimated_prompt
                                            modified = True
                                        if not u.get("completion_tokens"):
                                            u["completion_tokens"] = completion_chars // 3
                                            modified = True
                                        if not u.get("total_tokens"):
                                            u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]
                                            modified = True
                                        final_usage = u
                                        model = evt.get("model", model)
                                    if modified:
                                        out = b"data: " + json.dumps(evt).encode() + b"\n"
                        await resp.write(out)

                if buffer:
                    await resp.write(buffer)

                # If upstream sent no usage event at all (some upstreams
                # ignore stream_options.include_usage), synthesize one
                # before EOF so CC's auto-compact still has a signal.
                if final_usage is None:
                    synth = {
                        "prompt_tokens": estimated_prompt,
                        "completion_tokens": completion_chars // 3,
                        "total_tokens": estimated_prompt + completion_chars // 3,
                    }
                    synth_evt = {"usage": synth, "model": model, "choices": []}
                    await resp.write(b"data: " + json.dumps(synth_evt).encode() + b"\n\n")
                    final_usage = synth

                await resp.write_eof()

                _append_usage(final_usage, model)
                return resp

            # ── non-streaming JSON branch ──
            data = await upstream.json()
            if isinstance(data, dict):
                _strip_reasoning_content(data)
                u = data.get("usage")
                if not isinstance(u, dict):
                    u = {}
                    data["usage"] = u
                if not u.get("prompt_tokens"):
                    u["prompt_tokens"] = estimated_prompt
                if not u.get("completion_tokens"):
                    # Estimate from response message bodies.
                    out_chars = 0
                    for ch in data.get("choices") or []:
                        msg = (ch or {}).get("message") or {}
                        c = msg.get("content")
                        if isinstance(c, str):
                            out_chars += len(c)
                        for tc in msg.get("tool_calls") or []:
                            fn = (tc or {}).get("function") or {}
                            args = fn.get("arguments")
                            if isinstance(args, str):
                                out_chars += len(args)
                    u["completion_tokens"] = out_chars // 3
                if not u.get("total_tokens"):
                    u["total_tokens"] = u["prompt_tokens"] + u["completion_tokens"]
                _append_usage(u, data.get("model", body.get("model", "")))
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
