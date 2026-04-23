// Reklamabot Mini App — OLX style
const tg = window.Telegram?.WebApp;
try { tg?.ready(); tg?.expand(); } catch {}

const API = 'api';
const INIT_DATA = tg?.initData || '';

// ---------- State ----------
const state = {
  tab: 'home',
  view: 'home',       // home | ads | detail | favs | recent | searches
  category: null,     // {id, title}
  query: '',
  sort: 'new',
  location: '',
  priceMin: null,
  priceMax: null,
  page: 1,
  loading: false,
  hasMore: true,
  items: [],
  tokens: [],
  locations: [],
  rates: { usd_uzs: null, rub_uzs: null },
};

const els = {
  search: document.getElementById('searchInput'),
  searchClear: document.getElementById('searchClear'),
  searchHint: document.getElementById('searchHint'),
  filterBtn: document.getElementById('filterBtn'),
  chips: document.getElementById('chips'),
  sortBar: document.getElementById('sortBar'),
  trending: document.getElementById('trendingSection'),
  trendingList: document.getElementById('trendingList'),
  homeView: document.getElementById('homeView'),
  catGrid: document.getElementById('catGrid'),
  adsView: document.getElementById('adsView'),
  adsList: document.getElementById('adsList'),
  loadMore: document.getElementById('loadMore'),
  favsView: document.getElementById('favsView'),
  favsList: document.getElementById('favsList'),
  favsEmpty: document.getElementById('favsEmpty'),
  recentView: document.getElementById('recentView'),
  recentList: document.getElementById('recentList'),
  recentEmpty: document.getElementById('recentEmpty'),
  searchesView: document.getElementById('searchesView'),
  searchesList: document.getElementById('searchesList'),
  searchesEmpty: document.getElementById('searchesEmpty'),
  saveCurrentBtn: document.getElementById('saveCurrentBtn'),
  detailView: document.getElementById('detailView'),
  detailContent: document.getElementById('detailContent'),
  backBtn: document.getElementById('backBtn'),
  filterSheet: document.getElementById('filterSheet'),
  filterClose: document.getElementById('filterClose'),
  filterLocation: document.getElementById('filterLocation'),
  priceMin: document.getElementById('priceMin'),
  priceMax: document.getElementById('priceMax'),
  filterApply: document.getElementById('filterApply'),
  filterReset: document.getElementById('filterReset'),
};

// ---------- LocalStorage helpers ----------
const LS = {
  favs: () => {
    try { return JSON.parse(localStorage.getItem('favs') || '[]'); } catch { return []; }
  },
  setFavs: (v) => localStorage.setItem('favs', JSON.stringify(v)),
  isFav: (id) => LS.favs().includes(id),
  toggleFav: (id) => {
    const f = LS.favs();
    const i = f.indexOf(id);
    if (i >= 0) f.splice(i, 1); else f.unshift(id);
    LS.setFavs(f.slice(0, 200));
    return LS.isFav(id);
  },
  recent: () => {
    try { return JSON.parse(localStorage.getItem('recent') || '[]'); } catch { return []; }
  },
  pushRecent: (id) => {
    let r = LS.recent().filter(x => x !== id);
    r.unshift(id);
    localStorage.setItem('recent', JSON.stringify(r.slice(0, 30)));
  },
};

// ---------- Utils ----------
const fmt = (n) => {
  const num = parseInt(n);
  if (isNaN(num)) return n || '';
  return num.toLocaleString('uz-UZ').replace(/,/g, ' ');
};

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function highlight(text, tokens) {
  const safe = escapeHtml(text);
  if (!tokens || !tokens.length) return safe;
  const sorted = [...tokens].sort((a, b) => b.length - a.length);
  let result = safe;
  for (const t of sorted) {
    if (!t) continue;
    const pattern = t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    result = result.replace(new RegExp(pattern, 'gi'), m => `<mark>${m}</mark>`);
  }
  return result;
}

function timeAgo(iso) {
  if (!iso) return '';
  const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z');
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return 'hozirgina';
  if (s < 3600) return `${Math.floor(s/60)} daq oldin`;
  if (s < 86400) return `${Math.floor(s/3600)} soat oldin`;
  if (s < 604800) return `${Math.floor(s/86400)} kun oldin`;
  return d.toLocaleDateString('uz-UZ');
}

