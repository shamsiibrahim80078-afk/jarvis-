"""Language support for Mira office vlogs — voices + translations."""

from __future__ import annotations

import json
import re
from typing import Any

# Male default voices (Alex is male). Female fallback listed second where useful.
VOICE_MAP: dict[str, str] = {
    "en": "en-US-GuyNeural",
    "ur": "ur-PK-AsadNeural",
    "urdu": "ur-PK-AsadNeural",
    "ar": "ar-SA-HamedNeural",
    "arabic": "ar-SA-HamedNeural",
    "arabian": "ar-SA-HamedNeural",
    "ps": "ps-AF-GulNawazNeural",
    "pashto": "ps-AF-GulNawazNeural",
    "pushto": "ps-AF-GulNawazNeural",
    "hi": "hi-IN-MadhurNeural",
    "hindi": "hi-IN-MadhurNeural",
    "fa": "fa-IR-FaridNeural",
    "farsi": "fa-IR-FaridNeural",
    "persian": "fa-IR-FaridNeural",
    "es": "es-ES-AlvaroNeural",
    "spanish": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "french": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "german": "de-DE-ConradNeural",
    "tr": "tr-TR-AhmetNeural",
    "turkish": "tr-TR-AhmetNeural",
    "zh": "zh-CN-YunxiNeural",
    "chinese": "zh-CN-YunxiNeural",
    "ja": "ja-JP-KeitaNeural",
    "japanese": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "korean": "ko-KR-InJoonNeural",
    "pt": "pt-BR-AntonioNeural",
    "portuguese": "pt-BR-AntonioNeural",
    "ru": "ru-RU-DmitryNeural",
    "russian": "ru-RU-DmitryNeural",
    "it": "it-IT-DiegoNeural",
    "italian": "it-IT-DiegoNeural",
}

# Normalize aliases → short code
_ALIASES = {
    "english": "en",
    "urdu": "ur",
    "arabic": "ar",
    "arabian": "ar",
    "pashto": "ps",
    "pushto": "ps",
    "hindi": "hi",
    "farsi": "fa",
    "persian": "fa",
}


def normalize_lang(text: str | None) -> str:
    raw = (text or "en").strip().lower()
    if not raw:
        return "en"
    raw = raw.replace("_", "-")
    if raw in _ALIASES:
        return _ALIASES[raw]
    if raw in VOICE_MAP:
        code = raw if len(raw) <= 3 else _ALIASES.get(raw, raw)
        return code if code in ("en", "ur", "ar", "ps", "hi", "fa") or code in VOICE_MAP else raw[:2]
    # "in urdu", "ur-PK"
    for key, code in _ALIASES.items():
        if key in raw:
            return code
    m = re.match(r"^([a-z]{2})(?:-|$)", raw)
    if m:
        return m.group(1)
    return "en"


def detect_lang_from_request(text: str) -> str | None:
    """Return language code if user asked for a specific language, else None."""
    lower = (text or "").lower()
    patterns = [
        (r"\b(?:in|into|with)\s+urdu\b|\burdu\b", "ur"),
        (r"\b(?:in|into)\s+pashto\b|\bpashto\b|\bpushto\b", "ps"),
        (r"\b(?:in|into)\s+arab(?:ic|ian)?\b|\barabic\b|\barabian\b", "ar"),
        (r"\b(?:in|into)\s+hindi\b|\bhindi\b", "hi"),
        (r"\b(?:in|into)\s+(?:farsi|persian)\b|\bfarsi\b|\bpersian\b", "fa"),
        (r"\b(?:in|into)\s+spanish\b|\bespa[nñ]ol\b", "es"),
        (r"\b(?:in|into)\s+french\b|\bfran[cç]ais\b", "fr"),
        (r"\b(?:in|into)\s+german\b|\bdeutsch\b", "de"),
        (r"\b(?:in|into)\s+turkish\b|\bt[uü]rk(?:çe|ce)?\b", "tr"),
        (r"\b(?:in|into)\s+chinese\b|\bmandarin\b", "zh"),
        (r"\b(?:in|into)\s+japanese\b", "ja"),
        (r"\b(?:in|into)\s+korean\b", "ko"),
        (r"\b(?:in|into)\s+english\b", "en"),
    ]
    for pat, code in patterns:
        if re.search(pat, lower):
            return code
    return None


