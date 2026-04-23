"""
Reklamabot Mini App backend (FastAPI) — OLX-style.
Endpoints:
  GET  /api/health
  GET  /api/categories
  GET  /api/locations
  GET  /api/trending
  GET  /api/ads            — filtr+sort+qidiruv+paginatsiya
  GET  /api/ads/{id}
  POST /api/ads/{id}/view
  GET  /api/thumb/{file_id}   — rasmni proksilab beradi (kesh)
  GET  /api/media/{file_id}   — orig URL (eski)
  GET  /api/saved_searches        ?user_id=...&init_data=...
  POST /api/saved_searches
  DELETE /api/saved_searches/{id}
  GET  /admin                 — HTTP basic auth
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sqlite3
import time
import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import sys as _sys
_PRJ = str(Path(__file__).resolve().parent.parent)
if _PRJ not in _sys.path:
    _sys.path.insert(0, _PRJ)
try:
    from utils.template_parser import safe_format
except Exception:
    def safe_format(text, data):
        try:
            return text.format(**{k: (v if v is not None else "") for k, v in (data or {}).items()})
        except Exception:
            return text or ""

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
load_dotenv(PROJECT_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_PATH = str(PROJECT_DIR / "reklama.db")
CACHE_DIR = PROJECT_DIR / ".webapp_cache"
CACHE_DIR.mkdir(exist_ok=True)
ADMIN_PASSWORD = os.getenv("WEBAPP_ADMIN_PASSWORD", "admin123")

app = FastAPI(title="Reklamabot Mini App", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# --------- DB helper ---------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# --------- Telegram WebApp initData validation ---------
def validate_init_data(init_data: str, max_age: int = 86400) -> Optional[dict]:
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        auth_date = int(parsed.get("auth_date", "0"))
        if auth_date and (time.time() - auth_date) > max_age:
            return None
        data_check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, received_hash):
            return None
        user_json = parsed.get("user")
        if user_json:
            parsed["user"] = json.loads(user_json)
        return parsed
    except Exception:
        return None


def require_user(init_data: str = "") -> int:
    v = validate_init_data(init_data)
    if not v or "user" not in v:
        raise HTTPException(401, "initData required")
    uid = v["user"].get("id")
    if not uid:
        raise HTTPException(401, "user id missing")
    return int(uid)


# --------- Price parsing ---------
PRICE_RE = re.compile(r"(\d[\d\s.,]*)")

def parse_price(s) -> Optional[int]:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return int(s)
    m = PRICE_RE.search(str(s))
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace(",", "").replace(".", "")
    try:
        return int(num)
    except Exception:
        return None


def extract_price(data: dict) -> Optional[int]:
    for key in ("price", "narx", "narxi", "summa"):
        if key in data:
            p = parse_price(data[key])
            if p is not None:
                return p
    # fallback: scan all values for price-looking numbers if key contains narx
    for k, v in data.items():
        if isinstance(k, str) and ("narx" in k.lower() or "price" in k.lower()):
            p = parse_price(v)
            if p is not None:
                return p
    return None


def extract_location(data: dict) -> str:
    for key in ("location", "manzil", "joy", "shahar", "city", "region"):
        if data.get(key):
            return str(data[key])
    return ""


def extract_title(data: dict, ad_id: int) -> str:
    for k in ("title", "nomi", "name", "mahsulot", "tovar"):
        if data.get(k):
            return str(data[k])
    return f"E'lon #{ad_id}"


def extract_desc(data: dict) -> str:
    for k in ("description", "tavsif", "izoh", "matn", "batafsil"):
        if data.get(k):
            return str(data[k])
    return ""


# --------- Routes ---------
@app.get("/", response_class=HTMLResponse)
async def index():
    html = (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/health")
async def health():
    return {"ok": True, "ts": int(time.time())}


@app.get("/api/categories")
async def api_categories():
    conn = db()
    try:
        cur = conn.execute(
            "SELECT id, parent_id, is_question, text AS title, "
            "COALESCE(icon, '') AS icon "
            "FROM routing_nodes ORDER BY position ASC, id ASC"
        )
        nodes = [dict(r) for r in cur.fetchall()]
        children_map = {}
        by_id = {n["id"]: n for n in nodes}
        for n in nodes:
            children_map.setdefault(n["parent_id"], []).append(n)

        def path_for(node_id):
            path = []
            cur_id = node_id
            seen = set()
            while cur_id and cur_id not in seen:
                seen.add(cur_id)
                n = by_id.get(cur_id)
                if not n:
                    break
                path.append(n["title"])
                cur_id = n["parent_id"]
            return list(reversed(path))

        categories = []
        for n in nodes:
            if n["is_question"] == 0 and n["id"] not in children_map:
                c = conn.execute(
                    "SELECT COUNT(*) FROM ads WHERE category_id=? AND status='approved'",
                    (n["id"],),
                ).fetchone()[0]
                categories.append({
                    "id": n["id"],
                    "title": n["title"],
                    "icon": n["icon"] or "",
                    "path": path_for(n["id"]),
                    "count": c,
                })
        total = conn.execute(
            "SELECT COUNT(*) FROM ads WHERE status='approved'"
        ).fetchone()[0]
        return {"categories": categories, "total": total}
    finally:
        conn.close()


@app.get("/api/locations")
async def api_locations():
    """Unique location list from all approved ads."""
    conn = db()
    try:
        cur = conn.execute(
            "SELECT filled_data FROM ads WHERE status='approved'"
        )
        counter: dict[str, int] = {}
        for (fd,) in cur.fetchall():
            try:
                d = json.loads(fd or "{}")
            except Exception:
                continue
            loc = extract_location(d).strip()
            if loc:
                # normalize
                loc_norm = loc[:60]
                counter[loc_norm] = counter.get(loc_norm, 0) + 1
        items = sorted(counter.items(), key=lambda x: -x[1])
        return {"locations": [{"name": n, "count": c} for n, c in items[:100]]}
    finally:
        conn.close()


@app.get("/api/trending")
async def api_trending(limit: int = Query(10, ge=1, le=30)):
    """Top viewed ads across all time (approved only)."""
    conn = db()
    try:
        cur = conn.execute(
            """SELECT a.id, a.filled_data, a.media_file_id, a.media_type,
                      a.created_at, a.category_id, a.view_count, a.media_list
               FROM ads a
               WHERE a.status='approved'
               ORDER BY COALESCE(a.view_count, 0) DESC, a.id DESC
               LIMIT ?""",
            (limit,),
        )
        return {"items": [_ad_row_to_card(r) for r in cur.fetchall()]}
    finally:
        conn.close()


def _ad_row_to_card(r):
    try:
        data = json.loads(r["filled_data"] or "{}")
    except Exception:
        data = {}
    price_num = extract_price(data)
    return {
        "id": r["id"],
        "title": extract_title(data, r["id"])[:120],
        "description": extract_desc(data)[:240],
        "price": str(data.get("price") or data.get("narx") or data.get("narxi") or ""),
        "price_num": price_num,
        "location": extract_location(data),
        "created_at": r["created_at"],
        "category_id": r["category_id"],
        "has_media": bool(r["media_file_id"] or (r["media_list"] if "media_list" in r.keys() else None)),
        "media_file_id": r["media_file_id"],
        "view_count": r["view_count"] or 0,
        "thumb_url": f"api/thumb/{r['media_file_id']}" if r["media_file_id"] else None,
        "is_sold": bool(r["sold_at"]) if "sold_at" in r.keys() else False,
    }


@app.get("/api/ads")
async def api_ads(
    category: Optional[int] = None,
    q: Optional[str] = Query(None, max_length=200),
    location: Optional[str] = Query(None, max_length=80),
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sort: str = Query("new", pattern="^(new|cheap|expensive|views)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    conn = db()
    try:
        where = ["a.status='approved'"]
        params: list = []

        if category:
            where.append("a.category_id=?")
            params.append(category)

        if location:
            where.append("LOWER(a.filled_data) LIKE ?")
            params.append(f"%{location.lower()}%")

        # Multi-token search
        tokens: list[str] = []
        if q:
            tokens = [t.strip().lower() for t in q.split() if t.strip()]

        if tokens:
            all_nodes = conn.execute(
                "SELECT id, parent_id, text FROM routing_nodes"
            ).fetchall()
            node_by_id = {n["id"]: dict(n) for n in all_nodes}

            def path_titles(nid):
                titles = []
                cur = nid
                seen = set()
                while cur and cur not in seen:
                    seen.add(cur)
                    n = node_by_id.get(cur)
                    if not n:
                        break
                    titles.append((n["text"] or "").lower())
                    cur = n["parent_id"]
                return " ".join(titles)

            for tok in tokens:
                s_cat = {nid for nid in node_by_id if tok in path_titles(nid)}
                clauses = ["LOWER(a.filled_data) LIKE ?"]
                params.append(f"%{tok}%")
                if tok.isdigit():
                    clauses.append("a.id = ?")
                    params.append(int(tok))
                if s_cat:
                    placeholders = ",".join(["?"] * len(s_cat))
                    clauses.append(f"a.category_id IN ({placeholders})")
                    params.extend(s_cat)
                where.append("(" + " OR ".join(clauses) + ")")

        where_sql = " AND ".join(where)

        # Sort
        order_sql = "a.id DESC"
        if sort == "views":
            order_sql = "COALESCE(a.view_count,0) DESC, a.id DESC"
        # cheap/expensive — price is inside JSON, so we must do it in Python
        # unless small dataset. We'll fetch all matching rows for these two modes.

        total = conn.execute(
            f"SELECT COUNT(*) FROM ads a WHERE {where_sql}", params
        ).fetchone()[0]

        if sort in ("cheap", "expensive") or price_min is not None or price_max is not None:
            # Python-side sort/filter by price
            cur = conn.execute(
                f"""SELECT a.id, a.filled_data, a.media_file_id, a.media_type,
                           a.created_at, a.category_id, a.view_count, a.media_list, a.sold_at
                    FROM ads a
                    WHERE {where_sql}""",
                params,
            )
            rows = [_ad_row_to_card(r) for r in cur.fetchall()]
            if price_min is not None:
                rows = [r for r in rows if r["price_num"] is not None and r["price_num"] >= price_min]
            if price_max is not None:
                rows = [r for r in rows if r["price_num"] is not None and r["price_num"] <= price_max]
            if sort == "cheap":
                rows.sort(key=lambda r: (r["price_num"] is None, r["price_num"] or 0))
            elif sort == "expensive":
                rows.sort(key=lambda r: -(r["price_num"] or 0))
            elif sort == "views":
                rows.sort(key=lambda r: -r["view_count"])
            else:
                rows.sort(key=lambda r: -r["id"])
            total = len(rows)
            offset = (page - 1) * page_size
            items = rows[offset:offset + page_size]
        else:
            offset = (page - 1) * page_size
            cur = conn.execute(
                f"""SELECT a.id, a.filled_data, a.media_file_id, a.media_type,
                           a.created_at, a.category_id, a.view_count, a.media_list, a.sold_at
                    FROM ads a
                    WHERE {where_sql}
                    ORDER BY {order_sql}
                    LIMIT ? OFFSET ?""",
                params + [page_size, offset],
            )
            items = [_ad_row_to_card(r) for r in cur.fetchall()]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page * page_size) < total,
            "query": q or "",
            "tokens": tokens,
            "sort": sort,
        }
    finally:
        conn.close()


@app.get("/api/ads/{ad_id}")
async def api_ad_detail(ad_id: int):
    conn = db()
    try:
        r = conn.execute(
            """SELECT id, user_id, username, filled_data, media_file_id, media_type,
                      custom_url, created_at, category_id, posted_chat_id, posted_message_id,
                      view_count, media_list
               FROM ads WHERE id=? AND status='approved'""",
            (ad_id,),
        ).fetchone()
        if not r:
            raise HTTPException(404, "Not found")
        try:
            data = json.loads(r["filled_data"] or "{}")
        except Exception:
            data = {}
        try:
            media_list = json.loads(r["media_list"] or "[]")
        except Exception:
            media_list = []
        breadcrumb = []
        if r["category_id"]:
            cur_id = r["category_id"]
            seen = set()
            while cur_id and cur_id not in seen:
                seen.add(cur_id)
                n = conn.execute(
                    "SELECT id, parent_id, text AS title FROM routing_nodes WHERE id=?",
                    (cur_id,),
                ).fetchone()
                if not n:
                    break
                breadcrumb.insert(0, {"id": n["id"], "title": n["title"]})
                cur_id = n["parent_id"]
        channel_url = None
        if r["posted_chat_id"] and r["posted_message_id"]:
            cid = str(r["posted_chat_id"])
            if cid.startswith("@"):
                channel_url = f"https://t.me/{cid[1:]}/{r['posted_message_id']}"
            elif cid.startswith("-100"):
                channel_url = f"https://t.me/c/{cid[4:]}/{r['posted_message_id']}"
            elif cid.lstrip("-").isdigit():
                channel_url = f"https://t.me/c/{cid.lstrip('-')}/{r['posted_message_id']}"
            else:
                channel_url = f"https://t.me/{cid}/{r['posted_message_id']}"
        # REJA9: public post text + contact button config
        public_text = None
        button_label = None
        has_premium_gate = False
        try:
            tpl_row = None
            if r["posted_chat_id"]:
                tpl_row = conn.execute(
                    """SELECT t.text_template, t.button_label, t.private_chat_id,
                              t.private_text_template, t.premium_url, t.id_prefix
                       FROM templates t JOIN channels c ON c.id=t.channel_id
                       WHERE c.chat_id=? LIMIT 1""",
                    (str(r["posted_chat_id"]),),
                ).fetchone()
            if tpl_row and tpl_row["text_template"]:
                # Kanal postiga to'liq mos matn — ad_id placeholder bilan.
                # show_in_public=0 bo'lgan maydonlar publicdan olib tashlanadi,
                # huddi moderation.approve'dagidek — kanal postiga aynan moslik.
                prefix = (tpl_row["id_prefix"] if "id_prefix" in tpl_row.keys() else "_") or "_"
                try:
                    ch_row = conn.execute(
                        "SELECT id FROM channels WHERE chat_id=? LIMIT 1",
                        (str(r["posted_chat_id"]),),
                    ).fetchone()
                    public_keys = None
                    if ch_row:
                        fmeta = conn.execute(
                            "SELECT key, show_in_public FROM template_fields WHERE channel_id=?",
                            (ch_row["id"],),
                        ).fetchall()
                        if fmeta:
                            public_keys = {f["key"] for f in fmeta if f["show_in_public"]}
                except Exception:
                    public_keys = None
                pub_data = dict(data)
                if public_keys is not None:
                    # maxfiy maydonlarni bo'sh qilib qo'yamiz
                    pub_data = {k: (v if k in public_keys else "") for k, v in pub_data.items()}
                pub_data.setdefault("ad_id", f"#{prefix}{r['id']:04d}")
                public_text = safe_format(tpl_row["text_template"], pub_data)
                # Agar template'da {ad_id} yo'q bo'lsa — oxiriga qo'shamiz
                if "{ad_id}" not in (tpl_row["text_template"] or ""):
                    public_text = f"{public_text}\n\n🆔 #{prefix}{r['id']:04d}"
                button_label = tpl_row["button_label"] or "📞 Aloqa"
                has_premium_gate = bool(tpl_row["private_chat_id"])
            else:
                button_label = "📞 Aloqa"
        except Exception:
            button_label = "📞 Aloqa"
        return {
            "id": r["id"],
            "data": data,
            "created_at": r["created_at"],
            "category_id": r["category_id"],
            "breadcrumb": breadcrumb,
            "media_file_id": r["media_file_id"],
            "media_type": r["media_type"],
            "media_list": media_list,
            "custom_url": r["custom_url"],
            "channel_url": channel_url,
            # REJA9: username/user_id removed from public response — seller
            # identity only reachable via /api/contact for private-group members
            "view_count": r["view_count"] or 0,
            "public_text": public_text,
            "button_label": button_label,
            "has_premium_gate": has_premium_gate,
            "has_full_info": has_premium_gate,  # REJA10: full-info tugmasi ham premium-gated
            "is_sold": bool((conn.execute("SELECT sold_at FROM ads WHERE id=?", (r['id'],)).fetchone() or [None])[0]),
        }
    finally:
        conn.close()


@app.get("/api/sellers/{user_id}")
async def api_seller(user_id: int):
    """Seller profile: total ads count + recent 10 approved ads."""
    conn = db()
    try:
        agg = conn.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(view_count),0) AS views,
                      MIN(created_at) AS first_at,
                      MAX(username) AS username
               FROM ads WHERE user_id=? AND status='approved'""",
            (user_id,),
        ).fetchone()
        rows = conn.execute(
            """SELECT id, filled_data, media_file_id, created_at, view_count
               FROM ads WHERE user_id=? AND status='approved'
               ORDER BY id DESC LIMIT 20""",
            (user_id,),
        ).fetchall()
        items = []
        for r in rows:
            try:
                d = json.loads(r["filled_data"] or "{}")
            except Exception:
                d = {}
            items.append({
                "id": r["id"],
                "title": d.get("title") or d.get("nomi") or f"E'lon #{r['id']}",
                "price": d.get("price") or d.get("narx") or d.get("narxi") or "",
                "location": d.get("location") or d.get("manzil") or "",
                "created_at": r["created_at"],
                "view_count": r["view_count"] or 0,
                "thumb_url": f"api/thumb/{r['media_file_id']}" if r["media_file_id"] else None,
            })
        return {
            "user_id": user_id,
            "username": agg["username"] if agg else None,
            "total_ads": agg["total"] if agg else 0,
            "total_views": agg["views"] if agg else 0,
            "first_ad_at": agg["first_at"] if agg else None,
            "items": items,
        }
    finally:
        conn.close()