// ---------- API ----------
async function api(path, opts = {}) {
  const url = path.startsWith('http') ? path : `${API}${path.startsWith('/') ? path : '/' + path}`;
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ---------- Card renderer ----------
function cardHTML(ad) {
  const isFav = LS.isFav(ad.id);
  const title = highlight(ad.title || `E'lon #${ad.id}`, state.tokens);
  const price = ad.price ? `${fmt(ad.price)} so'm` : '—';
  const loc = ad.location ? `📍 ${escapeHtml(ad.location)}` : '';
  const views = ad.view_count ? `👁 ${ad.view_count}` : '';
  const thumb = ad.thumb_url
    ? `<img class="thumb" data-src="${escapeHtml(ad.thumb_url)}" alt="" loading="lazy">`
    : `<div class="thumb thumb-ph">📦</div>`;
  return `
    <article class="card" data-ad-id="${ad.id}">
      ${thumb}
      <div class="card-body">
        <div class="card-title">${title}</div>
        <div class="card-price">${escapeHtml(price)}</div>
        <div class="card-meta">
          <span>${loc}</span>
          <span class="muted">${timeAgo(ad.created_at)} ${views}</span>
        </div>
      </div>
      <button class="fav-btn ${isFav ? 'on' : ''}" data-fav="${ad.id}" aria-label="Sevimli">${isFav ? '❤️' : '🤍'}</button>
    </article>
  `;
}

function skeletonHTML(n = 6) {
  let s = '';
  for (let i = 0; i < n; i++) {
    s += `<div class="card skel"><div class="thumb shimmer"></div><div class="card-body"><div class="shimmer line w80"></div><div class="shimmer line w40"></div><div class="shimmer line w60"></div></div></div>`;
  }
  return s;
}

// ---------- IntersectionObserver ----------
let imgObserver;
function setupImgObserver() {
  if (imgObserver) imgObserver.disconnect();
  imgObserver = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) {
        const img = e.target;
        if (img.dataset.src) {
          img.src = img.dataset.src;
          img.removeAttribute('data-src');
        }
        imgObserver.unobserve(img);
      }
    }
  }, { rootMargin: '200px' });
  document.querySelectorAll('img[data-src]').forEach(i => imgObserver.observe(i));
}

let loadMoreObserver;
function setupLoadMoreObserver() {
  if (loadMoreObserver) loadMoreObserver.disconnect();
  const target = els.loadMore;
  if (!target) return;
  loadMoreObserver = new IntersectionObserver(async (entries) => {
    for (const e of entries) {
      if (e.isIntersecting && state.hasMore && !state.loading && state.view === 'ads') {
        await loadMoreAds();
      }
    }
  }, { rootMargin: '300px' });
  loadMoreObserver.observe(target);
}

// ---------- Views ----------
function showView(name) {
  state.view = name;
  for (const v of ['homeView','adsView','favsView','recentView','searchesView','detailView']) {
    const el = document.getElementById(v);
    if (el) el.classList.toggle('hidden', v !== name + 'View');
  }
  const showSort = (name === 'ads');
  const showTrend = (name === 'home');
  els.sortBar.classList.toggle('hidden', !showSort);
  els.trending.classList.toggle('hidden', !showTrend || !state.trendingLoaded);
  window.scrollTo({ top: 0, behavior: 'smooth' });

  // BackButton
  try {
    if (name === 'home') tg?.BackButton?.hide();
    else tg?.BackButton?.show();
  } catch {}
}

// ---------- Home: categories ----------
async function loadHome() {
  showView('home');
  els.catGrid.innerHTML = '<div class="loader">Yuklanmoqda…</div>';
  try {
    const [cats, trend] = await Promise.all([
      api('/categories'),
      api('/trending?limit=10').catch(() => ({ items: [] })),
    ]);
    renderCategories(cats.categories);
    renderTrending(trend.items);
  } catch (e) {
    els.catGrid.innerHTML = `<div class="error">Xatolik: ${e.message}</div>`;
  }
}

function renderCategories(cats) {
  if (!cats?.length) {
    els.catGrid.innerHTML = '<div class="empty">Kategoriyalar yo\'q</div>';
    return;
  }
  els.catGrid.innerHTML = cats.map(c => `
    <button class="cat-card" data-cat-id="${c.id}" data-cat-title="${escapeHtml(c.title)}">
      <div class="cat-icon">${c.icon || '🏷'}</div>
      <div class="cat-title">${escapeHtml(c.title)}</div>
      <div class="cat-count">${c.count} ta</div>
    </button>
  `).join('');
}