def voice_for(lang: str) -> str:
    code = normalize_lang(lang)
    return VOICE_MAP.get(code) or VOICE_MAP.get(code[:2]) or VOICE_MAP["en"]


def _llm_translate_batch(items: list[dict[str, str]], lang: str) -> list[dict[str, str]] | None:
    """Translate heading+line pairs via Jarvis Brain when available."""
    if not items:
        return []
    lang_name = {
        "ur": "Urdu",
        "ar": "Arabic",
        "ps": "Pashto",
        "hi": "Hindi",
        "fa": "Persian",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "tr": "Turkish",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
    }.get(normalize_lang(lang), lang)
    payload = [{"i": i, "heading": it.get("heading", ""), "line": it.get("line", "")} for i, it in enumerate(items)]
    prompt = (
        f"Translate each heading and line into natural spoken {lang_name} for a day-in-the-life office vlog. "
        f"Keep meaning. Headings stay short (2-5 words). Return ONLY JSON array with keys i, heading, line.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        from jarvis.brain import Brain

        brain = Brain()
        raw = brain.ask(
            "You are a precise translator. Output valid JSON only, no markdown.",
            prompt,
        )
        if not raw:
            return None
        text = raw.strip()
        if "```" in text:
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        if not isinstance(data, list):
            return None
        by_i = {int(x.get("i")): x for x in data if isinstance(x, dict) and "i" in x}
        out = []
        for i, it in enumerate(items):
            tr = by_i.get(i) or {}
            out.append(
                {
                    **it,
                    "heading": str(tr.get("heading") or it.get("heading") or ""),
                    "line": str(tr.get("line") or it.get("line") or ""),
                }
            )
        return out
    except Exception:
        return None


# Reliable offline packs for priority languages
_PACKS: dict[str, dict[str, dict[str, str]]] = {
    "ur": {
        "listen": {"heading": "سنو…", "line": "سنو — آج میرا اصلی نائن ٹو فائیو دکھا رہا ہوں۔"},
        "breakfast": {"heading": "ناشتہ", "line": "صبح کا ناشتہ۔ دن کا آغاز۔"},
        "commute": {"heading": "آفس جا رہے ہیں", "line": "آفس کی طرف نکل پڑا۔"},
        "enter": {"heading": "داخلہ", "line": "بیج ٹیپ۔ اندر داخل۔"},
        "desk": {"heading": "ڈیسک", "line": "اپنی جگہ پر۔ لیپ ٹاپ آن۔"},
        "standup": {"heading": "اسٹینڈ اپ", "line": "فوری اسٹینڈ اپ۔ کام صاف۔"},
        "work_a": {"heading": "کام", "line": "ڈیپ ورک۔ ایک مسئلہ، پورا فوکس۔"},
        "work_b": {"heading": "کوڈ", "line": "کوڈ لکھ رہا ہوں۔ چھوٹے کمیٹس۔"},
        "work_c": {"heading": "ریویو", "line": "کوڈ ریویو۔ بہتر بناؤ۔"},
        "work_d": {"heading": "ڈیبگ", "line": "بگ ڈھونڈ رہا ہوں۔ ٹھیک کر کے آگے۔"},
        "work_e": {"heading": "ڈیزائن", "line": "وائٹ بورڈ۔ پہلے سوچ، پھر کوڈ۔"},
        "lunch": {"heading": "لنچ", "line": "لنچ بریک۔ دماغ ری سیٹ۔"},
        "meeting": {"heading": "میٹنگ", "line": "میٹنگ۔ فیصلے، کم بات۔"},
        "ship": {"heading": "شپ", "line": "شپ کر دیا۔ سبز سگنل۔"},
        "leave": {"heading": "روانگی", "line": "ڈیسک صاف۔ گھر کی طرف۔"},
        "outro": {"heading": "ختم", "line": "آج کا دن مکمل۔ کل ملتے ہیں۔"},
    },
    "ar": {
        "listen": {"heading": "اسمع…", "line": "اسمع — هذا يوم عملي الحقيقي من التاسعة للخامسة."},
        "breakfast": {"heading": "الإفطار", "line": "إفطار الصباح. بداية اليوم."},
        "commute": {"heading": "في الطريق للمكتب", "line": "في طريقي إلى المكتب الآن."},
        "enter": {"heading": "الدخول", "line": "بطاقة الدخول. دخلت."},
        "desk": {"heading": "المكتب", "line": "على مكتبي. اللابتوب يعمل."},
        "standup": {"heading": "الاجتماع الصباحي", "line": "اجتماع سريع. المهام واضحة."},
        "work_a": {"heading": "العمل", "line": "تركيز عميق. مشكلة واحدة."},
        "work_b": {"heading": "البرمجة", "line": "أكتب الكود. تعديلات صغيرة."},
        "work_c": {"heading": "المراجعة", "line": "مراجعة الكود. نحسّنه."},
        "work_d": {"heading": "إصلاح الأخطاء", "line": "أبحث عن الخطأ وأصلحه."},
        "work_e": {"heading": "التصميم", "line": "السبورة أولاً. فكر ثم اكتب."},
        "lunch": {"heading": "الغداء", "line": "استراحة غداء. إعادة شحن."},
        "meeting": {"heading": "اجتماع", "line": "اجتماع. قرارات سريعة."},
        "ship": {"heading": "الإطلاق", "line": "تم الإطلاق. كل شيء أخضر."},
        "leave": {"heading": "المغادرة", "line": "مكتب نظيف. إلى المنزل."},
        "outro": {"heading": "النهاية", "line": "انتهى اليوم. أراك غداً."},
    },
    "ps": {
        "listen": {"heading": "واورئ…", "line": "واورئ — نن زما اصلي نهه تر پنځه ورځ ښکاره کوم."},
        "breakfast": {"heading": "ناشته", "line": "سهارنۍ ناسته. ورځ پیل."},
        "commute": {"heading": "دفتر ته", "line": "اوس دفتر ته روان یم."},
        "enter": {"heading": "ننوتل", "line": "بیج. دننه شو."},
        "desk": {"heading": "میز", "line": "زما میز. لپ‌ټاپ پرانیست."},
        "standup": {"heading": "سټنډ اپ", "line": "لنډ سټنډ اپ. کارونه روښانه."},
        "work_a": {"heading": "کار", "line": "ژور کار. یوه ستونزه."},
        "work_b": {"heading": "کوډ", "line": "کوډ لیکم. وړوکی کمیټونه."},
        "work_c": {"heading": "کتنه", "line": "کوډ کتنه. ښه یې کړئ."},
        "work_d": {"heading": "ډیبګ", "line": "بګ لټوم او سموم."},
        "work_e": {"heading": "ډیزاین", "line": "وایت‌بورډ. لومړی فکر."},
        "lunch": {"heading": "غرمه‌ماښامی", "line": "ناشته وقفه. دماغ تازه."},
        "meeting": {"heading": "غونډه", "line": "غونډه. چټک پرېکړې."},
        "ship": {"heading": "خپور", "line": "خپور شو. شنه نښه."},
        "leave": {"heading": "وتل", "line": "میز پاک. کور ته."},
        "outro": {"heading": "پای", "line": "نن ورځ خلاصه. سبا به وګورو."},
    },
}


def localize_beats(beats: list[dict[str, Any]], lang: str) -> list[dict[str, Any]]:
    """Apply headings/lines in target language. Keeps kind/q/pose/t."""
    code = normalize_lang(lang)
    if code in ("en", "english"):
        return [dict(b) for b in beats]

    pack = _PACKS.get(code)
    if pack:
        out = []
        for b in beats:
            nb = dict(b)
            key = b.get("i18n") or b.get("t") or ""
            tr = pack.get(str(key)) or pack.get(str(b.get("t") or ""))
            if tr:
                nb["heading"] = tr.get("heading") or nb.get("heading") or ""
                nb["line"] = tr.get("line") or nb.get("line") or ""
            out.append(nb)
        # If many keys missed, try LLM fill for missing only
        missing = [i for i, (a, b) in enumerate(zip(beats, out)) if a.get("line") == b.get("line") and code != "en"]
        if len(missing) > len(beats) // 2:
            llm = _llm_translate_batch(
                [{"heading": b.get("heading", ""), "line": b.get("line", "")} for b in beats],
                code,
            )
            if llm:
                return [{**beats[i], "heading": llm[i]["heading"], "line": llm[i]["line"]} for i in range(len(beats))]
        return out

    llm = _llm_translate_batch(
        [{"heading": b.get("heading", ""), "line": b.get("line", "")} for b in beats],
        code,
    )
    if llm:
        return [{**beats[i], "heading": llm[i]["heading"], "line": llm[i]["line"]} for i in range(len(beats))]
    return [dict(b) for b in beats]
