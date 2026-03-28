# Inebotten Quick Reference

## Start the Bot

```bash
# Everything together (bridge + bot)
python3 run_both.py

# Or separately:
python3 hermes_bridge_server.py  # Terminal 1
python3 selfbot_runner.py        # Terminal 2
```

## Calendar Commands

| What You Want | What to Type |
|---------------|--------------|
| See calendar | `@inebotten kalender` |
| Add event | `@inebotten [event] [when]` |
| Complete item | `@inebotten ferdig [nummer]` |
| Delete item | `@inebotten slett [nummer]` |
| Sync to GCal | `@inebotten sync` |

### Natural Language Examples

```
@inebotten møte med Ola i morgen kl 14
@inebotten husk å ringe mamma på lørdag
@inebotten RBK-kamp 12.04 kl 18:30
@inebotten lunsj hver fredag kl 12
@inebotten bursdag til mamma 15.05 hvert år
```

### Date Keywords

- `i dag`, `idag` - Today
- `i morgen`, `imorgen`, `imårra` - Tomorrow
- `i overmorgen` - Day after tomorrow
- `på mandag`, `neste tirsdag` - Weekdays

## Status Icons

| Icon | Meaning |
|------|---------|
| 📅 | Synced to Google Calendar |
| 📌 | Local only |
| ✓ | Completed |
| 🔄 | Recurring |

## Other Commands

| Feature | Command |
|---------|---------|
| Weather | `@inebotten vær` / `@inebotten været i Oslo` |
| Poll | `@inebotten avstemning Tittel? Alt1, Alt2` |
| Vote | `@inebotten stem [nummer]` |
| Countdown | `@inebotten nedtelling til [dato]` |
| Horoscope | `@inebotten horoskop [stjernetegn]` |
| Crypto | `@inebotten pris BTC` |
| Calculator | `@inebotten kalk [uttrykk]` |
| Quote | `@inebotten sitat` |
| Word of Day | `@inebotten dagens ord` |
| Compliment | `@inebotten kompliment` |

## Chatting

Just mention the bot naturally:

```
@inebotten Hei! Hvordan går det?
@inebotten Hva synes du om RBK?
@inebotten Fortell en vits
```

## File Locations

| Data | Location |
|------|----------|
| Calendar | `~/.hermes/discord/data/calendar.json` |
| User Memory | `~/.hermes/discord/data/user_memory.json` |
| GCal Token | `~/.gcal_token.pickle` |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Bot not responding | Check `run_both.py` output |
| AI not working | Check LM Studio is running on Windows |
| GCal sync fails | Run `python3 sync_calendar_to_gcal.py` |
| "Fant ikke nummer" | Use `@inebotten kalender` first to see numbers |

## Architecture

```
You ──► Discord ──► Message Monitor ──► Command Router
                    │
                    ├──► Calendar Manager ──► data/calendar.json
                    │         │
                    │         └──► Google Calendar API
                    │
                    ├──► Natural Language Parser
                    │
                    ├──► User Memory ──► data/user_memory.json
                    │
                    ├──► Conversation Context
                    │
                    └──► Hermes Connector ──► Hermes Bridge ──► LM Studio
                                                    │
                                                    └──► Local Fallback (if AI down)
```
