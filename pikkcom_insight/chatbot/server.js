const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const url = require('url');

// --- load .env (no dotenv package needed) ---
// Reads KEY=VALUE lines from a .env file next to server.js and puts them
// into process.env, without overwriting anything already set.
function loadEnv() {
  const envPath = path.join(__dirname, '.env');
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, 'utf8').split('\n');
  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) return;
    const idx = trimmed.indexOf('=');
    if (idx === -1) return;
    const key = trimmed.slice(0, idx).trim();
    let value = trimmed.slice(idx + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  });
}
loadEnv();

const USERS_FILE = path.join(__dirname, 'users.json');
const PUBLIC_DIR = path.join(__dirname, 'public');
const PORT = process.env.PORT || 3000;
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-flash-latest';
const RETAIL_DB_PATH = path.resolve(__dirname, process.env.RETAIL_DB_PATH || 'retail.db');

// Pages that require a signed-in session. Anyone hitting these without a
// valid session cookie gets bounced back to the sign-in page.
const PROTECTED_PATHS = new Set(['/ui.html', '/report.html']);

// In-memory session store: token -> username. Resets when the server
// restarts — fine for now, swap for Redis/a DB-backed store for production.
const sessions = new Map();

function createSession(username) {
  const token = crypto.randomBytes(24).toString('hex');
  sessions.set(token, { username, createdAt: Date.now() });
  return token;
}

function getSession(req) {
  const cookies = parseCookies(req.headers.cookie);
  const token = cookies.session;
  if (!token) return null;
  return sessions.has(token) ? { token, ...sessions.get(token) } : null;
}

function parseCookies(header) {
  const out = {};
  if (!header) return out;
  header.split(';').forEach((pair) => {
    const idx = pair.indexOf('=');
    if (idx === -1) return;
    const key = pair.slice(0, idx).trim();
    const val = decodeURIComponent(pair.slice(idx + 1).trim());
    out[key] = val;
  });
  return out;
}

// --- user storage (a simple JSON file; swap for a real DB later) ---

function loadUsers() {
  if (!fs.existsSync(USERS_FILE)) return {};
  return JSON.parse(fs.readFileSync(USERS_FILE, 'utf8'));
}

function saveUsers(users) {
  fs.writeFileSync(USERS_FILE, JSON.stringify(users, null, 2));
}

function hashPassword(password, salt) {
  return crypto.scryptSync(password, salt, 64).toString('hex');
}

// --- small helpers ---

function sendJSON(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1e6) req.destroy(); // basic guard against huge payloads
    });
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });
}

function serveStatic(req, res) {
  const parsed = url.parse(req.url);
  let filePath = parsed.pathname === '/' ? '/index.html' : parsed.pathname;
  filePath = path.normalize(filePath).replace(/^(\.\.[/\\])+/, ''); // no path traversal

  if (PROTECTED_PATHS.has(filePath) && !getSession(req)) {
    res.writeHead(302, { Location: '/' });
    res.end();
    return;
  }

  const fullPath = path.join(PUBLIC_DIR, filePath);

  const ext = path.extname(fullPath);
  const types = {
    '.html': 'text/html',
    '.css': 'text/css',
    '.js': 'application/javascript',
  };

  fs.readFile(fullPath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('Not found');
      return;
    }
    res.writeHead(200, { 'Content-Type': types[ext] || 'application/octet-stream' });
    res.end(data);
  });
}

// --- retail data (read-only SQLite, via Node's built-in node:sqlite) ---

const { DatabaseSync } = require('node:sqlite');

function openDb() {
  // readOnly means SQLite itself rejects any write, even if validation missed one.
  return new DatabaseSync(RETAIL_DB_PATH, { readOnly: true });
}

