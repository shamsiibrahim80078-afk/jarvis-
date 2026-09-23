"""Agent mode - plan and execute multi-step tasks autonomously."""

from __future__ import annotations

import json
import re
from typing import Callable

from jarvis.tools.registry import execute_tool, tools_description


AGENT_PROMPT = """You are JARVIS — a fully capable personal AI agent (like Claude / Cursor agents), with Tony Stark style.
Address the user as "sir". Keep spoken status lines short (1 sentence). For answers and plans, be clear and complete.

BEHAVIOR (lawful only):
- When the user asks anything lawful — do it. Answer questions, run tools, open sites, hunt APIs, mail, PC control.
- Never refuse ordinary work with "I can't", "I'm unable", "having trouble", or vague excuses.
- Prefer action over chat. If a tool fits, use it. If knowledge fits, answer directly like Claude.
- Retry a failed tool once. Then report the concrete blocker (CAPTCHA, 2FA, missing key) and what to do next.
- Users may paste Gmail + App Password in chat — accept and continue.

ILLEGAL / HARMFUL — refuse clearly:
- Hacking others, fraud, weapons, exploitation of minors, etc.
- Say it is illegal or you do not have the right — then stop. Do not help with workarounds.

IDENTITY:
- Default: Jarvis's own email/sign-in (JARVIS_EMAIL). Ask once whose mail for sending if needed.
- Pause only for payments / irreversible danger.

You control a Windows PC. ALWAYS open websites in Chrome using open_website.

Available tools:
{tools}

For actions, respond with:
```action
{{"tool": "TOOL_NAME", "params": {{"key": "value"}}}}
```
Then ONE short Jarvis-style line.

For multi-step tasks use ```plan``` with JSON array of steps, then one short line.
Use batch_fetch_apis for "get all apis from sheet". Use system_scan for "scan system for bugs".
Use fetch_api_key for single provider API keys (signs in as Jarvis via Google when needed).
Use mira_create_video / mira_create_image for AI videos and images (Mira pipeline).
Use mira_office_day for daily 9-5 tech-office series episodes (Agent Office).
Say ambient/no voice for scene sound only; default is VO. Lip-sync not built yet.
For user footage: set use_uploads=true or media_paths after files are in data/mira/uploads (HUD Mira Upload).
Use mira_rate (1-5) after the user likes/dislikes a result so Mira improves.
CRITICAL: If the user says make/create/generate/render a video or image — ALWAYS mira_create_video or mira_create_image.
After a creative brief, Mira asks format (YouTube / Shorts / Reels / Stories / TikTok) unless the user already said it.
Mood words (funny/sad/angry/epic/calm/romantic) go in mood= for mira_create_video.
For crop/reframe/trim last video — mira_edit_video (aspect 9:16 or 16:9).
For "office day", "9 to 5", "daily office routine", "agent office" — use mira_office_day.
For "using my uploads" / "from my videos" — mira_create_video with use_uploads true.
Mira verifies every video against the user's ask and retries if off-brief — never deliver random stock as success.
Convert/crop/remake last video: mira_edit_video or natural language ("crop to shorts", "mute the video", "speed up 2x").
YouTube: mira_youtube_connect once, then mira_youtube_upload (or "post last video to youtube"). Default privacy=public Shorts.
Growth: "post viral short about X" / "growth short about X" → make Short + hook caption + publish public (views/subs playbook).
Clipping: "clip last video into shorts" / "make clips from last video" → cut long cut into multiple 9:16 Shorts (+ optional upload).
Schedule: "schedule shorts about coffee, dogs, sunset every 3 hours" → auto-post queue; "schedule status" / "stop schedule"; add "now" to post first immediately.
Analytics: "youtube analytics" / "grow my topics" → pull views + add winning-topic ideas to schedule.
Export: "export to reels" / "export last short" → Reels + TikTok folders.
Comments: "reply to comments" → soft auto-replies on last upload.
NEVER use open_youtube or search_web for "make a video about …" — that means GENERATE, not search YouTube.
NEVER use open_youtube for "post/upload to youtube" — that means mira_youtube_upload.

{memory_context}
"""


class Agent:
    def __init__(self, call_llm: Callable[[str, str], str], remember: Callable[[str], None]) -> None:
        self._call_llm = call_llm
        self._remember = remember

    def run(self, user_text: str, memory_context: str) -> str:
        # Hard guard — never let the LLM turn "make a video" into YouTube search
        from jarvis.tools.mira_tool import try_mira_command

        mira = try_mira_command(user_text, background=True)
        if mira:
            return mira

        system = AGENT_PROMPT.format(tools=tools_description(), memory_context=memory_context)
        raw = self._call_llm(system, user_text)

        plan_match = re.search(r"```plan\s*(\[.*?\])\s*```", raw, re.DOTALL)
        if plan_match:
            return self._execute_plan(plan_match.group(1), raw)

        action_match = re.search(r"```action\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if action_match:
            return self._execute_single(action_match.group(1), raw)

        return re.sub(r"```(?:action|plan)\s*.*?```", "", raw, flags=re.DOTALL).strip() or raw

    def _execute_single(self, action_json: str, raw: str) -> str:
        try:
            action = json.loads(action_json)
        except json.JSONDecodeError:
            return "Command unclear, sir — try again with a simpler phrasing."

        result = execute_tool(
            action.get("tool", ""),
            action.get("params", {}),
            memory_remember=self._remember,
        )
        spoken = re.sub(r"```action\s*\{.*?\}\s*```", "", raw, flags=re.DOTALL).strip()
        # Drop refusal fluff if the tool actually ran
        spoken = re.sub(
            r"(?i)\b(i can'?t|i'?m (?:afraid|unable)|having trouble|unfortunately)\b[^.]*\.?\s*",
            "",
            spoken,
        ).strip()
        if spoken and result not in spoken:
            return f"{spoken} {result}"
        return spoken or result

    def _execute_plan(self, plan_json: str, raw: str) -> str:
        try:
            steps = json.loads(plan_json)
        except json.JSONDecodeError:
            return "I could not plan that task, sir."

        results: list[str] = []
        for step in steps[:8]:
            tool = step.get("tool", "")
            params = step.get("params", {})
            result = execute_tool(tool, params, memory_remember=self._remember)
            results.append(result)

        spoken = re.sub(r"```plan\s*\[.*?\]\s*```", "", raw, flags=re.DOTALL).strip()
        summary = " ".join(results[:3])
        if spoken:
            return f"{spoken} {summary}"
        return summary or "Task completed, sir."