# Currency rates (cached in-memory)
_RATES_CACHE = {"ts": 0, "usd_uzs": None, "rub_uzs": None}

@app.get("/api/rates")
async def api_rates():
    """Return USD→UZS and RUB→UZS rates. Cached 1h. Fallback to CBU API."""
    import time as _t
    now = _t.time()
    if _RATES_CACHE["ts"] > now - 3600 and _RATES_CACHE["usd_uzs"]:
        return {"usd_uzs": _RATES_CACHE["usd_uzs"], "rub_uzs": _RATES_CACHE["rub_uzs"], "cached": True}
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://cbu.uz/oz/arkhiv-kursov-valyut/json/",
            headers={"User-Agent": "reklamabot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=4) as resp:
            arr = json.loads(resp.read().decode("utf-8"))
        usd = rub = None
        for c in arr:
            if c.get("Ccy") == "USD": usd = float(c["Rate"])
            elif c.get("Ccy") == "RUB": rub = float(c["Rate"])
        if usd:
            _RATES_CACHE.update({"ts": now, "usd_uzs": usd, "rub_uzs": rub})
            return {"usd_uzs": usd, "rub_uzs": rub, "cached": False}
    except Exception as e:
        pass
    # Fallback hardcoded
    return {"usd_uzs": _RATES_CACHE["usd_uzs"] or 12500.0, "rub_uzs": _RATES_CACHE["rub_uzs"] or 135.0, "cached": False, "fallback": True}


# REJA9: contact button — premium gating via private-group membership
@app.post("/api/contact/{ad_id}")
async def api_contact(ad_id: int, payload: dict):
    """REJA10: Aloqa tugmasi — faqat contact_field qiymatini DM qiladi.
    Agar user maxfiy guruh a'zosi bo'lmasa — premium alert qaytaradi."""
    init_data = (payload or {}).get("init_data") or ""
    fallback_uid = (payload or {}).get("user_id")
    user_id: Optional[int] = None
    v = validate_init_data(init_data) if init_data else None
    if v and "user" in v:
        try:
            user_id = int(v["user"].get("id"))
        except Exception:
            user_id = None
    if not user_id and fallback_uid:
        try:
            user_id = int(fallback_uid)
        except Exception:
            user_id = None
    if not user_id:
        raise HTTPException(401, "user_id required")

    conn = db()
    try:
        ad = conn.execute(
            "SELECT id, filled_data, posted_chat_id FROM ads WHERE id=? AND status='approved'",
            (ad_id,),
        ).fetchone()
        if not ad:
            raise HTTPException(404, "ad not found")
        tpl = None
        if ad["posted_chat_id"]:
            tpl = conn.execute(
                """SELECT t.private_chat_id, t.premium_url, t.contact_field_key
                   FROM templates t JOIN channels c ON c.id=t.channel_id
                   WHERE c.chat_id=? LIMIT 1""",
                (str(ad["posted_chat_id"]),),
            ).fetchone()
        try:
            filled = json.loads(ad["filled_data"] or "{}")
        except Exception:
            filled = {}
    finally:
        conn.close()

    premium_url = (tpl["premium_url"] if tpl else "") or ""
    private_chat_id = tpl["private_chat_id"] if tpl else None
    contact_key = (tpl["contact_field_key"] if tpl else "") or ""

    if not private_chat_id:
        return {"ok": False, "sent": False, "premium_url": premium_url,
                "message": "Maxfiy guruh sozlanmagan"}

    if not _is_member(private_chat_id, user_id):
        return {"ok": False, "sent": False, "premium_url": premium_url,
                "message": "Siz premium obunachi emassiz"}

    # Aloqa qiymati = contact_field_key dan, yo'q bo'lsa phone/telefon fallback
    contact_value = ""
    if contact_key and contact_key in filled:
        contact_value = str(filled[contact_key] or "")
    if not contact_value:
        for k in ("phone", "telefon", "contact", "tel", "nomer"):
            if filled.get(k):
                contact_value = str(filled[k])
                break
    if not contact_value:
        return {"ok": False, "error": "contact_field bo'sh", "premium_url": premium_url}

    text = f"📞 Aloqa: <b>{contact_value}</b>\n\n🆔 E'lon #{ad_id}"
    try:
        sb = _tg_post("sendMessage", {
            "chat_id": user_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "true",
        })
        if not sb.get("ok"):
            return {"ok": False, "error": sb.get("description", "send_failed"), "premium_url": premium_url}
    except Exception as e:
        return {"ok": False, "error": f"send_failed: {e}", "premium_url": premium_url}

    return {"ok": True, "sent": True, "message": "Aloqa ma'lumoti yuborildi"}


# REJA10 helpers
def _tg_post(method: str, payload: dict):
    import urllib.parse, urllib.request
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=15) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            if not res.get("ok"):
                print(f"[REJA10 _tg_post] {method} failed: {res}", flush=True)
            return res
    except Exception as e:
        print(f"[REJA10 _tg_post] {method} EXC: {e}", flush=True)
        return {"ok": False, "description": str(e)}