// Read the schema and the filter values straight from the database so the
// prompt and the report tool always match what's actually in retail.db.
function loadDbInfo() {
  const db = openDb();
  try {
    const schema = db
      .prepare("SELECT sql FROM sqlite_master WHERE type IN ('table', 'view') AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")
      .all()
      .map((r) => r.sql)
      .join(';\n');
    const distinct = (sql) => db.prepare(sql).all().map((r) => Object.values(r)[0]);
    const range = db.prepare('SELECT MIN(sale_date) AS first, MAX(sale_date) AS last FROM sales').get();
    return {
      schema,
      firstSale: range.first,
      lastSale: range.last,
      values: {
        category: distinct('SELECT DISTINCT category FROM products ORDER BY 1'),
        gender: distinct('SELECT DISTINCT gender FROM products ORDER BY 1'),
        style: distinct('SELECT DISTINCT style FROM products ORDER BY 1'),
        store: distinct('SELECT store_name FROM stores ORDER BY 1'),
        city: distinct('SELECT DISTINCT city FROM stores ORDER BY 1'),
        region: distinct('SELECT DISTINCT region FROM stores ORDER BY 1'),
      },
    };
  } finally {
    db.close();
  }
}
const DB_INFO = loadDbInfo();

const FORBIDDEN_SQL = /\b(insert|update|delete|drop|alter|create|truncate|pragma|attach|detach|replace|vacuum)\b/i;
const MAX_ROWS = 200;

function runReadOnlyQuery(sql) {
  const cleaned = String(sql || '').trim().replace(/;\s*$/, '');
  if (!/^(select|with)\b/i.test(cleaned)) throw new Error('only SELECT queries are allowed');
  if (cleaned.includes(';')) throw new Error('only one statement is allowed');
  if (FORBIDDEN_SQL.test(cleaned)) throw new Error('query contains a forbidden keyword');

  const db = openDb();
  try {
    const rows = db.prepare(cleaned).all().map((r) => ({ ...r }));
    return { rowCount: rows.length, rows: rows.slice(0, MAX_ROWS), truncated: rows.length > MAX_ROWS };
  } finally {
    db.close();
  }
}

// --- graphical reports ---
// A report is fully described by its filters, which live in the link's query
// string (/report.html?category=Saree&from=...), so links are shareable and
// the report page just asks /api/report for the same filters.

const REPORT_FILTERS = ['category', 'gender', 'style', 'store', 'city', 'region', 'from', 'to'];
const DATE_RE = /^\d{4}-\d{2}(-\d{2})?$/;

function normalizeFilters(input) {
  const f = {};
  for (const key of REPORT_FILTERS) {
    const raw = input?.[key];
    if (typeof raw !== 'string' || !raw.trim()) continue;
    const val = raw.trim();
    if (key === 'from' || key === 'to') {
      if (!DATE_RE.test(val)) continue;
      // Month-only dates cover the whole month; string comparison makes -31 safe.
      f[key] = val.length === 7 ? val + (key === 'from' ? '-01' : '-31') : val;
    } else {
      const match = DB_INFO.values[key].find((v) => v.toLowerCase() === val.toLowerCase());
      if (match) f[key] = match;
    }
  }
  return f;
}

// Builds "WHERE ..." for queries that join products p and stores st, with the
// given column used for the date range.
function filterWhere(f, dateCol) {
  const clauses = [];
  const params = [];
  const add = (sql, val) => { clauses.push(sql); params.push(val); };
  if (f.category) add('p.category = ?', f.category);
  if (f.gender) add('p.gender = ?', f.gender);
  if (f.style) add('p.style = ?', f.style);
  if (f.store) add('st.store_name = ?', f.store);
  if (f.city) add('st.city = ?', f.city);
  if (f.region) add('st.region = ?', f.region);
  if (f.from) add(`${dateCol} >= ?`, f.from);
  if (f.to) add(`${dateCol} <= ?`, f.to);
  return { where: clauses.length ? 'WHERE ' + clauses.join(' AND ') : '', params };
}

function pluralize(word) {
  const w = word.toLowerCase();
  return /(s|sh|ch|x)$/.test(w) ? w + 'es' : w + 's';
}

// Mirror sessions that touched a product in the selection, joined to the
// shopper (age group) and whether the session ended in a bill.
const MIRROR_FROM = `FROM session_events e
  JOIN products p ON p.product_id = e.product_id
  JOIN mirror_sessions ms ON ms.session_id = e.session_id
  JOIN stores st ON st.store_id = ms.store_id`;
const MIRROR_DATE = 'SUBSTR(ms.started_at, 1, 10)';
const AGE_ORDER = ['18-24', '25-34', '35-44', '45-54', '55+', 'anonymous'];
const byAge = (a, b) => AGE_ORDER.indexOf(a.age) - AGE_ORDER.indexOf(b.age);