function renderTrending(items) {
  if (!items?.length) {
    els.trending.classList.add('hidden');
    state.trendingLoaded = false;
    return;
  }
  state.trendingLoaded = true;
  els.trendingList.innerHTML = items.map(ad => {
    const thumb = ad.thumb_url
      ? `<img class="mini-thumb" data-src="${escapeHtml(ad.thumb_url)}" alt="">`
      : `<div class="mini-thumb mini-ph">📦</div>`;
    return `<div class="mini-card" data-ad-id="${ad.id}">
      ${thumb}
      <div class="mini-title">${escapeHtml(ad.title || 'E\'lon')}</div>
      <div class="mini-price">${ad.price ? fmt(ad.price) + " so'm" : '—'}</div>
    </div>`;
  }).join('');
  els.trending.classList.remove('hidden');
  setupImgObserver();
}

// ---------- Ads list ----------
async function loadAds(reset = true) {
  showView('ads');
  if (reset) {
    state.page = 1;
    state.items = [];
    state.hasMore = true;
    els.adsList.innerHTML = skeletonHTML(6);
  }
  if (state.loading) return;
  state.loading = true;

  const params = new URLSearchParams();
  if (state.category?.id) params.set('category', state.category.id);
  if (state.query) params.set('q', state.query);
  if (state.sort) params.set('sort', state.sort);
  if (state.location) params.set('location', state.location);
  if (state.priceMin != null) params.set('price_min', state.priceMin);
  if (state.priceMax != null) params.set('price_max', state.priceMax);
  params.set('page', state.page);

  try {
    const r = await api('/ads?' + params.toString());
    state.tokens = r.tokens || [];
    state.hasMore = r.has_more;
    state.items = reset ? r.items : state.items.concat(r.items);
    renderAds(reset);
    renderSearchHint(r.total, r.query);
    renderChips();
    renderSaveCurrentBtn();
  } catch (e) {
    els.adsList.innerHTML = `<div class="error">Xatolik: ${e.message}</div>`;
  } finally {
    state.loading = false;
  }
}

async function loadMoreAds() {
  if (!state.hasMore || state.loading) return;
  state.page++;
  els.loadMore.classList.remove('hidden');
  els.loadMore.textContent = 'Yuklanmoqda…';
  await loadAds(false);
  els.loadMore.classList.toggle('hidden', !state.hasMore);
}

function renderAds(reset) {
  if (!state.items.length) {
    els.adsList.innerHTML = '<div class="empty">Bunday e\'lonlar topilmadi 🤷</div>';
    els.loadMore.classList.add('hidden');
    return;
  }
  els.adsList.innerHTML = state.items.map(cardHTML).join('');
  els.loadMore.classList.toggle('hidden', !state.hasMore);
  setupImgObserver();
  setupLoadMoreObserver();
}

function renderSearchHint(total, query) {
  if (!state.tokens.length && !state.category && !state.location && state.priceMin == null && state.priceMax == null) {
    els.searchHint.classList.add('hidden');
    return;
  }
  let parts = [`${total} ta natija`];
  if (query) parts.push(`"${escapeHtml(query)}" bo'yicha`);
  if (state.category) parts.push(`${escapeHtml(state.category.title)} ichida`);
  els.searchHint.innerHTML = parts.join(' ');
  els.searchHint.classList.remove('hidden');
}

function renderChips() {
  const chips = [];
  if (state.category) chips.push({ k: 'cat', label: `📂 ${state.category.title}` });
  if (state.location) chips.push({ k: 'loc', label: `📍 ${state.location}` });
  if (state.priceMin != null) chips.push({ k: 'pmin', label: `💰 dan ${fmt(state.priceMin)}` });
  if (state.priceMax != null) chips.push({ k: 'pmax', label: `💰 gacha ${fmt(state.priceMax)}` });
  if (!chips.length) { els.chips.classList.add('hidden'); els.chips.innerHTML = ''; return; }
  els.chips.classList.remove('hidden');
  els.chips.innerHTML = chips.map(c =>
    `<button class="chip" data-chip="${c.k}">${escapeHtml(c.label)} <span>✕</span></button>`
  ).join('');
}

