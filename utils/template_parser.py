import re

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_']*)\}")


def extract_placeholders(text: str) -> list[str]:
    seen = []
    for m in PLACEHOLDER_RE.finditer(text or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def fill_template(text: str, data: dict) -> str:
    def repl(m):
        key = m.group(1)
        if key in data:
            return str(data.get(key, ""))
        # Agar key data'da umuman yo'q bo'lsa — bo'sh qaytarish
        # (admin yangi maydon qo'shgan lekin text_template'da {ad_id} kabi
        # alohida tizim placeholder'lar bor — ularni {} da qoldirmaymiz,
        # bo'sh qilib chiqaramiz — bot crash bermaydi)
        return ""
    return PLACEHOLDER_RE.sub(repl, text or "")


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def safe_format(text: str, data: dict) -> str:
    """str.format_map bilan xavfsiz — yo'q placeholder'lar '' ga almashadi."""
    try:
        return (text or "").format_map(_SafeDict(**(data or {})))
    except Exception:
        return fill_template(text, data or {})
