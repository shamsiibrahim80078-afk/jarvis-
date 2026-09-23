# Free API Keys for Jarvis (No Gemini Required)

Jarvis supports several **free** AI providers. No credit card needed for most.

## Best picks for Jarvis

| Provider | Free limit | Speed | Sign up |
|----------|-----------|-------|---------|
| **Groq** (recommended) | ~1,000 req/day | Fastest | https://console.groq.com/keys |
| **OpenRouter** | 50/day (1000 after $10 top-up) | Good | https://openrouter.ai/keys |
| **NVIDIA NIM** | 40 req/min, no daily cap | Good | https://build.nvidia.com/ |
| **GitHub Models** | Monthly quota | Medium | https://github.com/marketplace/models |
| **Cerebras** | ~1M tokens/day | Very fast | https://cloud.cerebras.ai/ |
| **Mistral** | ~1B tokens/month | Good | https://console.mistral.ai/ |

## Quick setup (Groq — easiest)

1. Go to https://console.groq.com/keys
2. Sign up with email (no credit card)
3. Create API key
4. Open `.env` in the jarvis folder and add:

```env
GROQ_API_KEY=gsk_your_key_here
JARVIS_AI_PROVIDER=groq
```

5. Run `start.bat`

## OpenRouter setup (most models, one key)

1. Go to https://openrouter.ai/keys
2. Sign up with email or GitHub
3. Create API key (starts with `sk-or-`)
4. Add to `.env`:

```env
OPENROUTER_API_KEY=sk-or-your_key_here
OPENROUTER_MODEL=openrouter/free
JARVIS_AI_PROVIDER=openrouter
```

Free models use `:free` suffix, e.g. `meta-llama/llama-3.3-70b-instruct:free`

## NVIDIA NIM setup

1. Go to https://build.nvidia.com/
2. Sign up for free developer account
3. Generate API key
4. Add to `.env`:

```env
NVIDIA_API_KEY=nvapi-your_key_here
JARVIS_AI_PROVIDER=nvidia
```

## Full list of free providers

GitHub repo (from nick_saraev reel): https://github.com/cheahjs/free-llm-api-resources

## Provider priority in "auto" mode

Jarvis tries in this order:
1. Groq (fast + generous free tier)
2. OpenRouter
3. NVIDIA NIM
4. Claude (if key set)
5. Gemini (if key set)
