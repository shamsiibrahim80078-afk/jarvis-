"""YouTube control — correct search query extraction."""

from jarvis.tools.command_parse import extract_youtube_query
from jarvis.tools.mira_tool import is_mira_followup_intent, is_mira_generate_intent
from jarvis.tools.system import open_youtube


def handle(text: str) -> str | None:
    # Never steal Mira generate / upload / connect
    if is_mira_generate_intent(text) or is_mira_followup_intent(text):
        return None
    try:
        from jarvis.mira.youtube_upload import is_youtube_connect_intent, is_youtube_upload_intent

        if is_youtube_connect_intent(text) or is_youtube_upload_intent(text):
            return None
    except Exception:
        pass
    yt_flag, query = extract_youtube_query(text)
    if not yt_flag:
        return None
    return open_youtube(query)
