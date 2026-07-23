# Tau Prime compaction and extensions

## Compaction

Tau Prime has adaptive local compaction plus verified provider-native compaction.

- Local strategies: `summary` and `pipelined`.
- Provider-native compaction is explicit and fail-closed for verified OpenAI/Codex endpoints.
- Opaque provider-native state is stored in `CompactionEntry.details` and replayed only for compatible provider/model/base URL.
- Do not summarize or expose opaque provider-native sentinels as human-readable context.
- `/compaction` controls provider-native enablement and local strategy in the TUI.

## Extension runtime

Tau Prime supports a safe Python extension seam from `.tau/extensions` and `.agents/extensions`.

Current extension features:

- tools
- slash commands
- prompt guidelines
- input hooks
- agent event listeners
- lifecycle listeners
- tool call/result hooks
- custom message, tool call, and tool result renderer seams

Full Textual component slots, main views, and key interceptors are deliberately deferred until mobile/a-Shell behavior is reviewed.

## Event protocol

Tau Prime emits Pi-shaped `message_update` events with assistant sub-events while retaining legacy Tau events for compatibility. The TUI adapter consumes `message_update` as the primary assistant stream.
