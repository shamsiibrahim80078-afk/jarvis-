# Jarvis - Personal AI Assistant

A local Jarvis for Windows — voice control, PC automation, persistent memory, and AI brain (Claude/Gemini).

Inspired by the Instagram builds from **lukebuildsai**, **fatihmakes**, **chandlerintelligence**, and **adam.godigital**.

## Quick Start

### 1. Add your API key (required for AI conversations)

Copy `.env.example` to `.env` and add **at least one** key:

```env
# Free option — get key at https://aistudio.google.com/apikey
GEMINI_API_KEY=your_key_here

# Or Claude — https://console.anthropic.com/
ANTHROPIC_API_KEY=your_key_here
```

### 2. Run Jarvis

**Text mode** (type commands):
```
start.bat
```
or
```
.venv\Scripts\python.exe main.py
```

**Voice mode** (microphone):
```
start-voice.bat
```
or
```
.venv\Scripts\python.exe main.py voice
```

## What works right now (Phase 1)

| Feature | Status |
|---------|--------|
| Voice output (Edge TTS, British Jarvis voice) | Working |
| Voice input (microphone) | Working |
| Text chat mode | Working |
| Tell time / system status | Working (no API key needed) |
| Open apps (Chrome, Notepad, etc.) | Working with API key |
| Web search / open websites | Working with API key |
| Volume control | Working with API key |
| Persistent memory | Working |
| Plugin system | Working (`plugins/` folder) |
| MCP servers for Cursor | Configured (`.cursor/mcp.json`) |

## Try these commands

- "What time is it?"
- "How is my computer?"
- "Open Chrome"
- "Search the web for Python tutorials"
- "Remember that I prefer dark mode"
- "Good morning" (plugin)

## Project structure

```
jarvis/
  main.py              # Start here
  jarvis/
    brain.py           # Claude/Gemini AI
    voice.py           # Speech in/out
    memory.py          # Remembers you across sessions
    tools/system.py    # PC control
  plugins/             # Drop .py files to add skills
  config/              # Settings
  data/                # Memory storage
  CLAUDE.md            # Cursor/Claude Code instructions
  .cursor/mcp.json     # MCP tools for Cursor
```

## MCP servers (for Cursor IDE)

Already configured in `.cursor/mcp.json`:
- **filesystem** — read/write project files
- **memory** — persistent MCP memory
- **brave-search** — web search (add `BRAVE_API_KEY` to enable)

Restart Cursor after first run so MCP servers load.

## Next phases

- **Phase 2**: Gmail, Calendar, YouTube upload, WhatsApp plugins
- **Phase 3**: Iron Man HUD dashboard UI