def _is_member(chat_id, user_id) -> bool:
    import urllib.parse, urllib.request
    if not BOT_TOKEN:
        print("[REJA10 _is_member] BOT_TOKEN missing", flush=True)
        return False
    try:
        q = urllib.parse.urlencode({"chat_id": chat_id, "user_id": user_id})
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember?{q}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[REJA10 _is_member] EXC chat={chat_id} user={user_id}: {e}", flush=True)
        return False
    if not body.get("ok"):
        print(f"[REJA10 _is_member] NOT OK chat={chat_id} user={user_id}: {body}", flush=True)
        return False
    status = (body.get("result") or {}).get("status", "")
    is_mem = status in ("creator", "administrator", "member", "restricted")
    print(f"[REJA10 _is_member] chat={chat_id} user={user_id} status={status} → {is_mem}", flush=True)
    return is_mem


@app.post("/api/full-info/{ad_id}")
async def api_full_info(ad_id: int, payload: dict):
    """REJA10: To'liq ma'lumot tugmasi — maxfiy guruh postini (media+matn)
    userga DM qiladi. Faqat maxfiy guruh a'zolari uchun."""
    init_data = (payload or {}).get("init_data") or ""
    fallback_uid = (payload or {}).get("user_id")
    user_id: Optional[int] = None
    v = validate_init_data(init_data) if init_data else None
    if v and "user" in v:
        try:
            user_id = int(v["user"].get("id"))
        except Exception:
            user_id = None
    if not user_id and fallback_uid:
        try:
            user_id = int(fallback_uid)
        except Exception:
            user_id = None
    if not user_id:
        raise HTTPException(401, "user_id required")

    conn = db()
    try:
        ad = conn.execute(
            """SELECT id, filled_data, posted_chat_id, media_file_id, media_type, media_list,
                      private_posted_chat_id, private_posted_message_id
               FROM ads WHERE id=? AND status='approved'""",
            (ad_id,),
        ).fetchone()
        if not ad:
            raise HTTPException(404, "ad not found")
        tpl = None
        if ad["posted_chat_id"]:
            tpl = conn.execute(
                """SELECT t.private_chat_id, t.private_text_template, t.text_template,
                          t.premium_url, t.id_prefix
                   FROM templates t JOIN channels c ON c.id=t.channel_id
                   WHERE c.chat_id=? LIMIT 1""",
                (str(ad["posted_chat_id"]),),
            ).fetchone()
        try:
            filled = json.loads(ad["filled_data"] or "{}")
        except Exception:
            filled = {}
        try:
            media_list = json.loads(ad["media_list"] or "[]")
        except Exception:
            media_list = []
    finally:
        conn.close()

    if not tpl or not tpl["private_chat_id"]:
        return {"ok": False, "sent": False, "message": "Maxfiy guruh sozlanmagan"}

    premium_url = tpl["premium_url"] or ""
    private_chat_id = tpl["private_chat_id"]

    if not _is_member(private_chat_id, user_id):
        return {"ok": False, "sent": False, "premium_url": premium_url,
                "message": "Siz premium obunachi emassiz"}

    # 1-variant: forwardMessage — agar bizda maxfiy post ref bo'lsa
    if ad["private_posted_chat_id"] and ad["private_posted_message_id"]:
        try:
            sb = _tg_post("copyMessage", {
                "chat_id": user_id,
                "from_chat_id": ad["private_posted_chat_id"],
                "message_id": ad["private_posted_message_id"],
            })
            if sb.get("ok"):
                return {"ok": True, "sent": True, "message": "Post yuborildi"}
        except Exception:
            pass  # fallback to 2-variant

    # 2-variant: qayta qurish — private_text_template + media_list
    priv_tpl = tpl["private_text_template"] or tpl["text_template"] or ""
    prefix = (tpl["id_prefix"] or "_")
    extra = dict(filled)
    extra["ad_id"] = f"#{prefix}{ad_id:04d}"
    text = safe_format(priv_tpl, extra) or "—"

    try:
        CAPTION_LIMIT = 1024
        cap_fits = len(text) <= CAPTION_LIMIT
        if len(media_list) >= 2:
            items = []
            for i, m in enumerate(media_list[:10]):
                mtype = "video" if m.get("type") == "video" else "photo"
                item = {"type": mtype, "media": m.get("file_id")}
                if i == 0 and cap_fits:
                    item["caption"] = text
                    item["parse_mode"] = "HTML"
                items.append(item)
            sb = _tg_post("sendMediaGroup", {"chat_id": user_id, "media": json.dumps(items)})
            if not sb.get("ok"):
                return {"ok": False, "error": sb.get("description", "send_failed")}
            if not cap_fits:
                _tg_post("sendMessage", {"chat_id": user_id, "text": text,
                                         "parse_mode": "HTML", "disable_web_page_preview": "true"})
        elif ad["media_file_id"] and ad["media_type"] == "photo":
            p = {"chat_id": user_id, "photo": ad["media_file_id"], "parse_mode": "HTML"}
            if cap_fits: p["caption"] = text
            sb = _tg_post("sendPhoto", p)
            if not sb.get("ok"):
                return {"ok": False, "error": sb.get("description", "send_failed")}
            if not cap_fits:
                _tg_post("sendMessage", {"chat_id": user_id, "text": text, "parse_mode": "HTML"})
        elif ad["media_file_id"] and ad["media_type"] == "video":
            p = {"chat_id": user_id, "video": ad["media_file_id"], "parse_mode": "HTML"}
            if cap_fits: p["caption"] = text
            sb = _tg_post("sendVideo", p)
            if not sb.get("ok"):
                return {"ok": False, "error": sb.get("description", "send_failed")}
            if not cap_fits:
                _tg_post("sendMessage", {"chat_id": user_id, "text": text, "parse_mode": "HTML"})
        else:
            sb = _tg_post("sendMessage", {"chat_id": user_id, "text": text,
                                          "parse_mode": "HTML", "disable_web_page_preview": "true"})
            if not sb.get("ok"):
                return {"ok": False, "error": sb.get("description", "send_failed")}
    except Exception as e:
        return {"ok": False, "error": f"send_failed: {e}"}

    return {"ok": True, "sent": True, "message": "To'liq ma'lumot yuborildi"}


