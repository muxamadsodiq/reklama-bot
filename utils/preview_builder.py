from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .template_parser import fill_template


def format_ad_id(ad_id: int, prefix: str = "_") -> str:
    """Format: #<prefix><0001>. Prefix admin kiritadi ('_', 'REK', 'A', ...)."""
    p = prefix if prefix is not None else "_"
    return f"#{p}{ad_id:04d}"


def build_text_and_kb(template_row, filled_data: dict, custom_url: str | None, ad_id: int | None = None, prefix: str | None = None, bot_username: str | None = None, channel_id: int | None = None):
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

    rows = []
    label = template_row["button_label"]
    caption = template_row["button_caption"]
    if label:
        url = custom_url if template_row["button_url_by_user"] else template_row["button_url"]
        if url:
            if caption:
                text = f"{text}\n\n{caption}"
            rows.append([InlineKeyboardButton(text=label, url=url)])

    # REJA13: Obuna (premium) tugmasi — admin belgilagan label + deep link botga
    try:
        sub_label_raw = template_row["sub_btn_label"] or ""
    except (KeyError, IndexError):
        sub_label_raw = ""
    if sub_label_raw and bot_username and channel_id is not None:
        try:
            sub_label = fill_template(sub_label_raw, data)
        except Exception:
            sub_label = sub_label_raw
        sub_label = (sub_label or "").strip()[:64] or sub_label_raw.strip()[:64]
        payload = f"sub_{channel_id}_{ad_id or 0}"
        rows.append([InlineKeyboardButton(
            text=sub_label,
            url=f"https://t.me/{bot_username}?start={payload}",
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    return text, kb