function mirrorByAge(all, f) {
  const w = filterWhere(f, MIRROR_DATE);
  return all(
    `SELECT COALESCE(c.age_group, 'anonymous') AS age,
            COUNT(DISTINCT ms.session_id) AS sessions,
            COUNT(DISTINCT b.session_id) AS converted
     ${MIRROR_FROM}
     LEFT JOIN customers c ON c.customer_id = ms.customer_id
     LEFT JOIN bills b ON b.session_id = ms.session_id
     ${w.where} GROUP BY 1`,
    w.params
  ).sort(byAge);
}

// Which saree types each age group tries on the mirror. "Type" is the saree
// family from the product name (Kanjivaram Silk, Kasavu, Linen...).
function sareesByAge(all, f) {
  if (f.category && f.category !== 'Saree') return null;
  if ((f.style && f.style !== 'Traditional') || f.gender === 'Men') return null;
  const w = filterWhere({ ...f, category: 'Saree' }, MIRROR_DATE);
  const rows = all(
    `SELECT c.age_group AS age,
            SUBSTR(p.product_name, 1, INSTR(p.product_name, ' Saree') - 1) AS type,
            COUNT(*) AS tries
     ${MIRROR_FROM}
     JOIN customers c ON c.customer_id = ms.customer_id
     ${w.where} ${w.where ? 'AND' : 'WHERE'} e.event_type = 'tried'
     GROUP BY 1, 2`,
    w.params
  );
  const types = [...new Set(rows.map((r) => r.type))];
  const totals = {};
  rows.forEach((r) => { totals[r.type] = (totals[r.type] || 0) + r.tries; });
  types.sort((a, b) => totals[b] - totals[a]);
  const ages = [...new Set(rows.map((r) => r.age))].map((age) => ({ age })).sort(byAge);
  return {
    types,
    rows: ages.map(({ age }) => {
      const mine = rows.filter((r) => r.age === age);
      const total = mine.reduce((a, r) => a + r.tries, 0);
      return { age, total, split: types.map((t) => mine.find((r) => r.type === t)?.tries || 0) };
    }),
  };
}

// Western tops and bottoms, shown whenever the selection can include them.
function westernWear(all, f) {
  if (f.category && !['Top', 'Bottom'].includes(f.category)) return null;
  if (f.style && f.style !== 'Western') return null;
  const w = filterWhere({ ...f, style: 'Western' }, 's.sale_date');
  const rows = all(
    `SELECT p.category AS category, p.product_name AS label, p.gender AS gender,
            SUM(s.quantity) AS units, SUM(s.amount) AS revenue
     FROM sales s JOIN products p ON p.product_id = s.product_id JOIN stores st ON st.store_id = s.store_id
     ${w.where} ${w.where ? 'AND' : 'WHERE'} p.category IN ('Top', 'Bottom')
     GROUP BY 1, 2, 3 ORDER BY revenue DESC`,
    w.params
  );
  return { tops: rows.filter((r) => r.category === 'Top'), bottoms: rows.filter((r) => r.category === 'Bottom') };
}

function addMonths(ym, n) {
  const [y, m] = ym.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + n, 1));
  return d.toISOString().slice(0, 7);
}

// Next-12-month forecast from the full history of the selection (the date
// filter is ignored so there is always enough history). Each month is last
// year's same month scaled by the year-on-year growth; with less than two
// years of data it falls back to seasonal-naive, then to a flat average.
function forecast(monthly, lastSale) {
  if (!monthly.length) return null;
  const series = monthly.map((r) => ({ ...r }));
  // The latest month is usually partial: scale it up to a full month.
  const last = series[series.length - 1];
  if (lastSale.startsWith(last.month)) {
    const day = Number(lastSale.slice(8, 10));
    const [y, m] = last.month.split('-').map(Number);
    const days = new Date(Date.UTC(y, m, 0)).getUTCDate();
    if (day < days) {
      last.revenue *= days / day;
      last.units *= days / day;
    }
  }
  const n = series.length;
  const sum = (rows, k) => rows.reduce((a, r) => a + r[k], 0);
  let growth = 1;
  let method = 'seasonal';
  let base;
  if (n >= 24) {
    growth = sum(series.slice(-12), 'revenue') / (sum(series.slice(-24, -12), 'revenue') || 1);
    growth = Math.min(Math.max(growth, 0.5), 2);
    base = series.slice(-12);
  } else if (n >= 12) {
    base = series.slice(-12);
  } else {
    method = 'average';
    const recent = series.slice(-3);
    const avg = { revenue: sum(recent, 'revenue') / recent.length, units: sum(recent, 'units') / recent.length };
    base = Array.from({ length: 12 }, () => avg);
  }
  const lastMonth = series[n - 1].month;
  const next = base.map((r, i) => ({
    month: addMonths(lastMonth, i + 1),
    revenue: r.revenue * growth,
    units: Math.round(r.units * growth),
  }));
  return {
    method,
    growth,
    history: monthly.slice(-12),
    next,
    nextRevenue: sum(next, 'revenue'),
    nextUnits: sum(next, 'units'),
    lastYearRevenue: sum(series.slice(-12), 'revenue'),
  };
}

