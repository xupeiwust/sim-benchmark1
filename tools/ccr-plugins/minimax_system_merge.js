// minimax-system-merge — claude-code-router transformer
//
// MiniMax's OpenAI-compat endpoint (api.minimaxi.com/v1/chat/completions)
// rejects requests where any role:system message is NOT the first entry
// in the messages array. The error code is 2013 with message
// "invalid params, chat content has invalid message role: system".
//
// claude-code injects mid-conversation system reminders (skills list,
// safety, etc.) which ccr's Anthropic→OpenAI conversion emits as
// role:system messages spread through the array. MiniMax then 400s.
//
// This transformer runs on the OUTBOUND OpenAI-format request (after
// ccr's internal conversion, before the HTTP send). It:
//   1. Collects every {role:"system"} message in order
//   2. Concatenates their content into one string (string + content-block
//      forms both supported)
//   3. Drops them from their original positions
//   4. Prepends a single merged system message at index 0
//
// No-op if the request has no system messages.

class MinimaxSystemMergeTransformer {
  // ccr expects an INSTANCE property `name` (lowercase). The earlier
  // `static TransformerName` form is for built-in transformers compiled
  // into ccr's bundle, NOT for plugin-loaded ones.
  name = "minimax-system-merge";

  // ccr's `use` chain calls `transformRequestIn(req, provider)` on each
  // transformer in order, after the endpoint transformer (e.g. Anthropic
  // → OpenAI) has already converted the body. `transformRequestOut` is
  // ONLY called on the endpoint transformer itself, not on chain entries.
  //
  // Chain order in ccr config matters: `tooluse` (built-in) appends a
  // late role:system message at the END of `messages` to enforce tool
  // mode. MiniMax then 400s with "invalid message role: system (2013)".
  // This transformer must run AFTER `tooluse` so it sees that injected
  // message and folds it into the first system entry.
  async transformRequestIn(request, _provider) {
    if (!request || !Array.isArray(request.messages)) return request;

    const systemTexts = [];
    const others = [];
    for (const m of request.messages) {
      if (m && m.role === "system") {
        const t = this._asText(m.content);
        if (t) systemTexts.push(t);
      } else {
        others.push(m);
      }
    }

    if (systemTexts.length === 0) return request;

    const merged = { role: "system", content: systemTexts.join("\n\n") };
    return { ...request, messages: [merged, ...others] };
  }

  _asText(content) {
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      return content
        .map(c => (typeof c === "string" ? c : (c && c.text) || ""))
        .filter(Boolean)
        .join("\n");
    }
    return "";
  }
}

module.exports = MinimaxSystemMergeTransformer;