function renderSaveCurrentBtn() {
  const show = state.view === 'searches' && (state.query || state.category || state.location || state.priceMin != null || state.priceMax != null);
  els.saveCurrentBtn.classList.toggle('hidden', !show);
}

// ---------- Detail ----------
async function loadDetail(id) {
  showView('detail');
  els.detailContent.innerHTML = '<div class="loader">Yuklanmoqda…</div>';
  try {
    const d = await api(`/ads/${id}`);
    api(`/ads/${id}/view`, { method: 'POST' }).catch(() => {});
    LS.pushRecent(id);
    renderDetail(d);
  } catch (e) {
    els.detailContent.innerHTML = `<div class="error">Xatolik: ${e.message}</div>`;
  }
}

function renderDetail(d) {
  const media = (d.media_list && d.media_list.length)
    ? d.media_list
    : (d.media_file_id ? [{ file_id: d.media_file_id, type: d.media_type }] : []);
  const slides = media.map(m => {
    const src = `api/thumb/${m.file_id || m}`;
    return `<div class="slide"><img data-src="${src}" alt=""></div>`;
  }).join('');

  const isFav = LS.isFav(d.id);
  const title = highlight(d.data.title || d.data.nomi || `E'lon #${d.id}`, state.tokens);
  const price = d.data.price || d.data.narx || d.data.narxi || '';
  const description = d.data.description || d.data.tavsif || d.data.izoh || '';
  const priceNum = parsePrice(price);
  const priceAlt = priceNum && state.rates.usd_uzs
    ? `<div class="price-alt muted">≈ $${(priceNum / state.rates.usd_uzs).toFixed(2)}${state.rates.rub_uzs ? ' · ' + Math.round(priceNum / state.rates.rub_uzs) + ' ₽' : ''}</div>`
    : '';

  const bc = (d.breadcrumb || []).map(b => escapeHtml(b.title)).join(' › ');
  const fields = Object.entries(d.data)
    .filter(([k]) => !['title','nomi','price','narx','narxi','description','tavsif','izoh'].includes(k))
    .map(([k,v]) => `<div class="field-row"><span class="k">${escapeHtml(k)}</span><span class="v">${highlight(String(v), state.tokens)}</span></div>`)
    .join('');

  // REJA9: seller/owner info HIDDEN from public view — only visible to
  // private-group members via /api/contact response (private_text_template)
  // REJA10: Aloqa + To'liq ma'lumot — ikkalasi ham premium-gated
  const btnLabel = escapeHtml(d.button_label || "📞 Aloqa");
  const contactBtn = `<button class="primary-btn contact-btn" id="detailContactBtn" data-ad-id="${d.id}">${btnLabel}</button>`;
  const fullInfoBtn = d.has_full_info
    ? `<button class="primary-btn fullinfo-btn" id="detailFullInfoBtn" data-ad-id="${d.id}">📄 To'liq ma'lumot</button>`
    : '';
  // REJA10 fix: SOTILDI badge'ni public/card'dan olib tashlaymiz (faqat maxfiy
  // guruh a'zolari Aloqa/To'liq ma'lumot bosgach asl post'da SOTILDI ko'radi)
  const soldBadge = '';

  // Public post matni admin template asosida (kanalga chiqqan post bilan
  // aynan bir xil). Agar public_text bor bo'lsa — sarlavha/narx/maydonlarni
  // qaytadan chiqarmaymiz, bo'lmasa fallback description+fields.
  const hasPublicText = !!d.public_text;
  const headHtml = hasPublicText
    ? `<div class="detail-head">
         <div class="bc muted">${bc}</div>
         <div class="detail-meta muted">
           <span>🕘 ${timeAgo(d.created_at)}</span>
           <span>👁 ${d.view_count}</span>
         </div>
       </div>`
    : `<div class="detail-head">
         <div class="bc muted">${bc}</div>
         <h2>${title}</h2>
         <div class="detail-price">${price ? fmt(price) + " so'm" : '—'}</div>
         ${priceAlt}
         <div class="detail-meta muted">
           <span>🕘 ${timeAgo(d.created_at)}</span>
           <span>👁 ${d.view_count}</span>
         </div>
       </div>`;

  const publicBlock = hasPublicText
    ? `<div class="detail-public-text">${escapeHtml(d.public_text).replace(/\n/g,'<br>')}</div>`
    : `${description ? `<div class="detail-desc">${highlight(description, state.tokens)}</div>` : ''}
       ${fields ? `<div class="detail-fields">${fields}</div>` : ''}`;

  els.detailContent.innerHTML = `
    ${soldBadge}
    ${headHtml}
    ${slides ? `<div class="slider">${slides}</div>` : ''}
    ${publicBlock}
    <div class="detail-actions">
      <div class="detail-cta-row">
        ${contactBtn}
        ${fullInfoBtn}
      </div>
      <div id="contactResult" class="contact-result"></div>
      <button class="secondary-btn" id="detailFavBtn" data-ad-id="${d.id}">${isFav ? '❤️ Saqlangan' : '🤍 Saqlash'}</button>
      <button class="secondary-btn" id="detailShareBtn" data-ad-id="${d.id}">🔗 Ulashish</button>
      ${d.channel_url ? `<a class="secondary-btn" href="${escapeHtml(d.channel_url)}" target="_blank">📢 Kanalda ochish</a>` : ''}
    </div>
  `;
  setupImgObserver();
  // REJA9/10: wire up buttons
  const cbtn = document.getElementById('detailContactBtn');
  if (cbtn) cbtn.addEventListener('click', () => handleContact(d.id));
  const fbtn = document.getElementById('detailFullInfoBtn');
  if (fbtn) fbtn.addEventListener('click', () => handleFullInfo(d.id));
}