@app.get("/api/my-ads")
async def api_my_ads(init_data: str = Query("", alias="init_data"),
                     user_id: int = Query(0, alias="user_id")):
    """REJA10: User o'z e'lonlari ro'yxati."""
    uid = None
    v = validate_init_data(init_data) if init_data else None
    if v and "user" in v:
        try: uid = int(v["user"].get("id"))
        except Exception: uid = None
    if not uid and user_id:
        uid = int(user_id)
    if not uid:
        raise HTTPException(401, "user_id required")

    conn = db()
    try:
        rows = conn.execute(
            """SELECT id, filled_data, media_file_id, created_at, view_count, sold_at,
                      posted_chat_id, posted_message_id
               FROM ads WHERE user_id=? AND status='approved'
               ORDER BY id DESC LIMIT 100""",
            (uid,),
        ).fetchall()
        items = []
        for r in rows:
            try:
                d = json.loads(r["filled_data"] or "{}")
            except Exception:
                d = {}
            items.append({
                "id": r["id"],
                "title": d.get("title") or d.get("nomi") or f"E'lon #{r['id']}",
                "price": d.get("price") or d.get("narx") or d.get("narxi") or "",
                "created_at": r["created_at"],
                "view_count": r["view_count"] or 0,
                "sold": bool(r["sold_at"]),
                "thumb_url": f"api/thumb/{r['media_file_id']}" if r["media_file_id"] else None,
            })
        return {"items": items, "total": len(items)}
    finally:
        conn.close()