// Last 365 days vs the 365 before, per product, ending at the latest sale.
function productTrends(all, f, lastSale) {
  const w = filterWhere({ ...f, from: undefined, to: undefined }, 's.sale_date');
  return all(
    `SELECT p.product_name AS label, p.category AS category,
            SUM(CASE WHEN s.sale_date > DATE(?, '-1 year') THEN s.amount ELSE 0 END) AS cur,
            SUM(CASE WHEN s.sale_date <= DATE(?, '-1 year') AND s.sale_date > DATE(?, '-2 years') THEN s.amount ELSE 0 END) AS prev
     FROM sales s JOIN products p ON p.product_id = s.product_id JOIN stores st ON st.store_id = s.store_id
     ${w.where} GROUP BY 1, 2`,
    [lastSale, lastSale, lastSale, ...w.params]
  )
    .filter((r) => r.prev > 0)
    .map((r) => ({ ...r, growth: (r.cur - r.prev) / r.prev }))
    .sort((a, b) => b.growth - a.growth);
}

function median(nums) {
  const s = [...nums].sort((a, b) => a - b);
  if (!s.length) return 0;
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

// Products that lag on several signals: revenue below their category's
// median, falling year-on-year, tried on the mirror but rarely picked, or
// sitting on far more stock than they sell.
function underperformers(all, f, trends, lastSale) {
  const sales = filterWhere(f, 's.sale_date');
  const products = all(
    `SELECT p.product_id AS id, p.product_name AS label, p.category AS category,
            SUM(s.quantity) AS units, SUM(s.amount) AS revenue,
            SUM(CASE WHEN s.sale_date > DATE(?, '-90 days') THEN s.quantity ELSE 0 END) AS units90
     FROM sales s JOIN products p ON p.product_id = s.product_id JOIN stores st ON st.store_id = s.store_id
     ${sales.where} GROUP BY 1, 2, 3`,
    [lastSale, ...sales.params]
  );
  if (products.length < 3) return [];

  const mirror = filterWhere(f, MIRROR_DATE);
  const conv = {};
  all(
    `SELECT e.product_id AS id, SUM(e.event_type = 'tried') AS tried, SUM(e.event_type = 'selected') AS selected
     ${MIRROR_FROM} ${mirror.where} GROUP BY 1`,
    mirror.params
  ).forEach((r) => { conv[r.id] = r; });

  const stockWhere = filterWhere({ store: f.store, city: f.city, region: f.region }, '');
  const stock = {};
  all(
    `SELECT i.product_id AS id, SUM(i.stock_qty) AS qty
     FROM inventory i JOIN stores st ON st.store_id = i.store_id ${stockWhere.where} GROUP BY 1`,
    stockWhere.params
  ).forEach((r) => { stock[r.id] = r.qty; });

  const growthOf = Object.fromEntries(trends.map((t) => [t.label, t.growth]));
  // Comparing against the category median only means something with 3+ peers.
  const catMedian = {};
  for (const cat of new Set(products.map((p) => p.category))) {
    const peers = products.filter((p) => p.category === cat);
    if (peers.length >= 3) catMedian[cat] = median(peers.map((p) => p.revenue));
  }

  const rows = products.map((p) => {
    const c = conv[p.id];
    const rate = c && c.tried >= 30 ? c.selected / c.tried : null;
    const perDay = p.units90 / 90;
    return {
      label: p.label,
      category: p.category,
      units: p.units,
      revenue: p.revenue,
      vsCategory: catMedian[p.category] ? p.revenue / catMedian[p.category] : 1,
      growth: growthOf[p.label] ?? null,
      conversion: rate,
      coverDays: perDay > 0 && stock[p.id] != null ? stock[p.id] / perDay : null,
    };
  });

  const avgConv = median(rows.map((r) => r.conversion).filter((v) => v != null));
  const medCover = median(rows.map((r) => r.coverDays).filter((v) => v != null));
  rows.forEach((r) => {
    r.reasons = [];
    if (r.vsCategory < 0.75) r.reasons.push(`revenue ${Math.round((1 - r.vsCategory) * 100)}% below category median`);
    if (r.growth != null && r.growth < -0.05) r.reasons.push(`sales down ${Math.round(-r.growth * 100)}% year on year`);
    if (r.conversion != null && r.conversion < avgConv * 0.85) r.reasons.push('tried on mirror, rarely picked');
    if (r.coverDays != null && r.coverDays > medCover * 1.5) r.reasons.push(`overstocked (${Math.round(r.coverDays)} days of stock)`);
  });
  return rows
    .filter((r) => r.reasons.length)
    .sort((a, b) => b.reasons.length - a.reasons.length || a.vsCategory - b.vsCategory)
    .slice(0, 6);
}

function buildReport(filters) {
  const f = normalizeFilters(filters);
  const db = openDb();
  try {
    const sales = filterWhere(f, 's.sale_date');
    const salesFrom = `FROM sales s JOIN products p ON p.product_id = s.product_id JOIN stores st ON st.store_id = s.store_id ${sales.where}`;
    const all = (sql, params) => db.prepare(sql).all(...params).map((r) => ({ ...r }));

    const totals = db
      .prepare(`SELECT COALESCE(SUM(s.quantity), 0) AS units, COALESCE(SUM(s.amount), 0) AS revenue,
                COUNT(DISTINCT s.bill_id) AS bills, MIN(s.sale_date) AS first, MAX(s.sale_date) AS last ${salesFrom}`)
      .get(...sales.params);

    // Within one category, "type" means fabric (silk, cotton...); across
    // categories it means the category itself.
    const typeCol = f.category ? 'p.fabric' : 'p.category';
    const byType = all(`SELECT ${typeCol} AS label, SUM(s.quantity) AS units, SUM(s.amount) AS revenue ${salesFrom} GROUP BY 1 ORDER BY units DESC`, sales.params);
    const byColour = all(`SELECT p.color AS label, SUM(s.quantity) AS units, SUM(s.amount) AS revenue ${salesFrom} GROUP BY 1 ORDER BY units DESC`, sales.params);
    const byStore = all(`SELECT st.store_name AS label, SUM(s.quantity) AS units, SUM(s.amount) AS revenue ${salesFrom} GROUP BY 1 ORDER BY revenue DESC`, sales.params);
    const trend = all(`SELECT SUBSTR(s.sale_date, 1, 7) AS month, SUM(s.quantity) AS units, SUM(s.amount) AS revenue ${salesFrom} GROUP BY 1 ORDER BY 1`, sales.params);
    const topProducts = all(`SELECT p.product_name AS label, SUM(s.quantity) AS units, SUM(s.amount) AS revenue ${salesFrom} GROUP BY 1 ORDER BY revenue DESC LIMIT 5`, sales.params);

    // Views come from the smart-mirror sessions, which only exist from the
    // mirror go-live date onwards.
    const allTime = { ...f, from: undefined, to: undefined };
    const monthlyAllTime = all(`SELECT SUBSTR(s.sale_date, 1, 7) AS month, SUM(s.quantity) AS units, SUM(s.amount) AS revenue
      FROM sales s JOIN products p ON p.product_id = s.product_id JOIN stores st ON st.store_id = s.store_id
      ${filterWhere(allTime, 's.sale_date').where} GROUP BY 1 ORDER BY 1`, filterWhere(allTime, 's.sale_date').params);
    const trends = productTrends(all, f, DB_INFO.lastSale);

    const views = filterWhere(f, 'SUBSTR(ms.started_at, 1, 10)');
    const mostViewed = all(
      `SELECT p.product_name AS label,
              SUM(e.event_type = 'viewed') AS views,
              SUM(e.event_type = 'tried') AS tried,
              SUM(e.event_type = 'selected') AS selected
       FROM session_events e
       JOIN products p ON p.product_id = e.product_id
       JOIN mirror_sessions ms ON ms.session_id = e.session_id
       JOIN stores st ON st.store_id = ms.store_id
       ${views.where}
       GROUP BY 1 ORDER BY views DESC LIMIT 5`,
      views.params
    );

    return {
      filters: f,
      noun: f.category ? pluralize(f.category) : 'items',
      typeLabel: f.category ? 'fabric' : 'category',
      period: { first: totals.first, last: totals.last },
      totals: {
        units: totals.units,
        revenue: totals.revenue,
        bills: totals.bills,
        avgPrice: totals.units ? totals.revenue / totals.units : 0,
      },
      byType,
      byColour,
      byStore,
      trend,
      topProducts,
      mostViewed,
      mirrorAge: mirrorByAge(all, f),
      sareeAge: sareesByAge(all, f),
      western: westernWear(all, f),
      monthlyAllTime,
      forecast: forecast(monthlyAllTime, DB_INFO.lastSale),
      trends,
      underperformers: underperformers(all, f, trends, DB_INFO.lastSale),
    };
  } finally {
    db.close();
  }
}

function reportUrl(filters, title, prompt) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(normalizeFilters(filters))) qs.set(k, v);
  if (title) qs.set('title', String(title).slice(0, 80));
  if (prompt) qs.set('q', String(prompt).slice(0, 80));
  return '/report.html?' + qs.toString();
}

