import aiosqlite
import json
from datetime import datetime
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL DEFAULT 0,
                name TEXT NOT NULL,
                chat_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                text_template TEXT NOT NULL,
                button_label TEXT,
                button_caption TEXT,
                button_url TEXT,
                button_url_by_user INTEGER DEFAULT 0,
                media_required INTEGER DEFAULT 0,
                private_chat_id TEXT,
                private_text_template TEXT,
                id_prefix TEXT DEFAULT '_',
                FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS template_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                question TEXT NOT NULL,
                order_idx INTEGER NOT NULL DEFAULT 0,
                show_in_public INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                filled_data TEXT NOT NULL,
                media_file_id TEXT,
                media_type TEXT,
                custom_url TEXT,
                target_channels TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                reject_reason TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        # Migration: add owner_id if missing
        cur = await db.execute("PRAGMA table_info(channels)")
        cols = [r[1] for r in await cur.fetchall()]
        if "owner_id" not in cols:
            await db.execute("ALTER TABLE channels ADD COLUMN owner_id INTEGER NOT NULL DEFAULT 0")
        cur = await db.execute("PRAGMA table_info(templates)")
        tcols = [r[1] for r in await cur.fetchall()]
        if "private_chat_id" not in tcols:
            await db.execute("ALTER TABLE templates ADD COLUMN private_chat_id TEXT")
        if "private_text_template" not in tcols:
            await db.execute("ALTER TABLE templates ADD COLUMN private_text_template TEXT")
        if "id_prefix" not in tcols:
            await db.execute("ALTER TABLE templates ADD COLUMN id_prefix TEXT DEFAULT '_'")
        if "premium_url" not in tcols:
            await db.execute("ALTER TABLE templates ADD COLUMN premium_url TEXT")
        # channels migration — button_label
        cur = await db.execute("PRAGMA table_info(channels)")
        chcols = [r[1] for r in await cur.fetchall()]
        if "button_label" not in chcols:
            await db.execute("ALTER TABLE channels ADD COLUMN button_label TEXT")
        cur = await db.execute("PRAGMA table_info(ads)")
        acols = [r[1] for r in await cur.fetchall()]
        if "media_list" not in acols:
            await db.execute("ALTER TABLE ads ADD COLUMN media_list TEXT")
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                added_by INTEGER,
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_grants (
                user_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                chat_title TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS survey_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                is_root INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS survey_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                next_question_id INTEGER,
                position INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(question_id) REFERENCES survey_questions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS survey_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                question_id INTEGER NOT NULL,
                option_id INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                option_text TEXT NOT NULL,
                answered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS survey_sessions (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                current_question_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS super_admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                added_by INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routing_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER,
                text TEXT NOT NULL,
                is_question INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(parent_id) REFERENCES routing_nodes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS routing_node_channels (
                node_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                PRIMARY KEY (node_id, channel_id),
                FOREIGN KEY(node_id) REFERENCES routing_nodes(id) ON DELETE CASCADE,
                FOREIGN KEY(channel_id) REFERENCES channels(id) ON DELETE CASCADE
            );
            """
        )
        # Migration: template_fields — done_replace, done_text
        cur = await db.execute("PRAGMA table_info(template_fields)")
        tf_cols = [r[1] for r in await cur.fetchall()]
        if "done_replace" not in tf_cols:
            await db.execute("ALTER TABLE template_fields ADD COLUMN done_replace INTEGER NOT NULL DEFAULT 0")
        if "done_text" not in tf_cols:
            await db.execute("ALTER TABLE template_fields ADD COLUMN done_text TEXT")
        # Migration: ads — posted_message_id, posted_chat_id, group_message_id, group_chat_id
        cur = await db.execute("PRAGMA table_info(ads)")
        ads_cols = [r[1] for r in await cur.fetchall()]
        for col, typ in [
            ("posted_message_id", "INTEGER"),
            ("posted_chat_id", "TEXT"),
            ("group_message_id", "INTEGER"),
            ("group_chat_id", "TEXT"),
            ("category_id", "INTEGER"),
            ("view_count", "INTEGER DEFAULT 0"),
        ]:
            if col not in ads_cols:
                await db.execute(f"ALTER TABLE ads ADD COLUMN {col} {typ}")

        # routing_nodes.icon migration
        try:
            cur = await db.execute("PRAGMA table_info(routing_nodes)")
            rcols = [r[1] for r in await cur.fetchall()]
            if rcols and "icon" not in rcols:
                await db.execute("ALTER TABLE routing_nodes ADD COLUMN icon TEXT")
        except Exception:
            pass

        # saved_searches table
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS saved_searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                category_id INTEGER,
                location TEXT,
                price_min INTEGER,
                price_max INTEGER,
                last_notified_ad_id INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_saved_searches_user ON saved_searches(user_id);
            CREATE INDEX IF NOT EXISTS idx_ads_status_id ON ads(status, id DESC);
            CREATE INDEX IF NOT EXISTS idx_ads_category ON ads(category_id, status);
            """
        )
        await db.commit()


# ---------- admins ----------
async def add_admin(user_id: int, username: str | None, full_name: str | None, added_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO admins(user_id, username, full_name, added_by, added_at) VALUES(?,?,?,?,?)",
            (user_id, username, full_name, added_by, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def remove_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE user_id=?", (user_id,))
        await db.commit()


async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        return (await cur.fetchone()) is not None


async def list_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM admins ORDER BY added_at")
        return await cur.fetchall()


# ---------- pending_grants (membership so'rovlari) ----------
async def save_pending_grant(user_id: int, chat_id: str, chat_title: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO pending_grants(user_id, chat_id, chat_title, created_at) VALUES(?,?,?,?)",
            (user_id, chat_id, chat_title, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def get_pending_grants_for_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM pending_grants WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        )
        return await cur.fetchall()


async def delete_pending_grants_for_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM pending_grants WHERE user_id=?", (user_id,))
        await db.commit()


# ---------- channels ----------
async def add_channel(owner_id: int, name: str, chat_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO channels(owner_id, name, chat_id, created_at) VALUES(?,?,?,?)",
            (owner_id, name, chat_id, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def get_channel_by_chat_id(chat_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM channels WHERE chat_id=?", (str(chat_id),))
        return await cur.fetchone()


async def list_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM channels ORDER BY id")
        return await cur.fetchall()


async def list_channels_by_owner(owner_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM channels WHERE owner_id=? ORDER BY id", (owner_id,)
        )
        return await cur.fetchall()


async def get_channel(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM channels WHERE id=?", (channel_id,))
        return await cur.fetchone()


async def delete_channel(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM template_fields WHERE channel_id=?", (channel_id,))
        await db.execute("DELETE FROM templates WHERE channel_id=?", (channel_id,))
        await db.execute("DELETE FROM channels WHERE id=?", (channel_id,))
        await db.commit()


async def update_channel(channel_id: int, name: str, chat_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE channels SET name=?, chat_id=? WHERE id=?",
            (name, chat_id, channel_id),
        )
        await db.commit()


# ---------- templates ----------
async def upsert_template(
    channel_id: int,
    text_template: str,
    button_label: str | None,
    button_caption: str | None,
    button_url: str | None,
    button_url_by_user: bool,
    media_required: bool,
    private_chat_id: str | None = None,
    private_text_template: str | None = None,
    id_prefix: str = "_",
    premium_url: str | None = None,
    contact_field_key: str | None = None,
    sold_field_key: str | None = None,
    sold_replacement: str | None = None,
    telegram_field_key: str | None = None,
    sold_rules: str | None = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id FROM templates WHERE channel_id=?", (channel_id,)
        )
        row = await cur.fetchone()
        if row:
            await db.execute(
                """UPDATE templates SET text_template=?, button_label=?,
                   button_caption=?, button_url=?, button_url_by_user=?,
                   media_required=?, private_chat_id=?, private_text_template=?,
                   id_prefix=?, premium_url=?,
                   contact_field_key=?, sold_field_key=?, sold_replacement=?,
                   telegram_field_key=?, sold_rules=?
                   WHERE channel_id=?""",
                (
                    text_template,
                    button_label,
                    button_caption,
                    button_url,
                    int(button_url_by_user),
                    int(media_required),
                    private_chat_id,
                    private_text_template,
                    id_prefix,
                    premium_url,
                    contact_field_key,
                    sold_field_key,
                    sold_replacement,
                    telegram_field_key,
                    sold_rules if sold_rules is not None else "",
                    channel_id,
                ),
            )
        else:
            await db.execute(
                """INSERT INTO templates(channel_id, text_template, button_label,
                   button_caption, button_url, button_url_by_user, media_required,
                   private_chat_id, private_text_template, id_prefix, premium_url,
                   contact_field_key, sold_field_key, sold_replacement, telegram_field_key, sold_rules)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    channel_id,
                    text_template,
                    button_label,
                    button_caption,
                    button_url,
                    int(button_url_by_user),
                    int(media_required),
                    private_chat_id,
                    private_text_template,
                    id_prefix,
                    premium_url,
                    contact_field_key,
                    sold_field_key,
                    sold_replacement,
                    telegram_field_key,
                    sold_rules if sold_rules is not None else "",
                ),
            )
        await db.commit()


async def get_template(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM templates WHERE channel_id=?", (channel_id,)
        )
        return await cur.fetchone()


# ---------- template_fields (dinamik savollar) ----------
async def replace_fields(channel_id: int, fields: list[dict]):
    """
    fields: [{"key": "telefon", "question": "Telefon raqamingizni kiriting",
              "show_in_public": True}, ...]
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM template_fields WHERE channel_id=?", (channel_id,))
        for i, f in enumerate(fields):
            await db.execute(
                """INSERT INTO template_fields(channel_id, key, question, order_idx, show_in_public)
                   VALUES(?,?,?,?,?)""",
                (
                    channel_id,
                    f["key"],
                    f["question"],
                    i,
                    int(bool(f.get("show_in_public", True))),
                ),
            )
        await db.commit()


async def list_fields(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM template_fields WHERE channel_id=? ORDER BY order_idx",
            (channel_id,),
        )
        return await cur.fetchall()


# ---------- ads ----------
async def create_ad(
    user_id: int,
    username: str | None,
    filled_data: dict,
    media_file_id: str | None,
    media_type: str | None,
    custom_url: str | None,
    target_channels: list[int],
    media_list: list | None = None,
    category_id: int | None = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO ads(user_id, username, filled_data, media_file_id,
               media_type, custom_url, target_channels, status, created_at, media_list, category_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user_id,
                username,
                json.dumps(filled_data, ensure_ascii=False),
                media_file_id,
                media_type,
                custom_url,
                json.dumps(target_channels),
                "pending",
                datetime.utcnow().isoformat(),
                json.dumps(media_list or [], ensure_ascii=False),
                category_id,
            ),
        )
        await db.commit()
        return cur.lastrowid


async def get_ad(ad_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
        return await cur.fetchone()


async def list_user_ads(user_id: int, limit: int = 15):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ads WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        )
        return await cur.fetchall()


async def user_ad_stats(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected
            FROM ads
            WHERE user_id=?
            """,
            (user_id,),
        )
        row = await cur.fetchone()
        return {
            "total": int(row["total"] or 0),
            "pending": int(row["pending"] or 0),
            "approved": int(row["approved"] or 0),
            "rejected": int(row["rejected"] or 0),
        }


async def search_approved_ads(keyword: str | None = None, limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if keyword and keyword.strip():
            q = f"%{keyword.strip()}%"
            cur = await db.execute(
                """
                SELECT * FROM ads
                WHERE status='approved'
                  AND (
                    filled_data LIKE ? OR
                    COALESCE(username, '') LIKE ? OR
                    COALESCE(custom_url, '') LIKE ?
                  )
                ORDER BY id DESC
                LIMIT ?
                """,
                (q, q, q, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM ads WHERE status='approved' ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return await cur.fetchall()


async def set_ad_status(ad_id: int, status: str, reason: str | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET status=?, reject_reason=? WHERE id=?",
            (status, reason, ad_id),
        )
        await db.commit()


async def list_owner_pending_ads(owner_id: int, limit: int = 20):
    """Owner kanallariga tegishli pending reklamalar."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id FROM channels WHERE owner_id=?", (owner_id,)
        )
        ch_rows = await cur.fetchall()
        ch_ids = [r["id"] for r in ch_rows]
        if not ch_ids:
            return []
        cur = await db.execute(
            "SELECT * FROM ads WHERE status='pending' ORDER BY id DESC LIMIT ?",
            (limit * 3,),
        )
        rows = await cur.fetchall()
        out = []
        for r in rows:
            try:
                tgt = json.loads(r["target_channels"] or "[]")
            except Exception:
                tgt = []
            if any(int(t) in ch_ids for t in tgt):
                out.append(r)
            if len(out) >= limit:
                break
        return out


async def channel_stats_for_owner(owner_id: int):
    """Owner'ning har bir kanali bo'yicha statistika."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM channels WHERE owner_id=? ORDER BY id", (owner_id,)
        )
        chs = await cur.fetchall()
        out = []
        for c in chs:
            cur = await db.execute("SELECT * FROM ads")
            all_ads = await cur.fetchall()
            total = pending = approved = rejected = 0
            for a in all_ads:
                try:
                    tgt = json.loads(a["target_channels"] or "[]")
                except Exception:
                    tgt = []
                if c["id"] in [int(t) for t in tgt]:
                    total += 1
                    if a["status"] == "pending":
                        pending += 1
                    elif a["status"] == "approved":
                        approved += 1
                    elif a["status"] == "rejected":
                        rejected += 1
            out.append({
                "id": c["id"],
                "name": c["name"],
                "total": total,
                "pending": pending,
                "approved": approved,
                "rejected": rejected,
            })
        return out


async def global_stats():
    """Super admin uchun umumiy statistika."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status='approved' THEN 1 ELSE 0 END) AS approved,
                SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected,
                COUNT(DISTINCT user_id) AS users
            FROM ads
            """
        )
        row = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*) AS c FROM channels")
        ch = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*) AS c FROM admins")
        ad = await cur.fetchone()
        return {
            "total_ads": int(row["total"] or 0),
            "pending": int(row["pending"] or 0),
            "approved": int(row["approved"] or 0),
            "rejected": int(row["rejected"] or 0),
            "unique_users": int(row["users"] or 0),
            "channels": int(ch["c"] or 0),
            "admins": int(ad["c"] or 0),
        }


async def count_active_channels() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM channels")
        (c,) = await cur.fetchone()
        return int(c or 0)


async def count_approved_ads() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM ads WHERE status='approved'")
        (c,) = await cur.fetchone()
        return int(c or 0)


async def channel_counts(ch_id: int) -> dict:
    """Bitta kanal bo'yicha pending/approved soni."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT status, target_channels FROM ads")
        rows = await cur.fetchall()
        pending = approved = 0
        for r in rows:
            try:
                tgt = json.loads(r["target_channels"] or "[]")
            except Exception:
                tgt = []
            if ch_id in [int(t) for t in tgt]:
                if r["status"] == "pending":
                    pending += 1
                elif r["status"] == "approved":
                    approved += 1
        return {"pending": pending, "approved": approved}


async def list_user_ads_by_status(user_id: int, status: str | None, limit: int = 20):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status and status != "all":
            cur = await db.execute(
                "SELECT * FROM ads WHERE user_id=? AND status=? ORDER BY id DESC LIMIT ?",
                (user_id, status, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM ads WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
        return await cur.fetchall()


async def user_has_pending(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM ads WHERE user_id=? AND status='pending'",
            (user_id,),
        )
        (c,) = await cur.fetchone()
        return c > 0


# ============================================================
# SURVEY / STATISTIKA
# ============================================================

async def survey_add_question(text: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM survey_questions")
        (cnt,) = await cur.fetchone()
        is_root = 1 if cnt == 0 else 0
        cur = await db.execute(
            "INSERT INTO survey_questions(position, text, is_root, created_at) VALUES(?, ?, ?, ?)",
            (cnt, text, is_root, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def survey_update_question(qid: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE survey_questions SET text=? WHERE id=?", (text, qid))
        await db.commit()


async def survey_delete_question(qid: int):
    """Savol o'chiriladi. Unga ishora qilgan optionlarning next_question_id NULL qilinadi."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE survey_options SET next_question_id=NULL WHERE next_question_id=?", (qid,))
        await db.execute("DELETE FROM survey_options WHERE question_id=?", (qid,))
        await db.execute("DELETE FROM survey_questions WHERE id=?", (qid,))
        # Agar root o'chgan bo'lsa — birinchi qolgan savolni root qilamiz
        cur = await db.execute("SELECT id FROM survey_questions WHERE is_root=1")
        r = await cur.fetchone()
        if not r:
            cur = await db.execute("SELECT id FROM survey_questions ORDER BY position LIMIT 1")
            r = await cur.fetchone()
            if r:
                await db.execute("UPDATE survey_questions SET is_root=1 WHERE id=?", (r[0],))
        await db.commit()


async def survey_get_question(qid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM survey_questions WHERE id=?", (qid,))
        return await cur.fetchone()


async def survey_list_questions():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM survey_questions ORDER BY position, id")
        return await cur.fetchall()


async def survey_get_root_question():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM survey_questions WHERE is_root=1 LIMIT 1")
        return await cur.fetchone()


async def survey_set_root(qid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE survey_questions SET is_root=0")
        await db.execute("UPDATE survey_questions SET is_root=1 WHERE id=?", (qid,))
        await db.commit()


async def survey_add_option(qid: int, text: str, next_qid: int | None = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM survey_options WHERE question_id=?", (qid,))
        (cnt,) = await cur.fetchone()
        cur = await db.execute(
            "INSERT INTO survey_options(question_id, text, next_question_id, position) VALUES(?, ?, ?, ?)",
            (qid, text, next_qid, cnt),
        )
        await db.commit()
        return cur.lastrowid


async def survey_update_option(oid: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE survey_options SET text=? WHERE id=?", (text, oid))
        await db.commit()


async def survey_set_option_next(oid: int, next_qid: int | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE survey_options SET next_question_id=? WHERE id=?", (next_qid, oid))
        await db.commit()


async def survey_delete_option(oid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM survey_options WHERE id=?", (oid,))
        await db.commit()


async def survey_get_option(oid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM survey_options WHERE id=?", (oid,))
        return await cur.fetchone()


async def survey_list_options(qid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM survey_options WHERE question_id=? ORDER BY position, id", (qid,))
        return await cur.fetchall()


async def survey_session_get(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM survey_sessions WHERE user_id=?", (user_id,))
        return await cur.fetchone()


async def survey_session_start(user_id: int, username: str | None, full_name: str | None, phone: str | None, first_qid: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO survey_sessions(user_id, username, full_name, phone, started_at, current_question_id)
               VALUES(?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                 username=excluded.username, full_name=excluded.full_name,
                 phone=COALESCE(excluded.phone, survey_sessions.phone),
                 started_at=excluded.started_at, completed_at=NULL,
                 current_question_id=excluded.current_question_id""",
            (user_id, username, full_name, phone, datetime.utcnow().isoformat(), first_qid),
        )
        await db.commit()


async def survey_session_set_phone(user_id: int, phone: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE survey_sessions SET phone=? WHERE user_id=?", (phone, user_id))
        await db.commit()


async def survey_session_set_current(user_id: int, qid: int | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE survey_sessions SET current_question_id=? WHERE user_id=?", (qid, user_id))
        await db.commit()


async def survey_session_complete(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE survey_sessions SET completed_at=?, current_question_id=NULL WHERE user_id=?",
            (datetime.utcnow().isoformat(), user_id),
        )
        await db.commit()


async def survey_has_completed(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT completed_at FROM survey_sessions WHERE user_id=?", (user_id,))
        r = await cur.fetchone()
        return bool(r and r[0])


async def survey_save_answer(user_id: int, username: str | None, full_name: str | None, phone: str | None,
                              question_id: int, option_id: int, question_text: str, option_text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO survey_answers(user_id, username, full_name, phone, question_id, option_id,
                                          question_text, option_text, answered_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (user_id, username, full_name, phone, question_id, option_id,
             question_text, option_text, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def survey_clear_all_answers():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM survey_answers")
        await db.execute("DELETE FROM survey_sessions")
        await db.commit()


async def survey_export_rows():
    """Excel uchun. Har user uchun 1 qator, har savol ustun.
    O'chirilgan savollar ham qo'shiladi (answers jadvalidan snapshot orqali)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q_cur = await db.execute("SELECT id, text FROM survey_questions ORDER BY position, id")
        questions = await q_cur.fetchall()
        s_cur = await db.execute("SELECT * FROM survey_sessions ORDER BY user_id")
        sessions = await s_cur.fetchall()
        a_cur = await db.execute("SELECT * FROM survey_answers ORDER BY answered_at")
        answers = await a_cur.fetchall()

    # Savollar: mavjudlar + o'chirilganlar (answers'dan)
    seen_qids = set()
    questions_list = []
    for q in questions:
        questions_list.append({"id": q["id"], "text": q["text"]})
        seen_qids.add(q["id"])
    # answers'da bor, lekin questions'da yo'q savollarni qo'shamiz
    extra = {}
    for a in answers:
        if a["question_id"] not in seen_qids:
            extra[a["question_id"]] = a["question_text"]
    for qid in sorted(extra):
        questions_list.append({"id": qid, "text": extra[qid] + " (o'chirilgan)"})

    # user_id -> {qid: option_text}
    by_user: dict = {}
    for a in answers:
        by_user.setdefault(a["user_id"], {})[a["question_id"]] = a["option_text"]

    # Sessiyasiz userlar ham bo'lishi mumkin (answers bor, session yo'q)
    user_meta = {}
    for s in sessions:
        user_meta[s["user_id"]] = {
            "username": s["username"],
            "full_name": s["full_name"],
            "phone": s["phone"],
            "completed": "Ha" if s["completed_at"] else "Yo'q",
        }
    for a in answers:
        uid = a["user_id"]
        if uid not in user_meta:
            user_meta[uid] = {
                "username": a["username"],
                "full_name": a["full_name"],
                "phone": a["phone"],
                "completed": "—",
            }

    rows = []
    for uid, meta in user_meta.items():
        user_answers = by_user.get(uid, {})
        row = {
            "user_id": uid,
            "username": meta["username"],
            "full_name": meta["full_name"],
            "phone": meta["phone"],
            "completed": meta["completed"],
            "answers": {q["id"]: user_answers.get(q["id"], "") for q in questions_list},
        }
        rows.append(row)

    # Batafsil log (har qator = bitta javob)
    detail = []
    for a in answers:
        detail.append({
            "user_id": a["user_id"],
            "username": a["username"] or "",
            "full_name": a["full_name"] or "",
            "phone": a["phone"] or "",
            "question_text": a["question_text"],
            "option_text": a["option_text"],
            "answered_at": a["answered_at"],
        })
    return {"questions": questions_list, "rows": rows, "detail": detail}


# ---------- settings (key-value) ----------
async def get_setting(key: str, default: str | None = None) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        await db.commit()


# ---------- channels: button_label ----------
async def set_channel_button_label(channel_id: int, label: str | None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE channels SET button_label=? WHERE id=?",
            (label, channel_id),
        )
        await db.commit()


# ---------- super_admins (dinamik) ----------
async def sa_list():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM super_admins ORDER BY created_at ASC")
        return await cur.fetchall()


async def sa_add(user_id: int, username: str | None, full_name: str | None, added_by: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO super_admins(user_id, username, full_name, added_by, created_at) VALUES(?,?,?,?,?)",
            (user_id, username, full_name, added_by, datetime.utcnow().isoformat()),
        )
        await db.commit()


async def sa_remove(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM super_admins WHERE user_id=?", (user_id,))
        await db.commit()


async def sa_db_ids() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM super_admins")
        return [r[0] for r in await cur.fetchall()]


# ---------- routing tree (kanal tanlash daraxti) ----------
async def routing_get_root_question():
    """Root savol — parent_id IS NULL va is_question=1 bo'lgan node."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM routing_nodes WHERE parent_id IS NULL AND is_question=1 ORDER BY id ASC LIMIT 1"
        )
        return await cur.fetchone()


async def routing_create_node(parent_id: int | None, text: str, is_question: int, position: int = 0) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO routing_nodes(parent_id, text, is_question, position, created_at) VALUES(?,?,?,?,?)",
            (parent_id, text, is_question, position, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def routing_update_text(node_id: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE routing_nodes SET text=? WHERE id=?", (text, node_id))
        await db.commit()


async def routing_delete_node(node_id: int):
    """Cascade: FK ON DELETE CASCADE bor, lekin PRAGMA foreign_keys=ON kerak."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA foreign_keys=ON")
        await db.execute("DELETE FROM routing_nodes WHERE id=?", (node_id,))
        await db.commit()


async def routing_get_node(node_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM routing_nodes WHERE id=?", (node_id,))
        return await cur.fetchone()


async def routing_list_children(parent_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM routing_nodes WHERE parent_id=? ORDER BY position ASC, id ASC",
            (parent_id,),
        )
        return await cur.fetchall()


async def routing_is_leaf(node_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM routing_nodes WHERE parent_id=?", (node_id,))
        row = await cur.fetchone()
        return (row[0] or 0) == 0


async def routing_set_node_channels(node_id: int, channel_ids: list[int]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM routing_node_channels WHERE node_id=?", (node_id,))
        for cid in channel_ids:
            await db.execute(
                "INSERT OR IGNORE INTO routing_node_channels(node_id, channel_id) VALUES(?,?)",
                (node_id, cid),
            )
        await db.commit()


async def routing_get_node_channels(node_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT channel_id FROM routing_node_channels WHERE node_id=?", (node_id,)
        )
        return [r[0] for r in await cur.fetchall()]


async def routing_toggle_channel(node_id: int, channel_id: int) -> bool:
    """Return True if now linked, False if removed."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM routing_node_channels WHERE node_id=? AND channel_id=?",
            (node_id, channel_id),
        )
        exists = await cur.fetchone()
        if exists:
            await db.execute(
                "DELETE FROM routing_node_channels WHERE node_id=? AND channel_id=?",
                (node_id, channel_id),
            )
            await db.commit()
            return False
        await db.execute(
            "INSERT INTO routing_node_channels(node_id, channel_id) VALUES(?,?)",
            (node_id, channel_id),
        )
        await db.commit()
        return True


# ---------- template_fields: done rules ----------
async def field_set_done_rule(field_id: int, replace: int, text: str | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE template_fields SET done_replace=?, done_text=? WHERE id=?",
            (replace, text, field_id),
        )
        await db.commit()


async def field_toggle_done(field_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT done_replace FROM template_fields WHERE id=?", (field_id,))
        row = await cur.fetchone()
        cur_val = (row[0] if row else 0) or 0
        new_val = 0 if cur_val else 1
        await db.execute("UPDATE template_fields SET done_replace=? WHERE id=?", (new_val, field_id))
        await db.commit()
        return new_val


async def get_field(field_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM template_fields WHERE id=?", (field_id,))
        return await cur.fetchone()


# ---------- ads: posted refs + status ----------
async def set_ad_posted_refs(ad_id: int, posted_chat_id: str | None, posted_message_id: int | None,
                              group_chat_id: str | None = None, group_message_id: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET posted_chat_id=?, posted_message_id=?, group_chat_id=?, group_message_id=? WHERE id=?",
            (posted_chat_id, posted_message_id, group_chat_id, group_message_id, ad_id),
        )
        await db.commit()


async def set_ad_private_refs(ad_id: int, private_chat_id: str | None, private_message_id: int | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET private_posted_chat_id=?, private_posted_message_id=? WHERE id=?",
            (private_chat_id, private_message_id, ad_id),
        )
        await db.commit()


async def mark_ad_sold(ad_id: int, new_filled_data_json: str):
    """Mark ad as sold and update filled_data (sold_field replaced)."""
    from datetime import datetime, timezone
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET filled_data=?, sold_at=? WHERE id=?",
            (new_filled_data_json, datetime.now(timezone.utc).isoformat(), ad_id),
        )
        await db.commit()


async def list_user_ads(user_id: int, limit: int = 50):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT id, filled_data, media_file_id, created_at, sold_at,
                      posted_chat_id, posted_message_id,
                      private_posted_chat_id, private_posted_message_id,
                      view_count
               FROM ads
               WHERE user_id=? AND status='approved'
               ORDER BY id DESC LIMIT ?""",
            (user_id, limit),
        )
        return await cur.fetchall()


async def get_ad_full(ad_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM ads WHERE id=?", (ad_id,))
        return await cur.fetchone()


# ---------- alias/missing helpers ----------
async def routing_update_node(node_id: int, text: str):
    await routing_update_text(node_id, text)


async def routing_delete_subtree(node_id: int):
    # routing_nodes ON DELETE CASCADE bo'lgani uchun bitta delete yetarli
    await routing_delete_node(node_id)


async def routing_link_channel(node_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO routing_node_channels (node_id, channel_id) VALUES (?, ?)",
            (node_id, channel_id),
        )
        await db.commit()


async def routing_unlink_channel(node_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM routing_node_channels WHERE node_id=? AND channel_id=?",
            (node_id, channel_id),
        )
        await db.commit()


async def update_ad_posted(ad_id: int, posted_chat_id: int | None, posted_message_id: int | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE ads SET posted_chat_id=?, posted_message_id=? WHERE id=?",
            (posted_chat_id, posted_message_id, ad_id),
        )
        await db.commit()