// REJA9: premium-gated contact
async function handleContact(adId) {
  const resultEl = document.getElementById('contactResult');
  const btn = document.getElementById('detailContactBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Tekshirilmoqda…'; }
  if (resultEl) resultEl.innerHTML = '';
  try {
    const tg = window.Telegram?.WebApp;
    const initData = tg?.initData || '';
    const userId = tg?.initDataUnsafe?.user?.id || null;
    const res = await fetch(`${API}/contact/${adId}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({init_data: initData, user_id: userId}),
    });
    const data = await res.json();
    if (data.ok && data.sent) {
      if (btn) { btn.textContent = '✅ Telegram botga yuborildi'; btn.classList.add('ok'); }
      if (resultEl) resultEl.innerHTML = `<div class="contact-ok">📩 Tafsilotlar shaxsiy xabarda yuborildi. Botga o'ting.</div>`;
    } else if (data.ok && !data.sent) {
      if (btn) { btn.disabled = false; btn.textContent = '📞 Aloqa'; }
      if (resultEl) resultEl.innerHTML = `<div class="contact-warn">❌ Siz premium obunachi emassiz</div>`;
    } else {
      // Not a member or send failed → show premium CTA
      const purl = data.premium_url || '';
      if (btn) {
        btn.disabled = false;
        btn.textContent = '📞 Aloqa';
      }
      if (resultEl) {
        const warnMsg = escapeHtml(data.message || "Siz premium obunachi emassiz");
        if (purl) {
          resultEl.innerHTML = `
            <div class="contact-warn">❌ ${warnMsg}. Maxfiy guruhga a'zo bo'lishingiz kerak.</div>
            <a class="primary-btn premium-btn" href="${escapeHtml(purl)}" target="_blank">💎 Premium oling</a>`;
        } else {
          resultEl.innerHTML = `<div class="contact-warn">❌ ${warnMsg}</div>`;
        }
      }
    }
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = '📞 Aloqa'; }
    if (resultEl) resultEl.innerHTML = `<div class="contact-warn">Xatolik: ${escapeHtml(String(e))}</div>`;
  }
}

function parsePrice(s) {
  if (s == null) return null;
  const m = String(s).match(/(\d[\d\s.,]*)/);
  if (!m) return null;
  const n = parseInt(m[1].replace(/[\s.,]/g, ''));
  return isNaN(n) ? null : n;
}