@app.post("/api/ads/{ad_id}/sold")
async def api_ad_sold(ad_id: int, payload: dict):
    """REJA10: Postni 'sotildi' deb belgilash.
    - filled_data'dagi sold_field_key → sold_replacement bilan almashtiriladi
    - Kanal va maxfiy guruh postlari edit qilinadi (matn yoki caption)
    - WebApp'da ham ko'rinishi o'zgaradi"""
    init_data = (payload or {}).get("init_data") or ""
    fallback_uid = (payload or {}).get("user_id")
    uid = None
    v = validate_init_data(init_data) if init_data else None
    if v and "user" in v:
        try: uid = int(v["user"].get("id"))
        except Exception: uid = None
    if not uid and fallback_uid:
        try: uid = int(fallback_uid)
        except Exception: uid = None
    if not uid:
        raise HTTPException(401, "user_id required")

    conn = db()
    try:
        ad = conn.execute(
            """SELECT id, user_id, filled_data, media_file_id, media_type, media_list,
                      posted_chat_id, posted_message_id,
                      private_posted_chat_id, private_posted_message_id,
                      sold_at
               FROM ads WHERE id=? AND status='approved'""",
            (ad_id,),
        ).fetchone()
        if not ad:
            raise HTTPException(404, "ad not found")
        if ad["user_id"] != uid:
            raise HTTPException(403, "not your ad")
        if ad["sold_at"]:
            return {"ok": True, "already_sold": True}
        tpl = None
        if ad["posted_chat_id"]:
            tpl = conn.execute(
                """SELECT t.text_template, t.private_text_template, t.id_prefix,
                          t.sold_field_key, t.sold_replacement
                   FROM templates t JOIN channels c ON c.id=t.channel_id
                   WHERE c.chat_id=? LIMIT 1""",
                (str(ad["posted_chat_id"]),),
            ).fetchone()
        try:
            filled = json.loads(ad["filled_data"] or "{}")
        except Exception:
            filled = {}
    finally:
        conn.close()

    if not tpl:
        raise HTTPException(400, "template missing")
    sold_key = tpl["sold_field_key"] or ""
    sold_val = tpl["sold_replacement"] or "🔴 SOTILDI"

    # filled_data'ni yangilaymiz
    new_filled = dict(filled)
    if sold_key:
        new_filled[sold_key] = sold_val
    else:
        # agar sold_field_key sozlanmagan bo'lsa — title/nomi bo'yicha
        for k in ("title", "nomi"):
            if k in new_filled:
                new_filled[k] = f"{sold_val} — {new_filled[k]}"
                break

    import datetime as _dt
    new_json = json.dumps(new_filled, ensure_ascii=False)

    conn = db()
    try:
        conn.execute(
            "UPDATE ads SET filled_data=?, sold_at=? WHERE id=?",
            (new_json, _dt.datetime.utcnow().isoformat(), ad_id),
        )
        conn.commit()
    finally:
        conn.close()

    prefix = tpl["id_prefix"] or "_"
    extra = dict(new_filled)
    extra["ad_id"] = f"#{prefix}{ad_id:04d}"

    # Kanal postini edit
    edit_errors = []
    if ad["posted_chat_id"] and ad["posted_message_id"] and tpl["text_template"]:
        new_public = safe_format(tpl["text_template"], extra)
        if "{ad_id}" not in tpl["text_template"]:
            new_public = f"{new_public}\n\n🆔 #{prefix}{ad_id:04d}"
        try:
            has_media = bool(ad["media_file_id"]) or bool((ad["media_list"] or "").strip() not in ("", "[]"))
            method = "editMessageCaption" if has_media else "editMessageText"
            key = "caption" if has_media else "text"
            sb = _tg_post(method, {
                "chat_id": ad["posted_chat_id"],
                "message_id": ad["posted_message_id"],
                key: new_public[:1024] if has_media else new_public,
                "parse_mode": "HTML",
            })
            if not sb.get("ok"):
                edit_errors.append(f"channel: {sb.get('description')}")
        except Exception as e:
            edit_errors.append(f"channel_ex: {e}")

    # Maxfiy guruh postini edit
    if ad["private_posted_chat_id"] and ad["private_posted_message_id"] and tpl["private_text_template"]:
        new_priv = safe_format(tpl["private_text_template"], extra)
        if "{ad_id}" not in (tpl["private_text_template"] or ""):
            new_priv = f"{new_priv}\n\n🆔 #{prefix}{ad_id:04d}"
        try:
            has_media = bool(ad["media_file_id"]) or bool((ad["media_list"] or "").strip() not in ("", "[]"))
            method = "editMessageCaption" if has_media else "editMessageText"
            key = "caption" if has_media else "text"
            sb = _tg_post(method, {
                "chat_id": ad["private_posted_chat_id"],
                "message_id": ad["private_posted_message_id"],
                key: new_priv[:1024] if has_media else new_priv,
                "parse_mode": "HTML",
            })
            if not sb.get("ok"):
                edit_errors.append(f"private: {sb.get('description')}")
        except Exception as e:
            edit_errors.append(f"private_ex: {e}")

    return {"ok": True, "sold": True, "edit_errors": edit_errors}


