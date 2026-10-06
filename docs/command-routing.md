# One catalogue and inert routing preview

`core/command_registry.py` contains one immutable `CommandSpec` per `BotIntent`:
alias metadata, examples, description, mutation/scope requirements, a curated
handler binding and bounded payload validation. Alias metadata is descriptive;
only `IntentRouter.route()` parses text and determines precedence. Numeric
reminder completion still precedes poll votes, explicit commands still precede
natural-language inference and existing confidence thresholds stay unchanged.

`IntentRouter.preview_route(text, actor)` reuses that parser under an immutable
request context and returns intent/confidence/reason/threshold, validated fields
and required policy. Text is bounded to 4,000 characters. Preview never calls a
handler, provider or writer, never reserves send quota, and never updates intent
counters or conversation history. Auth codes and raw parser error fields are
withheld. Results depend on the current read-only routing state (for example,
whether the channel has active reminders/polls) and are not a future mutation
preview or an authorization decision. `accepted` means payload and route threshold
are acceptable; `authoritative_permission: false` makes that limit explicit.
The real mention/controller gate and current domain permissions remain required
at execution, as do item revision/ID/actor confirmation checks in domain handlers.

The catalogue's `dispatch_command()` resolves only its curated binding; input
cannot select a handler or another user's memory. Nested payloads have byte,
node/depth/type bounds and actual domain validation remains authoritative. Help
pages, console command reference and `docs/COMMANDS.md` use the same descriptions
and examples. Regenerate/check the Markdown using:

```sh
python scripts/write_command_reference.py
python scripts/write_command_reference.py --check
```

When adding a command, extend `BotIntent`, its existing router branch, the
catalogue binding/payload schema and positive/negative routing fixtures together.
Do not add a separate preview parser or parsing in `MessageMonitor`.