// What Gemini gets back from open_report: enough numbers to write a summary.
function reportSummary(report) {
  const top = (rows) => rows.slice(0, 3).map((r) => r.label);
  return {
    filtersApplied: report.filters,
    period: report.period,
    unitsSold: report.totals.units,
    revenueINR: Math.round(report.totals.revenue),
    avgPriceINR: Math.round(report.totals.avgPrice),
    bills: report.totals.bills,
    [`top_${report.typeLabel}`]: top(report.byType),
    topColours: top(report.byColour),
    topStoresByRevenue: top(report.byStore),
    mostViewedOnMirror: top(report.mostViewed),
    mirrorSessionsByAge: report.mirrorAge.map((r) => ({ age: r.age, sessions: r.sessions, boughtPct: Math.round((r.converted / (r.sessions || 1)) * 100) })),
    forecastNext12MonthsINR: report.forecast ? Math.round(report.forecast.nextRevenue) : null,
    forecastGrowthPct: report.forecast ? Math.round((report.forecast.growth - 1) * 100) : null,
    fastestGrowing: report.trends.slice(0, 3).map((t) => `${t.label} (${Math.round(t.growth * 100)}%)`),
    underperforming: report.underperformers.map((u) => `${u.label}: ${u.reasons.join(', ')}`),
  };
}