// REJA10: To'liq ma'lumot (maxfiy guruh postini DM orqali yuborish)
async function handleFullInfo(adId) {
  const resultEl = document.getElementById('contactResult');
  const btn = document.getElementById('detailFullInfoBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Tekshirilmoqda…'; }
  if (resultEl) resultEl.innerHTML = '';
  try {
    const tg = window.Telegram?.WebApp;
    const initData = tg?.initData || '';
    const userId = tg?.initDataUnsafe?.user?.id || null;
    const res = await fetch(`${API}/full-info/${adId}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({init_data: initData, user_id: userId}),
    });
    const data = await res.json();
    if (data.ok && data.sent) {
      if (btn) { btn.textContent = "✅ To'liq ma'lumot yuborildi"; btn.classList.add('ok'); }
      if (resultEl) resultEl.innerHTML = `<div class="contact-ok">📩 To'liq post shaxsiy xabarda yuborildi. Botga o'ting.</div>`;
    } else {
      const purl = data.premium_url || '';
      if (btn) { btn.disabled = false; btn.textContent = "📄 To'liq ma'lumot"; }
      if (resultEl) {
        const warnMsg = escapeHtml(data.message || "Siz premium obunachi emassiz");
        if (purl) {
          resultEl.innerHTML = `
            <div class="contact-warn">❌ ${warnMsg}. Maxfiy guruhga a'zo bo'lishingiz kerak.</div>
            <a class="primary-btn premium-btn" href="${escapeHtml(purl)}" target="_blank">💎 Premium oling</a>`;
        } else {
          resultEl.innerHTML = `<div class="contact-warn">❌ ${warnMsg}</div>`;
        }
      }
    }
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "📄 To'liq ma'lumot"; }
    if (resultEl) resultEl.innerHTML = `<div class="contact-warn">Xatolik: ${escapeHtml(String(e))}</div>`;
  }
}

// ---------- Seller profile ----------
async function loadSeller(userId) {
  showView('detail');
  els.detailContent.innerHTML = '<div class="loader">Yuklanmoqda…</div>';
  try {
    const s = await api(`/sellers/${userId}`);
    const uname = s.username ? `@${escapeHtml(s.username)}` : `ID ${s.user_id}`;
    const since = s.first_ad_at ? timeAgo(s.first_ad_at) : '—';
    const items = s.items.map(cardHTML).join('');
    els.detailContent.innerHTML = `
      <div class="detail-head">
        <h2>👤 ${uname}</h2>
        <div class="muted">
          📢 ${s.total_ads} e'lon · 👁 ${s.total_views} ko'rish · Birinchi e'lon: ${since}
        </div>
      </div>
      ${items ? `<div class="ads-list">${items}</div>` : '<div class="empty">E\'lonlar yo\'q</div>'}
    `;
    setupImgObserver();
  } catch (e) {
    els.detailContent.innerHTML = `<div class="error">Xatolik: ${e.message}</div>`;
  }
}

// ---------- Favorites view ----------
async function loadFavs() {
  showView('favs');
  const ids = LS.favs();
  if (!ids.length) {
    els.favsList.innerHTML = '';
    els.favsEmpty.classList.remove('hidden');
    return;
  }
  els.favsEmpty.classList.add('hidden');
  els.favsList.innerHTML = skeletonHTML(Math.min(ids.length, 4));
  const items = [];
  for (const id of ids) {
    try {
      const d = await api(`/ads/${id}`);
      items.push({
        id: d.id,
        title: d.data.title || d.data.nomi || `E'lon #${d.id}`,
        price: d.data.price || d.data.narx || d.data.narxi || '',
        location: d.data.location || d.data.manzil || '',
        created_at: d.created_at,
        view_count: d.view_count,
        thumb_url: d.media_file_id ? `api/thumb/${d.media_file_id}` : null,
      });
    } catch {}
  }
  state.tokens = [];
  if (!items.length) {
    els.favsList.innerHTML = '<div class="empty">Saqlanganlar topilmadi.</div>';
    return;
  }
  els.favsList.innerHTML = items.map(cardHTML).join('');
  setupImgObserver();
}

