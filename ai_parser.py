"""REJA8: AI-powered e'lon matnini shablon maydonlariga ajratish."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import aiohttp

from config import GROQ_API_KEY

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
PRIMARY_MODEL = "llama-3.3-70b-versatile"
FALLBACK_MODEL = "llama-3.1-8b-instant"
TIMEOUT_SEC = 15

# Kirill → Lotin (o'zbek)
_CYR_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'",
    "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ғ": "g'", "қ": "q", "ҳ": "h", "ў": "o'", "ә": "a",
}


def cyr_to_lat(s: str) -> str:
    out = []
    for ch in s:
        low = ch.lower()
        if low in _CYR_MAP:
            tr = _CYR_MAP[low]
            if ch.isupper():
                tr = tr.capitalize()
            out.append(tr)
        else:
            out.append(ch)
    return "".join(out)


def _regex_extract(text: str, fields: list[dict]) -> dict[str, str]:
    """Oddiy 'Kalit: qiymat' shaklidagi qatorlarni qidirib chiqarish."""
    result: dict[str, str] = {}
    # Har field uchun question'ning birinchi so'zi asosida pattern quramiz
    lines = text.splitlines()
    for f in fields:
        key = f["key"]
        q = (f.get("question") or "").strip()
        # Question'dan asosiy so'z (Nomi, Narxi, Telefon ...)
        qword = re.split(r"[\s:\-–?]", q, maxsplit=1)[0] if q else key
        candidates = {key.lower(), qword.lower()}
        # key variantlari: name→nomi, price→narxi, phone→telefon
        alias_map = {
            "name": ["nomi", "nom", "mahsulot"],
            "price": ["narxi", "narx", "summa"],
            "phone": ["telefon", "tel", "raqam", "aloqa"],
            "address": ["manzil", "joy", "hudud"],
            "description": ["tavsif", "ma'lumot", "izoh"],
        }
        for a in alias_map.get(key.lower(), []):
            candidates.add(a)
        for ln in lines:
            m = re.match(r"\s*([^:\-–]{1,30})\s*[:\-–]\s*(.+)", ln)
            if not m:
                continue
            label = m.group(1).strip().lower()
            val = m.group(2).strip()
            if any(c and c in label for c in candidates):
                result[key] = val
                break
    return result


def _normalize_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s)
    if len(digits) == 9:
        digits = "998" + digits
    if len(digits) == 12 and digits.startswith("998"):
        return f"+998 {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:12]}"
    return s


def _normalize_price(s: str) -> str:
    # Raqamlarni ajratib 3 500 000 so'm qilamiz
    m = re.search(r"(\d[\d\s.,]*)", s)
    if not m:
        return s
    num = re.sub(r"[^\d]", "", m.group(1))
    if not num:
        return s
    try:
        n = int(num)
    except ValueError:
        return s
    grouped = f"{n:,}".replace(",", " ")
    # so'm bor-yo'qligini tekshiramiz
    low = s.lower()
    suffix = "so'm"
    for sfx in ("so'm", "som", "сум", "сўм", "usd", "$", "у.е", "у.е."):
        if sfx in low:
            suffix = sfx if sfx not in ("som", "сум", "сўм") else "so'm"
            break
    return f"{grouped} {suffix}"


def _post_clean(result: dict[str, str], fields: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in fields:
        key = f["key"]
        val = result.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        if not isinstance(val, str):
            val = str(val)
        val = cyr_to_lat(val).strip()
        kl = key.lower()
        if "phone" in kl or "tel" in kl or "raqam" in kl:
            val = _normalize_phone(val)
        elif "price" in kl or "narx" in kl or "summa" in kl:
            val = _normalize_price(val)
        out[key] = val
    return out


def _build_prompt(fields: list[dict]) -> str:
    lines = []
    for f in fields:
        lines.append(f'  - "{f["key"]}": {f.get("question", "")}')
    field_block = "\n".join(lines)
    return (
        "Sen e'lon matnidan ma'lumot ajratuvchi yordamchisan. "
        "Foydalanuvchi yuborgan matnni tahlil qilib, quyidagi maydonlarga mos qiymatlarni toping.\n\n"
        "MAYDONLAR (JSON kalitlari):\n"
        f"{field_block}\n\n"
        "QOIDALAR:\n"
        "1) Agar matn kirill yozuvda bo'lsa — lotin o'zbek yozuviga o'giring (ruscha so'zlar ham transliteratsiya).\n"
        "2) Telefon raqamni shu formatda bering: +998 XX XXX XX XX\n"
        "3) Narxni shu formatda bering: 3 500 000 so'm (bo'sh joy bilan, birlik bilan)\n"
        "4) Agar biror maydon topilmasa — qiymat null bo'lsin.\n"
        "5) FAQAT JSON qaytaring, hech qanday izoh YO'Q. Format: {\"key1\": \"qiymat\", \"key2\": null, ...}\n"
    )


async def _call_groq(text: str, fields: list[dict], model: str) -> dict[str, Any] | None:
    if not GROQ_API_KEY:
        log.warning("GROQ_API_KEY bo'sh — AI parsing o'tkazib yuborildi")
        return None
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _build_prompt(fields)},
            {"role": "user", "content": text},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }
    timeout = aiohttp.ClientTimeout(total=TIMEOUT_SEC)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.post(GROQ_URL, headers=headers, json=payload) as resp:
                body = await resp.text()
                if resp.status == 429 or "rate_limit" in body.lower():
                    return {"__rate_limited__": True}
                if 500 <= resp.status < 600:
                    log.warning("Groq %s server xato %s", model, resp.status)
                    return None
                if resp.status != 200:
                    log.warning("Groq %s xato %s: %s", model, resp.status, body[:300])
                    return None
                try:
                    data = json.loads(body)
                    content = data["choices"][0]["message"]["content"]
                    return json.loads(content)
                except (json.JSONDecodeError, KeyError, TypeError):
                    log.exception("Groq javobini parse qilib bo'lmadi: %s", body[:300])
                    return None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        log.warning("Groq %s network/timeout xato", model)
        return None


async def parse_ad_text(text: str, fields: list[dict]) -> dict[str, str]:
    """Matnni AI bilan tahlil qilib, field_key -> qiymat dict qaytaradi."""
    if not text or not fields:
        return {}

    # a) Regex bilan birlamchi urinish
    regex_hits = _regex_extract(text, fields)
    regex_ratio = len(regex_hits) / max(1, len(fields))

    if regex_ratio >= 0.5:
        # Regex yetarli — faqat tozalab qaytaramiz
        return _post_clean(regex_hits, fields)

    # b) Groq'ga yuborish
    try:
        ai = await _call_groq(text, fields, PRIMARY_MODEL)
        if ai and ai.get("__rate_limited__"):
            ai = await _call_groq(text, fields, FALLBACK_MODEL)
        if not ai or ai.get("__rate_limited__"):
            # AI ishlamadi — qisman regex natijasini qaytaramiz
            return _post_clean(regex_hits, fields)
        # AI natijasini regex bilan birlashtiramiz (AI ustun)
        merged = {**regex_hits, **{k: v for k, v in ai.items() if v is not None}}
        return _post_clean(merged, fields)
    except Exception:
        log.exception("AI parse xato")
        return _post_clean(regex_hits, fields)
