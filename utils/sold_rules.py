"""Sotildi qoidalari — bitta markaziy logika.

Qoidalar formati (templates.sold_rules): JSON ro'yxat
  [{"key": "tel", "value": "TOPSHIRILDI"}, {"key": "status", "value": ""}]

- value bo'sh bo'lsa → filled_data'da shu maydon qiymati "" (bo'sh) qilinadi,
  lekin kalit saqlanadi (shablon format qilganda KeyError bo'lmasligi uchun).
- value bor bo'lsa → shu qiymat bilan almashtiriladi.

Backward compat: agar sold_rules bo'sh bo'lsa, eski sold_field_key/sold_replacement
juftligidan bitta qoida yasaladi.
"""
from __future__ import annotations
import json
from typing import Any


def parse_rules(tpl) -> list[dict]:
    """Template row'dan qoidalarni o'qiydi (backward compat bilan)."""
    def _g(k, d=None):
        try:
            v = tpl[k]
            return v if v is not None else d
        except (KeyError, IndexError, TypeError):
            return d

    raw = _g("sold_rules") or ""
    rules: list[dict] = []
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    k = str(item.get("key") or "").strip()
                    if not k:
                        continue
                    v = item.get("value")
                    rules.append({"key": k, "value": "" if v is None else str(v)})
        except Exception:
            rules = []

    if not rules:
        # Backward compat: single-rule
        sk = _g("sold_field_key") or ""
        if sk:
            sv = _g("sold_replacement") or ""
            rules.append({"key": sk, "value": sv})

    return rules


def dump_rules(rules: list[dict]) -> str:
    """Qoidalarni DB'ga saqlash uchun JSON string."""
    clean = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        k = str(r.get("key") or "").strip()
        if not k:
            continue
        v = r.get("value")
        clean.append({"key": k, "value": "" if v is None else str(v)})
    return json.dumps(clean, ensure_ascii=False)


def apply_rules(filled: dict, rules: list[dict]) -> dict:
    """filled_data'ga qoidalarni qo'llaydi. Yangi dict qaytaradi."""
    out = dict(filled or {})
    for r in rules or []:
        k = r.get("key")
        if not k:
            continue
        v = r.get("value")
        out[k] = "" if v is None else str(v)
    return out


def apply_sold(filled: dict, tpl) -> tuple[dict, list[dict]]:
    """High-level: template'dan qoidalarni olib, filled'ga qo'llaydi.
    Qaytaradi: (new_filled, applied_rules). Qoidalar bo'lmasa fallback ishlatiladi.
    """
    rules = parse_rules(tpl)
    if rules:
        return apply_rules(filled, rules), rules

    # Fallback: hech qanday qoida yo'q — title/nomi ga 🔴 SOTILDI prefix
    out = dict(filled or {})
    marker = "🔴 SOTILDI"
    for k in ("title", "nomi", "name"):
        if k in out:
            out[k] = f"{marker} — {out[k]}"
            return out, [{"key": k, "value": out[k]}]
    out["_status"] = marker
    return out, [{"key": "_status", "value": marker}]
