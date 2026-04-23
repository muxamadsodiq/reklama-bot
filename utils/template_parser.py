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
        return str(data.get(key, m.group(0)))
    return PLACEHOLDER_RE.sub(repl, text or "")
