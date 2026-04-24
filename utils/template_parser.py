import re

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_']*)\}")


def extract_placeholders(text: str) -> list[str]:
    seen = []
    for m in PLACEHOLDER_RE.finditer(text or ""):
        name = m.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def fill_template(text: str, data: dict, empty_placeholder: str = "") -> str:
    def repl(m):
        key = m.group(1)
        if key in data:
            val = data.get(key, "")
            s = str(val) if val is not None else ""
            # REJA13b: agar qiymat bo'sh/faqat bo'sh joy bo'lsa — admin matnini chiqaramiz
            if empty_placeholder and not s.strip():
                return empty_placeholder
            return s
        # key data'da yo'q — bo'sh qaytarish (bot crash bermasin)
        return empty_placeholder or ""
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