@app.post("/api/ads/{ad_id}/view")
async def api_ad_view(ad_id: int):
    conn = db()
    try:
        conn.execute(
            "UPDATE ads SET view_count=COALESCE(view_count,0)+1 WHERE id=? AND status='approved'",
            (ad_id,),
        )
        conn.commit()
        r = conn.execute("SELECT view_count FROM ads WHERE id=?", (ad_id,)).fetchone()
        return {"view_count": r["view_count"] if r else 0}
    finally:
        conn.close()


# --------- Thumbnail proxy with disk cache ---------
@app.get("/api/thumb/{file_id}")
async def api_thumb(file_id: str):
    import urllib.request
    if not BOT_TOKEN:
        raise HTTPException(500, "no token")
    # sanitize file_id into filename
    safe = hashlib.sha256(file_id.encode()).hexdigest()[:32]
    cache_file = CACHE_DIR / f"thumb_{safe}.bin"
    meta_file = CACHE_DIR / f"thumb_{safe}.meta"
    if cache_file.exists() and meta_file.exists():
        try:
            mime = meta_file.read_text().strip() or "image/jpeg"
            return FileResponse(
                str(cache_file),
                media_type=mime,
                headers={"Cache-Control": "public, max-age=604800"},
            )
        except Exception:
            pass
    try:
        info_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        with urllib.request.urlopen(info_url, timeout=10) as resp:
            body = json.loads(resp.read())
        if not body.get("ok"):
            raise HTTPException(404, "file not found")
        file_path = body["result"]["file_path"]
        direct = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        with urllib.request.urlopen(direct, timeout=20) as resp:
            data = resp.read()
            ct = resp.headers.get("Content-Type", "application/octet-stream")
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(413, "file too large")
        cache_file.write_bytes(data)
        meta_file.write_text(ct)
        return Response(
            content=data,
            media_type=ct,
            headers={"Cache-Control": "public, max-age=604800"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"thumb error: {e}")


@app.get("/api/media/{file_id}")
async def api_media(file_id: str):
    """Legacy: return direct Telegram URL (short-lived)."""
    import urllib.request
    import urllib.parse
    if not BOT_TOKEN:
        raise HTTPException(500, "no token")
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={urllib.parse.quote(file_id)}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = json.loads(resp.read())
        if not body.get("ok"):
            raise HTTPException(404, "file not found")
        file_path = body["result"]["file_path"]
        direct = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        return JSONResponse({"url": direct}, headers={"Cache-Control": "public, max-age=1800"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"proxy error: {e}")


# --------- Saved searches ---------
@app.get("/api/saved_searches")
async def api_saved_list(request: Request, init_data: str = Query(..., alias="init_data")):
    uid = require_user(init_data)
    conn = db()
    try:
        rows = conn.execute(
            "SELECT id, query, category_id, location, price_min, price_max, created_at "
            "FROM saved_searches WHERE user_id=? ORDER BY id DESC",
            (uid,),
        ).fetchall()
        return {"items": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.post("/api/saved_searches")
async def api_saved_create(request: Request):
    body = await request.json()
    init_data = body.get("init_data", "")
    uid = require_user(init_data)
    q = (body.get("query") or "").strip()[:200]
    category_id = body.get("category_id")
    location = (body.get("location") or "").strip()[:80] or None
    price_min = body.get("price_min")
    price_max = body.get("price_max")
    if not q and not category_id and not location:
        raise HTTPException(400, "empty filter")
    conn = db()
    try:
        # latest ad id to avoid spamming old ads
        last = conn.execute("SELECT COALESCE(MAX(id),0) FROM ads").fetchone()[0]
        cur = conn.execute(
            """INSERT INTO saved_searches
               (user_id, query, category_id, location, price_min, price_max,
                last_notified_ad_id, created_at)
               VALUES (?,?,?,?,?,?,?,datetime('now'))""",
            (uid, q, category_id, location, price_min, price_max, last),
        )
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@app.delete("/api/saved_searches/{sid}")
async def api_saved_delete(sid: int, init_data: str = Query(...)):
    uid = require_user(init_data)
    conn = db()
    try:
        conn.execute("DELETE FROM saved_searches WHERE id=? AND user_id=?", (sid, uid))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


# --------- Admin panel (HTTP basic auth) ---------
def _admin_auth(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(auth[6:]).decode()
        user, _, pwd = raw.partition(":")
        return secrets.compare_digest(pwd, ADMIN_PASSWORD)
    except Exception:
        return False


@app.get("/admin")
async def admin_panel(request: Request):
    if not _admin_auth(request):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="admin"'},
            content="auth required",
        )
    html = (BASE_DIR / "static" / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/admin/api/stats")
async def admin_stats(request: Request):
    if not _admin_auth(request):
        raise HTTPException(401)
    conn = db()
    try:
        totals = {
            "ads_total": conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0],
            "ads_approved": conn.execute("SELECT COUNT(*) FROM ads WHERE status='approved'").fetchone()[0],
            "ads_pending": conn.execute("SELECT COUNT(*) FROM ads WHERE status='pending'").fetchone()[0],
            "ads_rejected": conn.execute("SELECT COUNT(*) FROM ads WHERE status='rejected'").fetchone()[0],
            "users_total": conn.execute(
                "SELECT COUNT(DISTINCT user_id) FROM ads"
            ).fetchone()[0],
            "views_total": conn.execute(
                "SELECT COALESCE(SUM(view_count),0) FROM ads"
            ).fetchone()[0],
            "channels": conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0],
            "saved_searches": conn.execute("SELECT COUNT(*) FROM saved_searches").fetchone()[0],
        }
        # per-day last 14 days
        rows = conn.execute(
            """SELECT SUBSTR(created_at,1,10) AS d, COUNT(*) AS c
               FROM ads
               WHERE created_at >= date('now','-14 days')
               GROUP BY d ORDER BY d ASC"""
        ).fetchall()
        by_day = [dict(r) for r in rows]
        # top categories
        rows = conn.execute(
            """SELECT rn.text AS title, COUNT(a.id) AS c
               FROM ads a JOIN routing_nodes rn ON rn.id=a.category_id
               WHERE a.status='approved'
               GROUP BY a.category_id ORDER BY c DESC LIMIT 10"""
        ).fetchall()
        top_cats = [dict(r) for r in rows]
        # top ads by views
        rows = conn.execute(
            """SELECT id, view_count, SUBSTR(filled_data,1,80) AS preview
               FROM ads WHERE status='approved'
               ORDER BY view_count DESC LIMIT 10"""
        ).fetchall()
        top_ads = [dict(r) for r in rows]
        return {"totals": totals, "by_day": by_day, "top_cats": top_cats, "top_ads": top_ads}
    finally:
        conn.close()