// ---------- Recently viewed ----------
async function loadRecent() {
  showView('recent');
  const ids = LS.recent();
  if (!ids.length) {
    els.recentList.innerHTML = '';
    els.recentEmpty.classList.remove('hidden');
    return;
  }
  els.recentEmpty.classList.add('hidden');
  els.recentList.innerHTML = skeletonHTML(Math.min(ids.length, 4));
  const items = [];
  for (const id of ids) {
    try {
      const d = await api(`/ads/${id}`);
      items.push({
        id: d.id,
        title: d.data.title || d.data.nomi || `E'lon #${d.id}`,
        price: d.data.price || d.data.narx || d.data.narxi || '',
        location: d.data.location || d.data.manzil || '',
        created_at: d.created_at,
        view_count: d.view_count,
        thumb_url: d.media_file_id ? `api/thumb/${d.media_file_id}` : null,
      });
    } catch {}
  }
  state.tokens = [];
  if (!items.length) {
    els.recentList.innerHTML = '<div class="empty">Topilmadi.</div>';
    return;
  }
  els.recentList.innerHTML = items.map(cardHTML).join('');
  setupImgObserver();
}

// ---------- Saved searches ----------
async function loadSearches() {
  showView('searches');
  renderSaveCurrentBtn();
  els.searchesList.innerHTML = '<div class="loader">Yuklanmoqda…</div>';
  try {
    const r = await api(`/saved_searches?init_data=${encodeURIComponent(INIT_DATA)}`);
    if (!r.items.length) {
      els.searchesList.innerHTML = '';
      els.searchesEmpty.classList.remove('hidden');
      return;
    }
    els.searchesEmpty.classList.add('hidden');
    els.searchesList.innerHTML = r.items.map(s => `
      <div class="saved-row">
        <div>
          <div class="saved-title">${escapeHtml(s.query || '—')}</div>
          <div class="muted">
            ${s.location ? '📍 ' + escapeHtml(s.location) : ''}
            ${s.price_min != null ? ' 💰' + fmt(s.price_min) + '+' : ''}
            ${s.price_max != null ? ' —' + fmt(s.price_max) : ''}
          </div>
        </div>
        <button class="icon-btn" data-del-search="${s.id}">🗑</button>
      </div>
    `).join('');
  } catch (e) {
    els.searchesList.innerHTML = `<div class="error">${e.message}. Bot orqali ochishingiz kerak.</div>`;
  }
}

async function saveCurrentSearch() {
  const body = {
    init_data: INIT_DATA,
    query: state.query,
    category_id: state.category?.id || null,
    location: state.location || null,
    price_min: state.priceMin,
    price_max: state.priceMax,
  };
  try {
    await api('/saved_searches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    tg?.showAlert?.('✅ Qidiruv saqlandi. Yangi e\'lonlarda xabar beramiz.');
    loadSearches();
  } catch (e) {
    tg?.showAlert?.('Xatolik: ' + e.message);
  }
}

// ---------- Filter sheet ----------
async function openFilter() {
  if (!state.locations.length) {
    try {
      const r = await api('/locations');
      state.locations = r.locations;
      els.filterLocation.innerHTML = '<option value="">Barchasi</option>' +
        state.locations.map(l => `<option value="${escapeHtml(l.name)}">${escapeHtml(l.name)} (${l.count})</option>`).join('');
    } catch {}
  }
  els.filterLocation.value = state.location || '';
  els.priceMin.value = state.priceMin ?? '';
  els.priceMax.value = state.priceMax ?? '';
  els.filterSheet.classList.remove('hidden');
}

function closeFilter() {
  els.filterSheet.classList.add('hidden');
}

function applyFilter() {
  state.location = els.filterLocation.value || '';
  const pmin = parseInt(els.priceMin.value);
  const pmax = parseInt(els.priceMax.value);
  state.priceMin = isNaN(pmin) ? null : pmin;
  state.priceMax = isNaN(pmax) ? null : pmax;
  closeFilter();
  loadAds();
}

function resetFilter() {
  state.location = '';
  state.priceMin = null;
  state.priceMax = null;
  els.filterLocation.value = '';
  els.priceMin.value = '';
  els.priceMax.value = '';
}

