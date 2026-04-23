from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .template_parser import fill_template


def format_ad_id(ad_id: int, prefix: str = "_") -> str:
    """Format: #<prefix><0001>. Prefix admin kiritadi ('_', 'REK', 'A', ...)."""
    p = prefix if prefix is not None else "_"
    return f"#{p}{ad_id:04d}"


def build_text_and_kb(template_row, filled_data: dict, custom_url: str | None, ad_id: int | None = None, prefix: str | None = None):
    data = dict(filled_data)
    if prefix is None:
        try:
            prefix = template_row["id_prefix"] or "_"
        except (KeyError, IndexError):
            prefix = "_"
    prefix = prefix or "_"
    if ad_id is not None:
        data.setdefault("ad_id", format_ad_id(ad_id, prefix))
    text = fill_template(template_row["text_template"], data)

    if ad_id is not None and "{ad_id}" not in (template_row["text_template"] or ""):
        text = f"{text}\n\n🆔 {format_ad_id(ad_id, prefix)}"

    kb = None
    label = template_row["button_label"]
    caption = template_row["button_caption"]
    if label:
        url = custom_url if template_row["button_url_by_user"] else template_row["button_url"]
        if url:
            if caption:
                text = f"{text}\n\n{caption}"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=label, url=url)]]
            )
    return text, kb
