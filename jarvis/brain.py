"""AI brain with agent mode - plans and executes real PC actions."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from dotenv import load_dotenv

from jarvis.agent import Agent
from jarvis.fast_router import try_fast_command
from jarvis.tools.api_hunter import fetch_api_key
from jarvis.tools.api_intent import is_api_hunt_intent
from jarvis.tools.api_pipeline import count_apis_from_sheet, is_api_count_command
from jarvis.memory import Memory
from jarvis.tools import system

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Hard wall-clock for agent+LLM so HUD never hangs forever
_AGENT_TIMEOUT_S = 18.0
_llm_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="jarvis-llm")

PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "qwen/qwen3.8-27b",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "openrouter/free",
        "extra_headers": {
            "HTTP-Referer": "https://github.com/jarvis-local",
            "X-Title": "Jarvis Assistant",
        },
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
        "model_env": "NVIDIA_MODEL",
        "default_model": "meta/llama-3.1-8b-instruct",
    },
}


class Brain:
    def __init__(self, memory: Memory, assistant_name: str = "Jarvis", user_name: str = "sir") -> None:
        self.memory = memory
        self.assistant_name = assistant_name
        self.user_name = user_name
        self.provider = os.getenv("JARVIS_AI_PROVIDER", "auto").lower()
        self._keys: dict[str, str] = {}
        self._load_keys()
        self._agent = Agent(self._call_llm, self.memory.remember_fact)

    def _load_keys(self) -> None:
        for name, cfg in PROVIDERS.items():
            self._keys[name] = os.getenv(cfg["key_env"], "")
        self._keys["anthropic"] = os.getenv("ANTHROPIC_API_KEY", "")
        self._keys["gemini"] = os.getenv("GEMINI_API_KEY", "")

        keys_path = ROOT / "config" / "api_keys.json"
        if keys_path.exists():
            try:
                data = json.loads(keys_path.read_text(encoding="utf-8"))
                for k, v in data.items():
                    if v and not self._keys.get(k):
                        self._keys[k] = v
            except (json.JSONDecodeError, OSError):
                pass

    @staticmethod
    def _gemini_importable() -> bool:
        cached = getattr(Brain, "_gemini_ok", None)
        if cached is not None:
            return bool(cached)
        try:
            import google.generativeai  # noqa: F401
            Brain._gemini_ok = True
            return True
        except ImportError:
            Brain._gemini_ok = False
            return False

    def _available_providers(self) -> list[str]:
        """Groq first (fast path). Gemini is last so we never wait on it when Groq works."""
        have = [
            p for p in ("groq", "openrouter", "nvidia", "anthropic", "gemini")
            if self._keys.get(p)
        ]
        if "gemini" in have and not self._gemini_importable():
            have.remove("gemini")
        if not have:
            return []

        preferred = self.provider if self.provider != "auto" else None
        # Groq → OpenRouter → NVIDIA → Anthropic → Gemini (slow / flaky last)
        order = ["groq", "openrouter", "nvidia", "anthropic", "gemini"]
        if preferred and preferred in have and preferred != "auto":
            rest = [p for p in order if p in have and p != preferred]
            return [preferred] + rest
        return [p for p in order if p in have]

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        err = str(exc).lower()
        return (
            "429" in err
            or "rate_limit" in err
            or "rate limit" in err
            or "quota" in err
            or "resource_exhausted" in err
        )

    def _call_llm(self, system_msg: str, user_text: str) -> str:
        providers = self._available_providers()
        if not providers:
            raise RuntimeError("No API key configured")

        last_error = ""
        # Cap fallbacks — do not chain every provider into a 40s hang
        for provider in providers[:2]:
            try:
                if provider in PROVIDERS:
                    return self._ask_openai_compatible(provider, system_msg, user_text)
                if provider == "anthropic":
                    return self._ask_claude(system_msg, user_text)
                if provider == "gemini":
                    return self._ask_gemini(system_msg, user_text)
            except ImportError:
                # Missing SDK (e.g. google.generativeai) — skip silently
                continue
            except Exception as exc:
                err = str(exc)
                if "no module named" in err.lower():
                    continue
                last_error = f"{provider}: {exc}"
                continue
        raise RuntimeError(last_error or "All providers failed")

    def _ask_openai_compatible(self, provider: str, system_msg: str, user_text: str) -> str:
        from openai import OpenAI

        cfg = PROVIDERS[provider]
        model = os.getenv(cfg["model_env"], cfg["default_model"])
        # Short client timeout — never hang the HUD waiting on a slow brain
        timeout_s = 8.0 if provider == "groq" else 10.0
        client = OpenAI(
            api_key=self._keys[provider],
            base_url=cfg["base_url"],
            timeout=timeout_s,
            max_retries=0,
        )
        extra = cfg.get("extra_headers", {})
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=64,
                temperature=0.2,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_text},
                ],
                extra_headers=extra if extra else None,
            )
        except Exception as exc:
            # Re-raise so _call_llm can fall through to next provider
            raise RuntimeError(f"{provider} failed: {exc}") from exc
        return response.choices[0].message.content or ""

    def _ask_claude(self, system_msg: str, user_text: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self._keys["anthropic"], timeout=10.0)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=120,
            system=system_msg,
            messages=[{"role": "user", "content": user_text}],
        )
        return message.content[0].text

    def _ask_gemini(self, system_msg: str, user_text: str) -> str:
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise ImportError("gemini sdk missing") from exc

        genai.configure(api_key=self._keys["gemini"])
        model = genai.GenerativeModel("gemini-2.0-flash", system_instruction=system_msg)
        # Cap wait — Gemini is last-resort and must not block forever
        return model.generate_content(
            user_text,
            generation_config={"max_output_tokens": 80, "temperature": 0.2},
            request_options={"timeout": 8},
        ).text or ""

    def think(self, user_text: str) -> str:
        user_text = user_text.strip()
        if not user_text:
            return "I didn't catch that, sir."

        lower = user_text.lower()
        if lower in ("what time is it", "what's the time", "tell me the time"):
            return system.get_time()
        if "system status" in lower or "how is my computer" in lower:
            return system.get_system_status()
        if "cancel shutdown" in lower:
            return system.cancel_shutdown()

        # Simple remember FIRST — never LLM, never provider imports
        rem = user_text.strip()
        low = rem.lower()
        if low.startswith("remember that ") or (
            low.startswith("remember ")
            and "http://" not in low
            and "https://" not in low
            and "sheet" not in low
        ):
            fact = rem.split(" ", 1)[1] if " " in rem else rem
            if fact.lower().startswith("that "):
                fact = fact[5:]
            fact = fact.strip(" .")
            if fact:
                self.memory.remember_fact(fact)
                reply = f"I'll remember that, sir: {fact}."
                self.memory.add_conversation(user_text, reply)
                return reply

        # Instant intents — never touch the LLM
        if is_api_hunt_intent(user_text):
            return fetch_api_key(user_text)

        if is_api_count_command(user_text):
            return count_apis_from_sheet(user_text)

        from jarvis.tools.mira_tool import try_mira_command

        mira = try_mira_command(user_text, background=True)
        if mira:
            self.memory.add_conversation(user_text, mira)
            return mira

        fast = try_fast_command(user_text)
        if fast:
            self.memory.add_conversation(user_text, fast)
            return fast

        if not self._available_providers():
            return (
                "I need an API key to operate fully, sir. "
                "Add GROQ_API_KEY or GEMINI_API_KEY to .env. "
                "See FREE_API_KEYS.md."
            )

        try:
            fut = _llm_pool.submit(self._agent.run, user_text, self.memory.get_context_prompt())
            final = fut.result(timeout=_AGENT_TIMEOUT_S)
        except FuturesTimeout:
            return (
                "The AI brain is slow right now, sir. "
                "Try again, or use instant commands like time, open Chrome, or API hunts."
            )
        except Exception as exc:
            err = str(exc).lower()
            if self._is_rate_limit(exc):
                return (
                    "All AI brains are rate-limited right now, sir. "
                    "Instant commands still work — open apps, YouTube, API hunts, human view."
                )
            if "timeout" in err or "timed out" in err:
                return (
                    "The AI brain is slow right now, sir. "
                    "Try again, or use instant commands like time, open Chrome, or API hunts."
                )
            # Never leak raw ImportError / provider module names to the HUD
            return (
                "I'm having trouble connecting to my neural network, sir. "
                "Instant commands still work — time, volume, sheets, API keys."
            )

        self.memory.add_conversation(user_text, final)
        return final