// ---------- Event bindings ----------
document.addEventListener('click', async (e) => {
  const catBtn = e.target.closest('[data-cat-id]');
  if (catBtn) {
    state.category = { id: parseInt(catBtn.dataset.catId), title: catBtn.dataset.catTitle };
    state.page = 1;
    loadAds();
    return;
  }
  const sellerBtn2 = e.target.closest('[data-seller]');
  if (sellerBtn2) {
    e.stopPropagation();
    loadSeller(parseInt(sellerBtn2.dataset.seller));
    return;
  }
  const favBtn = e.target.closest('[data-fav]');
  if (favBtn) {
    e.stopPropagation();
    const id = parseInt(favBtn.dataset.fav);
    const on = LS.toggleFav(id);
    favBtn.classList.toggle('on', on);
    favBtn.textContent = on ? '❤️' : '🤍';
    return;
  }
  const card = e.target.closest('[data-ad-id]');
  if (card) {
    loadDetail(parseInt(card.dataset.adId));
    return;
  }
  const tab = e.target.closest('.tab');
  if (tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    state.tab = tab.dataset.tab;
    if (state.tab === 'home') { state.category = null; state.query = ''; els.search.value = ''; els.searchClear.classList.add('hidden'); loadHome(); }
    else if (state.tab === 'favs') loadFavs();
    else if (state.tab === 'recent') loadRecent();
    else if (state.tab === 'searches') loadSearches();
    return;
  }
  const sortBtn = e.target.closest('.sort-btn');
  if (sortBtn) {
    document.querySelectorAll('.sort-btn').forEach(b => b.classList.remove('active'));
    sortBtn.classList.add('active');
    state.sort = sortBtn.dataset.sort;
    loadAds();
    return;
  }
  const chip = e.target.closest('[data-chip]');
  if (chip) {
    const k = chip.dataset.chip;
    if (k === 'cat') state.category = null;
    if (k === 'loc') state.location = '';
    if (k === 'pmin') state.priceMin = null;
    if (k === 'pmax') state.priceMax = null;
    loadAds();
    return;
  }
  const delSearch = e.target.closest('[data-del-search]');
  if (delSearch) {
    const id = delSearch.dataset.delSearch;
    try {
      await api(`/saved_searches/${id}?init_data=${encodeURIComponent(INIT_DATA)}`, { method: 'DELETE' });
      loadSearches();
    } catch (e) { tg?.showAlert?.(e.message); }
    return;
  }
  if (e.target.id === 'detailFavBtn') {
    const id = parseInt(e.target.dataset.adId);
    const on = LS.toggleFav(id);
    e.target.textContent = on ? '❤️ Saqlangan' : '🤍 Saqlash';
    return;
  }
  if (e.target.id === 'detailShareBtn') {
    const id = parseInt(e.target.dataset.adId);
    const url = `${location.origin}${location.pathname}#ad=${id}`;
    const text = `E'lon #${id}`;
    try {
      tg?.openTelegramLink?.(`https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`);
    } catch {
      navigator.clipboard?.writeText(url);
      tg?.showAlert?.('Havola nusxa olindi');
    }
    return;
  }
});

els.search.addEventListener('input', debounce(() => {
  state.query = els.search.value.trim();
  els.searchClear.classList.toggle('hidden', !state.query);
  if (state.query || state.category) loadAds();
  else loadHome();
}, 400));

els.searchClear.addEventListener('click', () => {
  els.search.value = '';
  state.query = '';
  els.searchClear.classList.add('hidden');
  els.searchHint.classList.add('hidden');
  if (state.category) loadAds();
  else loadHome();
});

els.filterBtn.addEventListener('click', openFilter);
els.filterClose.addEventListener('click', closeFilter);
els.filterApply.addEventListener('click', applyFilter);
els.filterReset.addEventListener('click', () => { resetFilter(); loadAds(); closeFilter(); });
document.querySelector('.sheet-backdrop')?.addEventListener('click', closeFilter);

els.backBtn.addEventListener('click', () => {
  if (state.category || state.query) loadAds(); else loadHome();
});

els.saveCurrentBtn.addEventListener('click', saveCurrentSearch);

// Telegram BackButton
try {
  tg?.BackButton?.onClick(() => {
    if (state.view === 'detail') {
      if (state.category || state.query) loadAds(); else loadHome();
    } else {
      loadHome();
    }
  });
} catch {}

function debounce(fn, wait) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), wait); };
}

// ---------- Deep link (hash #ad=123) ----------
(function initHash() {
  const m = /#ad=(\d+)/.exec(location.hash);
  if (m) { loadDetail(parseInt(m[1])); return; }
})();

// ---------- Start ----------
loadHome();
// Load currency rates in background (best-effort)
api('/rates').then(r => { state.rates.usd_uzs = r.usd_uzs; state.rates.rub_uzs = r.rub_uzs; }).catch(() => {});
