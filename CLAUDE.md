# Jarvis - Personal AI Assistant

You are helping build and maintain **Jarvis**, a local personal AI assistant for Ibrahim's Windows PC.

## Project Goal

A hybrid Jarvis inspired by:
- **lukebuildsai** / **chandlerintelligence**: Claude + MCP + memory
- **fatihmakes**: Voice control, PC automation, plugin system
- **adam.godigital**: Claude brain + MCP hands + TTS voice

## Architecture

```
main.py              → Entry point (text or voice mode)
jarvis/brain.py      → Claude/Gemini AI with tool calling
jarvis/voice.py      → Speech recognition + Edge TTS
jarvis/memory.py     → Persistent memory across sessions
jarvis/tools/        → PC control (apps, web, volume, system)
plugins/             → Drop-in Python plugins (FatihMakes pattern)
config/              → Settings and API keys
data/                → Runtime memory storage
```

## Conventions

- Python 3.11+
- Keep spoken responses short (1-3 sentences)
- New capabilities go in `plugins/` or `jarvis/tools/`
- API keys in `.env` or `config/api_keys.json` (never commit)
- Phase 1: functional core. Phase 2: MCP tools. Phase 3: HUD UI.

## User

- Name: Ibrahim
- OS: Windows 10
- Workspace: C:\Users\hp\Desktop\nexus\jarvis

## Commands

```bash
python main.py        # Text mode
python main.py voice  # Voice mode (microphone)
```