const CHAT_TOOLS = [
  {
    functionDeclarations: [
      {
        name: 'open_report',
        description:
          'Build a graphical report (KPIs, breakdown by type and colour, most viewed items, mirror users by age group, ' +
          'saree types tried by age, western tops & bottoms, monthly trend, next-12-month forecast, year-on-year trends, ' +
          'underperforming products, store split) ' +
          'for the given filters. Returns summary numbers; the user gets a link to the full report automatically. ' +
          'Leave a filter out to include everything.',
        parameters: {
          type: 'object',
          properties: {
            title: { type: 'string', description: 'Short lowercase report title, e.g. "sarees report" or "september revenue report".' },
            category: { type: 'string', enum: DB_INFO.values.category },
            gender: { type: 'string', enum: DB_INFO.values.gender },
            store: { type: 'string', enum: DB_INFO.values.store },
            city: { type: 'string', enum: DB_INFO.values.city },
            region: { type: 'string', enum: DB_INFO.values.region },
            style: { type: 'string', enum: DB_INFO.values.style, description: 'Western, Traditional or Fusion wear.' },
            from: { type: 'string', description: 'Start date, YYYY-MM-DD (inclusive).' },
            to: { type: 'string', description: 'End date, YYYY-MM-DD (inclusive).' },
          },
          required: ['title'],
        },
      },
      {
        name: 'query_sales',
        description: 'Run a read-only SQLite SELECT query against the retail database and get the rows back.',
        parameters: {
          type: 'object',
          properties: { sql: { type: 'string', description: 'A single SQLite SELECT statement.' } },
          required: ['sql'],
        },
      },
    ],
  },
];

