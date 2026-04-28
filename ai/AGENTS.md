# ai/ — AI Layer

Connectors to LM Studio (local) and OpenRouter (cloud), bridge server, response generation, and personality.

## STRUCTURE

```
ai/
├── hermes_bridge_server.py    # HTTP bridge between bot and LM Studio (~826 lines)
├── connector_factory.py       # Creates AI connector (LM Studio or OpenRouter)
├── openrouter_connector.py    # OpenRouter API client
├── hermes_connector.py        # LM Studio / local API client
├── response_generator.py      # Local fallback response templates
├── response_cleaner.py        # Post-processing for AI responses
├── personality_config.py      # Character configuration
├── conversational_responses.py # Fallback conversational logic
└── system_prompt*.txt         # System prompts for AI
```

## WHERE TO LOOK

| Task | File |
|------|------|
| Switch AI provider | `connector_factory.py` + `core/config.py` |
| Change bridge behavior | `hermes_bridge_server.py` |
| Change OpenRouter model | `core/config.py` — `OPENROUTER_MODEL` |
| Change fallback responses | `response_generator.py` |
| Change bot personality | `personality_config.py` + `system_prompt*.txt` |
| Clean AI output | `response_cleaner.py` |

## CONVENTIONS

- Bridge runs as a subprocess on port 3000 (configurable via `HERMES_BRIDGE_PORT`)
- Connector factory picks provider based on `AI_PROVIDER` env var (`lm_studio` or `openrouter`)
- Fallback responses used when AI is unreachable
- System prompt is in Norwegian (nynorsk/bokmål mix)

## NOTES

- `hermes_bridge_server.py` is a full aiohttp server that proxies to LM Studio's OpenAI-compatible API
- The bridge can be started standalone or via `run_both.py`
- OpenRouter connector handles model routing, retries, and error fallback
