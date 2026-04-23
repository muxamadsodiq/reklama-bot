# REJA10 — WebApp: 2 tugma (Aloqa + To'liq ma'lumot) + Postlarim + Sold flow

## Maqsad
1. WebApp detail sahifasi = public guruh posti 1:1 (matn + media).
2. Pastida 2 ta tugma: **📞 Aloqa** va **📋 To'liq ma'lumot**.
3. Ikkalasi ham maxfiy guruh a'zolari uchun ishlaydi. A'zo emas → "Siz premium obunachi emassiz" + premium URL.
4. **Aloqa** → admin belgilagan field qiymati (masalan `{nomer}` → "+998..") user botga DM.
5. **To'liq ma'lumot** → maxfiy guruh postining AYNAN nusxasi (media + to'liq matn) user botga DM.
6. Botda user uchun **«📦 Postlarim»** inline button → ads ro'yxati → har birining yonida **❌ O'chirish** tugmasi.
7. O'chirish bossa → admin belgilagan field (masalan `{nomer}`) admin belgilagan qiymatga almashadi (masalan `"❌ SOTILDI"`) — **public kanal posti**, **maxfiy guruh posti**, **webapp** — barchasida bir vaqtda.
8. WebApp grid — vertikal 2 ustun (mobil), responsiv.

---

## DB schema o'zgarishlar

### templates jadvali (yangi ustunlar):
- `contact_field_key TEXT` — qaysi filled_data key Aloqa'da DM bo'ladi (masalan `"nomer"`, `"phone"`).
- `sold_field_key TEXT` — Sotildi bo'lganda qaysi field almashtiriladi.
- `sold_replacement TEXT` — qaysi qiymatga almashtiriladi (masalan `"❌ SOTILDI"`).

### ads jadvali (yangi ustunlar):
- `private_posted_chat_id TEXT` — maxfiy guruh chat_id (nusxa).
- `private_posted_message_id INTEGER` — maxfiy guruh post ID (media bo'lsa — birinchi media ID, matnsiz `None`).
- `sold_at TEXT` — vaqt (ISO), null bo'lsa hali sotilmagan.

---

## Admin UI
`own:ch:<ch_id>` kanal kartasida yangi tugma: **🔘 Aloqa & Sotildi sozlash**
- Qadam 1: Aloqa field key (masalan `nomer`) — field ro'yxatidan tanlash.
- Qadam 2: Sotildi field key (default: aloqa bilan bir xil).
- Qadam 3: Sotildi qiymat (masalan `"❌ SOTILDI"`).

(button_label va private_text_template allaqachon sozlangan; alohida.)

---

## API endpointlar

### `POST /api/contact/{ad_id}`
Hozirgi: to'liq maxfiy post yuboradi.
**Yangi**: faqat `contact_field_key` qiymatini (masalan `"+998901234567"`) DM qiladi.
Response bir xil: `{ok, sent, message, premium_url}`.

### `POST /api/full-info/{ad_id}` (YANGI)
Maxfiy guruh postining aynan nusxasi (media + matn) DM qiladi — `private_posted_message_id` borligida `copyMessage` yoki fallback qilib `private_text_template`'dan qayta quriladi.
Membership check bir xil.

### `GET /api/my-ads?user_id=X` (YANGI)
User'ning approved ads ro'yxati (id, title, price, thumb, sold_at).

### `POST /api/ads/{ad_id}/sold` (YANGI)
Body: `{user_id, init_data}`. Owner tekshiriladi.
1. `filled_data[sold_field_key] = sold_replacement` → DB update.
2. Public kanal post → `editMessageCaption` (media) yoki `editMessageText`.
3. Maxfiy guruh post → xuddi shunday.
4. `sold_at = now()`.

---

## Bot handlers

### User uchun inline button "📦 Postlarim"
`/start` va `u:home` javobida yangi tugma qo'shish.
Callback: `u:myads` → user'ning approved ads ro'yxati (inline keyboard, har biriga `u:sold:<ad_id>` tugma).
`u:sold:<id>` → tasdiq so'raydi (`u:soldy:<id>`, `u:soldn:<id>`), "Ha" bosilganda — yuqoridagi `/api/ads/{id}/sold` logikasini aiogram'da takrorlash.

---

## WebApp frontend

### Detail sahifa:
```
[matn — public_text aynan]
[media]

[📞 Aloqa]  (primary)
[📋 To'liq ma'lumot]  (secondary)
```

### Grid:
`grid-template-columns: repeat(2, 1fr)` default (mobil).
- `@media (min-width: 600px)` → 3 ustun
- `@media (min-width: 900px)` → 4 ustun
- `@media (min-width: 1200px)` → 5 ustun
Har bir karta vertikal (rasm tepada, matn pastida) — allaqachon shunday.

### Postlarim sahifasi (WebApp'da ham qo'shiladi):
URL: `?page=my-ads` — header'da "📦 Postlarim" link (faqat initData'da user_id bor bo'lganda).
Ro'yxat (vertikal grid) — har karta'da "❌ O'chirish" tugmasi.

---

## Implementatsiya tartibi

1. ✅ DB ALTER TABLE (templates + ads).
2. ✅ database.py — get/set methodlari.
3. ✅ Admin handler (BtnConfig kengaytirish yoki yangi Flow).
4. ✅ moderation.py — maxfiy guruh post ID saqlash.
5. ✅ webapp/app.py — 4 yangi endpoint.
6. ✅ webapp/static/app.js — 2 tugma + Postlarim sahifa.
7. ✅ webapp/static/style.css — grid + tugmalar.
8. ✅ handlers/user.py — Postlarim + sold flow.
9. ✅ Test deploy, syntax check.
10. ✅ Prod deploy, restart.
11. ✅ Git commit.