const SYSTEM_PROMPT =
  'You are the reflexn reporting assistant for Pikkcom, a Kerala retail company with smart mirrors in its stores. ' +
  'When the user asks for a report, performance, overview, breakdown or revenue/sales figures that can be scoped by ' +
  'category, gender, style, store, city, region or period - including forecasts, predictions, trends, age groups, ' +
  'western wear or underperforming products - call open_report with matching filters. ' +
  'After it returns, reply with a 2-3 line summary using its numbers, then end with exactly: ' +
  '"Click the link below for the complete report." Never write the link or URL yourself. ' +
  'For other data questions use query_sales. Always use a tool before stating any number; never invent figures. ' +
  'Revenue means SUM(amount) and is in INR (format below ₹1 lakh like ₹84,500, below ₹1 crore like ₹31.4L, otherwise like ₹12.66 Cr). Units sold means SUM(quantity). ' +
  `Sales data runs from ${DB_INFO.firstSale} to ${DB_INFO.lastSale}. "This month" means the latest month in the data ` +
  'unless the user names one. If the data cannot answer the question, say so plainly. ' +
  'Reply in plain text only, with no Markdown (no **, #, or tables), because the chat window shows text as-is; ' +
  'start list items with "• ". ' +
  'For greetings or general questions, just reply conversationally.\n\n' +
  'SQLite schema (sales_flat is a convenience view over sales):\n' +
  DB_INFO.schema;

// --- Gemini (Google Generative Language REST API) ---

async function callGemini(contents) {
  const aiRes = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': process.env.GEMINI_API_KEY },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: SYSTEM_PROMPT }] },
        tools: CHAT_TOOLS,
        contents,
      }),
    }
  );
  const data = await aiRes.json();
  if (!aiRes.ok) {
    const err = new Error(data.error?.message || 'Gemini returned an error');
    err.status = aiRes.status;
    throw err;
  }
  return data;
}

// The browser sends back plain {role, content} text turns. Convert them to
// Gemini's format and make sure the history starts on a user turn.
function toGeminiHistory(history) {
  const turns = (Array.isArray(history) ? history : [])
    .filter((m) => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && m.content)
    .slice(-10);
  while (turns.length && turns[0].role !== 'user') turns.shift();
  return turns.map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] }));
}

// Lets Gemini call query_sales as many times as it needs (up to a cap),
// then returns its final text answer.
async function answerWithData(message, history) {
  let link = null;
  const contents = [...toGeminiHistory(history), { role: 'user', parts: [{ text: message }] }];

  for (let round = 0; round < 6; round++) {
    const data = await callGemini(contents);
    const candidate = data.candidates?.[0];
    if (!candidate?.content) {
      if (data.promptFeedback?.blockReason || candidate?.finishReason === 'SAFETY') {
        return { reply: 'Sorry, I can’t help with that request.', reportUrl: null };
      }
      break;
    }

    const parts = candidate.content.parts || [];
    const calls = parts.filter((p) => p.functionCall);
    if (!calls.length) {
      const text = parts.filter((p) => p.text && !p.thought).map((p) => p.text).join('').trim();
      // The link is shown as a button, so drop any URL the model wrote anyway.
      return { reply: text.replace(/\S*report\.html\S*/g, '').trim(), reportUrl: link };
    }

    // Send the model's turn back unchanged — it carries thought signatures
    // that Gemini needs to see again on the next request.
    contents.push(candidate.content);

    const responses = calls.map(({ functionCall }) => {
      let result;
      try {
        if (functionCall.name === 'open_report') {
          console.log('[chat] report:', JSON.stringify(functionCall.args));
          result = reportSummary(buildReport(functionCall.args));
          link = reportUrl(functionCall.args, functionCall.args?.title, message);
        } else {
          console.log('[chat] SQL:', String(functionCall.args?.sql).replace(/\s+/g, ' '));
          result = runReadOnlyQuery(functionCall.args?.sql);
        }
      } catch (e) {
        result = { error: e.message };
      }
      return { functionResponse: { name: functionCall.name, id: functionCall.id, response: result } };
    });
    contents.push({ role: 'user', parts: responses });
  }
  return { reply: 'Sorry, I could not work out an answer to that from the sales data.', reportUrl: link };
}

function chatErrorMessage(e) {
  if (e.status === 400 && /api key/i.test(e.message)) return 'the Gemini API key is invalid — check GEMINI_API_KEY in .env';
  if (e.status === 403) return 'the Gemini API key is not allowed to use this model — check GEMINI_API_KEY in .env';
  if (e.status === 429) return 'Gemini is rate-limited or out of quota right now — try again in a moment';
  if (e.status) return e.message;
  return 'could not reach Gemini';
}

// --- routes ---

const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);

  if (req.method === 'POST' && parsed.pathname === '/api/signup') {
    try {
      const { username, password } = await readBody(req);

      if (!username || !password) {
        return sendJSON(res, 400, { error: 'username and password are required' });
      }
      if (password.length < 6) {
        return sendJSON(res, 400, { error: 'password must be at least 6 characters' });
      }

      const users = loadUsers();
      if (users[username]) {
        return sendJSON(res, 409, { error: 'that username is already taken' });
      }

      const salt = crypto.randomBytes(16).toString('hex');
      const hash = hashPassword(password, salt);
      users[username] = { salt, hash, createdAt: new Date().toISOString() };
      saveUsers(users);

      const token = createSession(username);
      res.setHeader('Set-Cookie', `session=${token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=86400`);
      return sendJSON(res, 201, { message: 'account created', username });
    } catch (e) {
      return sendJSON(res, 400, { error: 'invalid request body' });
    }
  }

  if (req.method === 'POST' && parsed.pathname === '/api/login') {
    try {
      const { username, password } = await readBody(req);

      if (!username || !password) {
        return sendJSON(res, 400, { error: 'username and password are required' });
      }

      const users = loadUsers();
      const user = users[username];
      if (!user) {
        return sendJSON(res, 401, { error: 'no account found for that username' });
      }

      const hash = hashPassword(password, user.salt);
      if (hash !== user.hash) {
        return sendJSON(res, 401, { error: 'incorrect password' });
      }

      const token = createSession(username);
      res.setHeader('Set-Cookie', `session=${token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=86400`);
      return sendJSON(res, 200, { message: 'signed in', username });
    } catch (e) {
      return sendJSON(res, 400, { error: 'invalid request body' });
    }
  }

  if (req.method === 'GET' && parsed.pathname === '/api/me') {
    const session = getSession(req);
    if (!session) return sendJSON(res, 401, { error: 'not signed in' });
    return sendJSON(res, 200, { username: session.username });
  }

  if (req.method === 'POST' && parsed.pathname === '/api/logout') {
    const session = getSession(req);
    if (session) sessions.delete(session.token);
    res.setHeader('Set-Cookie', 'session=; HttpOnly; Path=/; Max-Age=0');
    return sendJSON(res, 200, { message: 'signed out' });
  }

  if (req.method === 'POST' && parsed.pathname === '/api/chat') {
    const session = getSession(req);
    if (!session) {
      return sendJSON(res, 401, { error: 'not signed in' });
    }
    if (!process.env.GEMINI_API_KEY) {
      return sendJSON(res, 500, { error: 'GEMINI_API_KEY is not set on the server (.env)' });
    }

    try {
      const { message, history } = await readBody(req);
      if (!message || typeof message !== 'string') {
        return sendJSON(res, 400, { error: 'message is required' });
      }

      const { reply, reportUrl } = await answerWithData(message, history);
      return sendJSON(res, 200, { reply, reportUrl });
    } catch (e) {
      console.error('[chat] error:', e.message);
      return sendJSON(res, 502, { error: chatErrorMessage(e) });
    }
  }

  if (req.method === 'GET' && parsed.pathname === '/api/report') {
    if (!getSession(req)) return sendJSON(res, 401, { error: 'not signed in' });
    try {
      return sendJSON(res, 200, buildReport(parsed.query));
    } catch (e) {
      console.error('[report] error:', e.message);
      return sendJSON(res, 500, { error: 'could not build the report' });
    }
  }

  if (req.method === 'GET') {
    return serveStatic(req, res);
  }

  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('Not found');
});

server.listen(PORT, () => {
  console.log(`reflexn backend running at http://localhost:${PORT}`);
});