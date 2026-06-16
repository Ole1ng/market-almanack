"use strict";

// Map panel_key -> render function for its payload body.
const RENDERERS = {
  screener_day: renderScreener,
  screener_swing: renderScreener,
  earnings: renderEarnings,
  news_us: renderNews,
  news_global: renderNews,
  news_energy: renderNews,
  news_precious: renderNews,
  news_commodities: renderNews,
  analysis_macro: renderMacro,
  analysis_commodity: renderCommodity,
  spy_positioning: renderSpyPositioning,
  ticker_positioning: renderTickerPositioning,
  cftc_positioning: renderCftcPositioning,
};

const $ = (sel, root = document) => root.querySelector(sel);

// --------------------------------------------------------------------------
// Utilities
// --------------------------------------------------------------------------

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function relTime(epochSec) {
  if (!epochSec) return "unknown time";
  const diff = Date.now() / 1000 - epochSec;
  if (diff < 0) return "just now";
  const units = [
    [31536000, "y"], [2592000, "mo"], [604800, "w"],
    [86400, "d"], [3600, "h"], [60, "m"],
  ];
  for (const [s, label] of units) {
    if (diff >= s) return `${Math.floor(diff / s)}${label} ago`;
  }
  return `${Math.floor(diff)}s ago`;
}

function absTime(epochSec) {
  if (!epochSec) return "never";
  return new Date(epochSec * 1000).toLocaleString();
}

function pct(frac) {
  if (frac == null) return "—";
  const v = frac * 100;
  const cls = v > 0 ? "pos" : v < 0 ? "neg" : "";
  const sign = v > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${v.toFixed(2)}%</span>`;
}

function fmtNum(n) {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return String(n);
}

// --------------------------------------------------------------------------
// Panel framing (badge + timestamp + body)
// --------------------------------------------------------------------------

function panelEls(key) {
  const root = document.getElementById("panel-" + key);
  return {
    root,
    badge: $("[data-badge]", root),
    updated: $("[data-updated]", root),
    body: $("[data-body]", root),
  };
}

function setMeta(key, record) {
  const { badge, updated } = panelEls(key);
  if (!record || record.updated_at == null) {
    badge.className = "badge empty";
    badge.textContent = "no data";
    updated.textContent = "never";
    updated.title = "";
    return;
  }
  const status = record.status || "ok";
  // An error after a prior successful fetch = stale cache still showing.
  const hasPayload = record.payload && (
    Array.isArray(record.payload) ? record.payload.length :
    (record.payload.rows ? record.payload.rows.length : true));
  let cls = status, label = status;
  if (status === "error" && hasPayload) { cls = "stale"; label = "stale"; }
  else if (status === "error") { cls = "error"; label = "error"; }
  else if (status === "empty") { cls = "empty"; label = "empty"; }
  else { cls = "ok"; label = "ok"; }

  badge.className = "badge " + cls;
  badge.textContent = label;
  badge.title = record.error || "";
  updated.textContent = relTime(record.updated_at);
  updated.title = "Last updated: " + absTime(record.updated_at);
}

function renderPanel(key, record) {
  setMeta(key, record);
  const { body } = panelEls(key);
  const fn = RENDERERS[key];
  const payload = record ? record.payload : null;
  try {
    fn(body, payload, record);
  } catch (e) {
    body.innerHTML = `<p class="empty-note">Render error: ${esc(e.message)}</p>`;
  }
}

function renderAll(state) {
  for (const key of Object.keys(RENDERERS)) {
    renderPanel(key, state[key]);
  }
}

// --------------------------------------------------------------------------
// Screener renderer (sortable table)
// --------------------------------------------------------------------------

const NUMERIC_COLS = new Set(
  ["Price", "Change", "Perf Week", "Perf Month", "Volume", "Rel Volume", "Float", "Beta"]);
const PCT_COLS = new Set(["Change", "Perf Week", "Perf Month"]);

function renderScreener(body, payload) {
  if (!payload || !payload.rows || payload.rows.length === 0) {
    body.innerHTML = `<p class="empty-note">No matches — refresh screeners to populate.</p>`;
    return;
  }
  const cols = payload.columns;
  const rows = payload.rows;

  const wrap = document.createElement("div");
  wrap.className = "tbl-wrap";
  const tbl = document.createElement("table");
  tbl.className = "screener";

  const thead = document.createElement("thead");
  const htr = document.createElement("tr");
  cols.forEach((c) => {
    const th = document.createElement("th");
    th.textContent = c;
    th.setAttribute("scope", "col");
    th.tabIndex = 0;
    th.addEventListener("click", () => sortBy(tbl, cols, rows, c));
    th.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(tbl, cols, rows, c); }
    });
    htr.appendChild(th);
  });
  thead.appendChild(htr);
  tbl.appendChild(thead);

  const tbody = document.createElement("tbody");
  fillRows(tbody, cols, rows);
  tbl.appendChild(tbody);

  wrap.appendChild(tbl);
  body.innerHTML = "";
  body.appendChild(wrap);
}

function fillRows(tbody, cols, rows) {
  tbody.innerHTML = "";
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    cols.forEach((c) => {
      const td = document.createElement("td");
      const v = row[c];
      if (c === "Ticker") {
        td.innerHTML = `<span class="tkr">${esc(v)}</span>`;
      } else if (PCT_COLS.has(c)) {
        td.innerHTML = pct(v);
      } else if (c === "Volume" || c === "Float") {
        td.textContent = fmtNum(v);
      } else if (c === "Price" || c === "Beta" || c === "Rel Volume") {
        td.textContent = v == null ? "—" : Number(v).toFixed(2);
      } else {
        td.textContent = v == null ? "—" : v;
      }
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
}

function sortBy(tbl, cols, rows, col) {
  const ths = tbl.querySelectorAll("th");
  const idx = cols.indexOf(col);
  const prev = ths[idx].getAttribute("aria-sort");
  const dir = prev === "ascending" ? "descending" : "ascending";
  ths.forEach((th) => th.removeAttribute("aria-sort"));
  ths[idx].setAttribute("aria-sort", dir);

  const numeric = NUMERIC_COLS.has(col);
  const sorted = rows.slice().sort((a, b) => {
    let x = a[col], y = b[col];
    if (numeric) {
      x = x == null ? -Infinity : x; y = y == null ? -Infinity : y;
      return dir === "ascending" ? x - y : y - x;
    }
    x = (x == null ? "" : String(x)).toLowerCase();
    y = (y == null ? "" : String(y)).toLowerCase();
    return dir === "ascending" ? x.localeCompare(y) : y.localeCompare(x);
  });
  fillRows(tbl.querySelector("tbody"), cols, sorted);
}

// --------------------------------------------------------------------------
// Earnings renderer (grouped by date, sticky date headers)
// --------------------------------------------------------------------------

const TIME_ABBR = {
  "Before Market Open": "BMO",
  "After Market Close": "AMC",
  "Time Not Supplied": "—",
};

function renderEarnings(body, payload) {
  if (!payload || !payload.rows || payload.rows.length === 0) {
    body.innerHTML = `<p class="empty-note">No earnings in the next ` +
      `${payload && payload.lookahead_days ? payload.lookahead_days : 14} days ` +
      `for the watchlist — refresh earnings (or screeners) to populate.</p>`;
    return;
  }

  const tbl = document.createElement("table");
  tbl.className = "screener earn";
  tbl.innerHTML =
    `<thead><tr>` +
    `<th scope="col">Ticker</th>` +
    `<th scope="col">Company</th>` +
    `<th scope="col">Time</th>` +
    `<th scope="col">EPS Est.</th>` +
    `<th scope="col">In screener?</th>` +
    `</tr></thead>`;

  const tbody = document.createElement("tbody");
  let lastDate = null;
  payload.rows.forEach((r) => {
    if (r.date !== lastDate) {
      lastDate = r.date;
      const gh = document.createElement("tr");
      gh.className = "date-group-head";
      gh.innerHTML = `<th colspan="5" scope="colgroup">` +
        `${esc(r.date_label)} &middot; <span class="dow">${esc(r.dow)}</span></th>`;
      tbody.appendChild(gh);
    }
    const tr = document.createElement("tr");
    const abbr = TIME_ABBR[r.time] || "—";
    const badge = r.in_screener
      ? `<span class="scr-badge ${esc(r.in_screener)}">${esc(r.in_screener)}</span>`
      : "";
    tr.innerHTML =
      `<td><a class="tkr-link" href="https://finance.yahoo.com/quote/${encodeURIComponent(r.ticker)}" ` +
        `target="_blank" rel="noopener noreferrer">${esc(r.ticker)}</a></td>` +
      `<td class="company">${esc(r.company)}</td>` +
      `<td><span class="time-tag t-${abbr.toLowerCase()}" title="${esc(r.time)}">${abbr}</span></td>` +
      `<td>${r.eps_estimate == null ? "—" : Number(r.eps_estimate).toFixed(2)}</td>` +
      `<td>${badge}</td>`;
    tbody.appendChild(tr);
  });
  tbl.appendChild(tbody);

  const wrap = document.createElement("div");
  wrap.className = "tbl-wrap";
  wrap.appendChild(tbl);
  body.innerHTML = "";
  body.appendChild(wrap);
}

// --------------------------------------------------------------------------
// News renderer
// --------------------------------------------------------------------------

function renderNews(body, items) {
  if (!items || items.length === 0) {
    body.innerHTML = `<p class="empty-note">No headlines yet — refresh news.</p>`;
    return;
  }
  const ul = document.createElement("ul");
  ul.className = "feed";
  items.forEach((it) => {
    const li = document.createElement("li");
    li.innerHTML =
      `<a class="feed-title" href="${esc(it.link)}" target="_blank" rel="noopener noreferrer">${esc(it.title)}</a>` +
      `<div class="feed-meta"><span class="src">${esc(it.source)}</span> &middot; ${esc(relTime(it.published))}</div>`;
    ul.appendChild(li);
  });
  body.innerHTML = "";
  body.appendChild(ul);
}

// --------------------------------------------------------------------------
// Analysis renderers
// --------------------------------------------------------------------------

function toneRow(sent) {
  const breakdown =
    `${sent.pos_pct}% positive, ${sent.neg_pct}% negative, ${sent.neu_pct}% neutral ` +
    `&middot; mean sentiment ${sent.mean >= 0 ? "+" : ""}${sent.mean}`;
  return `<div class="an-row"><span class="an-label">Tone:</span>` +
    `<span class="tone ${esc(sent.tone)}">${esc(sent.tone)}</span> ` +
    `<span class="feed-meta">${breakdown}</span></div>`;
}

function chips(list, keyName, valName, cls) {
  if (!list || !list.length) return `<span class="empty-note">none</span>`;
  return `<div class="chips">` + list.map((x) =>
    `<span class="chip ${cls || ""}">${esc(x[keyName])}<span class="ct">${x[valName]}</span></span>`
  ).join("") + `</div>`;
}

function salientList(list) {
  if (!list || !list.length) return `<span class="empty-note">none</span>`;
  return `<ol class="salient">` + list.map((h) =>
    `<li><a href="${esc(h.link)}" target="_blank" rel="noopener noreferrer">${esc(h.title)}</a></li>`
  ).join("") + `</ol>`;
}

function sentBar(sent) {
  return `<div class="sentbar" role="img" aria-label="Sentiment distribution: ` +
    `${sent.pos_pct}% positive, ${sent.neu_pct}% neutral, ${sent.neg_pct}% negative">` +
    `<span class="s-pos" style="width:${sent.pos_pct}%"></span>` +
    `<span class="s-neu" style="width:${sent.neu_pct}%"></span>` +
    `<span class="s-neg" style="width:${sent.neg_pct}%"></span></div>` +
    `<div class="sentbar-legend">` +
    `<span class="pos">${sent.pos_pct}% pos</span> &middot; ` +
    `${sent.neu_pct}% neu &middot; ` +
    `<span class="neg">${sent.neg_pct}% neg</span></div>`;
}

function analysisBlock(a, opts = {}) {
  const showBar = opts.showBar !== false;
  return (
    toneRow(a.sentiment) +
    `<div class="an-row"><span class="an-label">Top themes:</span>${chips(a.themes, "term", "count")}</div>` +
    `<div class="an-row"><span class="an-label">Top entities:</span>${chips(a.entities, "entity", "count", "entity")}</div>` +
    `<div class="an-row"><span class="an-label">Headlines driving the narrative:</span>${salientList(a.salient)}</div>` +
    (showBar ? `<div class="an-row">${sentBar(a.sentiment)}</div>` : "")
  );
}

function renderMacro(body, payload) {
  if (!payload || payload.empty) {
    body.innerHTML = `<p class="empty-note">No data yet — refresh news first, then update analysis.</p>`;
    return;
  }
  body.innerHTML =
    `<div class="an-block">` + analysisBlock(payload) + `</div>` +
    `<p class="caveat">${esc(payload.caveat)}</p>`;
}

function renderCommodity(body, payload) {
  if (!payload || payload.empty) {
    body.innerHTML = `<p class="empty-note">No data yet — refresh news first, then update analysis.</p>`;
    return;
  }
  const b = payload.blocks;
  const block = (title, a) =>
    `<div class="an-block"><h3 class="an-sub">${title}</h3>` +
    (a.count === 0 ? `<p class="empty-note">No headlines in this complex.</p>`
                   : analysisBlock(a, { showBar: false })) +
    `</div>`;

  body.innerHTML =
    block("Energy", b.energy) +
    block("Precious Metals", b.precious) +
    block("Other Commodities", b.other) +
    `<div class="an-block"><h3 class="an-sub">Cross-Complex Summary</h3>` +
    toneRow(payload.cross.sentiment) +
    `<div class="an-row"><span class="an-label">Top themes across all:</span>${chips(payload.cross.themes, "term", "count")}</div>` +
    sentBar(payload.cross.sentiment) +
    `</div>` +
    `<p class="caveat">${esc(payload.caveat)}</p>`;
}

// --------------------------------------------------------------------------
// SPY positioning renderer (4-row decision hierarchy + diverging GEX chart)
// --------------------------------------------------------------------------

function fmtUsd(x) {
  if (x == null) return "—";
  const a = Math.abs(x), s = x < 0 ? "-" : "";
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(1)}bn`;
  return `${s}$${(a / 1e6).toFixed(0)}mm`;
}
function px(x) { return x == null ? "—" : Number(x).toFixed(2); }
function spct(frac) { return frac == null ? "—" : `${(frac * 100).toFixed(2)}%`; }

function spyCard(label, value, sub, cls) {
  return `<div class="spy-card">` +
    `<div class="spy-card-label">${esc(label)}</div>` +
    `<div class="spy-card-value ${cls || ""}">${value}</div>` +
    `<div class="spy-card-sub">${sub || ""}</div></div>`;
}

function spyGexChart(p, bucket = 5) {
  const chart = (p.chart || []).slice().sort((a, b) => b.strike - a.strike);
  if (!chart.length) return `<p class="empty-note">No strike data in window.</p>`;

  const n = chart.length;
  const rowH = 20, padTop = 26, padBot = 14;
  const H = padTop + padBot + n * rowH;
  const cx = 520, half = 440, gutter = 6;
  let maxAbs = 0;
  chart.forEach((c) => {
    maxAbs = Math.max(maxAbs, Math.abs(c.call_gex), Math.abs(c.put_gex));
  });
  maxAbs = maxAbs || 1;

  const strikes = chart.map((c) => c.strike);
  const maxK = strikes[0], minK = strikes[n - 1];
  const yFirst = padTop + rowH / 2, yLast = padTop + (n - 1) * rowH + rowH / 2;
  const yOf = (price) => {
    if (price == null || maxK === minK) return null;
    const f = Math.min(1, Math.max(0, (maxK - price) / (maxK - minK)));
    return yFirst + f * (yLast - yFirst);
  };

  let svg = `<svg class="gex-chart" viewBox="0 0 1000 ${H}" role="img" ` +
    `aria-label="Gamma exposure by strike; put GEX left, call GEX right">`;
  // axis
  svg += `<line x1="${cx}" y1="${padTop - 8}" x2="${cx}" y2="${H - padBot + 4}" class="gex-axis"/>`;

  const magnetSet = new Set((p.oi_magnets || []).map((m) => Math.round(m.strike / bucket) * bucket));

  chart.forEach((c, i) => {
    const y = padTop + i * rowH + rowH / 2;
    const callW = (Math.abs(c.call_gex) / maxAbs) * half;
    const putW = (Math.abs(c.put_gex) / maxAbs) * half;
    if (callW > 0.5)
      svg += `<rect class="gex-call" x="${cx + gutter}" y="${y - rowH * 0.32}" ` +
        `width="${callW}" height="${rowH * 0.64}"/>`;
    if (putW > 0.5)
      svg += `<rect class="gex-put" x="${cx - gutter - putW}" y="${y - rowH * 0.32}" ` +
        `width="${putW}" height="${rowH * 0.64}"/>`;
    svg += `<text class="gex-strike" x="${cx}" y="${y + 3}" text-anchor="middle">${px(c.strike)}</text>`;
    if (magnetSet.has(Math.round(c.strike / bucket) * bucket))
      svg += `<circle class="gex-magnet" cx="${cx - gutter - putW - 8}" cy="${y}" r="3"/>`;
  });

  // overlay lines: spot + zero gamma
  const ys = yOf(p.spot);
  if (ys != null) {
    svg += `<line class="gex-spot" x1="40" y1="${ys}" x2="980" y2="${ys}"/>`;
    svg += `<text class="gex-spot-lbl" x="44" y="${ys - 4}">Spot ${px(p.spot)}</text>`;
  }
  const yz = yOf(p.zero_gamma);
  if (yz != null) {
    svg += `<line class="gex-zero" x1="40" y1="${yz}" x2="980" y2="${yz}"/>`;
    svg += `<text class="gex-zero-lbl" x="980" y="${yz - 4}" text-anchor="end">Flip ${px(p.zero_gamma)}</text>`;
  }
  // wall labels
  const yc = yOf(p.call_wall);
  if (yc != null)
    svg += `<text class="gex-wall call" x="976" y="${yc + 3}" text-anchor="end">Call wall</text>`;
  const yp = yOf(p.put_wall);
  if (yp != null)
    svg += `<text class="gex-wall put" x="24" y="${yp + 3}">Put wall</text>`;

  svg += `</svg>`;
  return svg;
}

function renderSpyPositioning(body, p) {
  if (!p || p.spot == null) {
    body.innerHTML = `<p class="empty-note">No data yet — click ` +
      `<strong>Refresh SPY Positioning</strong> to fetch the CBOE chain and compute the snapshot.</p>`;
    return;
  }
  const c = p.commentary || { headline: "", warnings: [], sentences: [] };
  const regimePos = p.regime === "positive";

  // Row 0 — commentary
  const warnings = (c.warnings || []).map((w) =>
    `<div class="spy-warn">${esc(w)}</div>`).join("");
  const sentences = (c.sentences || []).map((s) => esc(s)).join(" ");
  const row0 =
    `<div class="spy-row spy-commentary">` +
    warnings +
    `<div class="spy-headline">${esc(c.headline)}</div>` +
    `<p class="spy-prose">${sentences}</p></div>`;

  // Row 1 — regime header (4 cards)
  const flipSub = p.zero_gamma == null
    ? "no flip in ±8%"
    : `Flip at ${px(p.zero_gamma)}`;
  const cushVal = p.cushion == null ? "—"
    : `${p.cushion >= 0 ? "+" : ""}$${p.cushion.toFixed(2)} / ${spct(p.cushion_pct)}`;
  const dexShort = p.dex < 0;
  const row1 =
    `<div class="spy-row spy-cards-4">` +
    spyCard("Regime", regimePos ? "Positive gamma" : "Negative gamma", flipSub,
      regimePos ? "pos" : "neg") +
    spyCard("Spot vs Flip", cushVal, `Spot ${px(p.spot)}`,
      (p.cushion || 0) >= 0 ? "pos" : "neg") +
    spyCard("Net GEX", fmtUsd(p.net_gex), "per 1% move",
      p.net_gex >= 0 ? "pos" : "neg") +
    spyCard("DEX bias", fmtUsd(p.dex),
      dexShort ? "dealers net short delta" : "dealers net long delta",
      dexShort ? "neg" : "pos") +
    `</div>`;

  // Row 2 — gamma by strike chart
  const row2 = `<div class="spy-row spy-chart-row">${spyGexChart(p)}</div>`;

  // Row 3 — three small cards
  const ladder = [];
  if (p.call_wall != null) ladder.push(["Call wall", p.call_wall, "lvl-call"]);
  const nm = p.nearest_magnet;
  if (nm != null) ladder.push(["OI magnet", nm, "lvl-mag"]);
  if (p.zero_gamma != null) ladder.push(["Zero gamma", p.zero_gamma, "lvl-zero"]);
  if (p.put_wall != null) ladder.push(["Put wall", p.put_wall, "lvl-put"]);
  ladder.push(["Spot", p.spot, "lvl-spot"]);
  ladder.sort((a, b) => b[1] - a[1]);
  const levelsTbl = `<table class="spy-levels">` + ladder.map((r) =>
    `<tr class="${r[2]}"><td>${esc(r[0])}</td><td>${px(r[1])}</td></tr>`).join("") + `</table>`;

  const vannaSub = Math.abs(p.vanna_pressure) < 1e6 ? "neutral"
    : (p.vanna_pressure > 0
      ? "falling IV forces dealer buying (supportive)"
      : "rising IV forces dealer selling (fragile)");
  const charmSub = p.charm_drift >= 0
    ? "drift to buy into the close"
    : "drift to sell into the close";

  const row3 =
    `<div class="spy-row spy-cards-3">` +
    `<div class="spy-card spy-levels-card"><div class="spy-card-label">Key levels</div>${levelsTbl}</div>` +
    spyCard("Vanna pressure", `${fmtUsd(p.vanna_pressure)} / -1 vol pt`, vannaSub,
      p.vanna_pressure >= 0 ? "pos" : "neg") +
    spyCard("Charm drift", `${fmtUsd(p.charm_drift)} / day`,
      `${charmSub} · OPEX ${esc(p.next_opex || "")}`,
      p.charm_drift >= 0 ? "pos" : "neg") +
    `</div>`;

  const footer =
    `<div class="spy-footer">CBOE delayed snapshot ${esc(p.snapshot_ts || "")} · ` +
    `~15-min delayed · expirations ≤ ${p.expiry_window_days || 90}d · ` +
    `${p.n_contracts || 0} contracts · assumes dealers long calls / short puts.</div>`;

  body.innerHTML = row0 + row1 + row2 + row3 + footer;
}

// Same layout as renderSpyPositioning but for any user-supplied ticker. The
// auto-scaled payload has the identical shape; only the symbol label and the
// single-name footer caveat differ, plus the dynamic chart bucket. SPY's
// renderer is intentionally left untouched.
function renderTickerPositioning(body, p) {
  if (p == null) {
    body.innerHTML = `<p class="empty-note">Enter a ticker and press ` +
      `<strong>Go</strong> to fetch its CBOE option chain.</p>`;
    return;
  }
  if (p.not_found) {
    body.innerHTML = `<p class="empty-note">${esc(p.message ||
      ("No data found for " + (p.symbol || "ticker")))}</p>`;
    return;
  }
  if (p.spot == null) {
    body.innerHTML = `<p class="empty-note">Enter a ticker and press ` +
      `<strong>Go</strong> to fetch its CBOE option chain.</p>`;
    return;
  }
  const sym = esc(p.symbol || "Ticker");
  const c = p.commentary || { headline: "", warnings: [], sentences: [] };
  const regimePos = p.regime === "positive";

  // Row 0 — commentary
  const warnings = (c.warnings || []).map((w) =>
    `<div class="spy-warn">${esc(w)}</div>`).join("");
  const sentences = (c.sentences || []).map((s) => esc(s)).join(" ");
  const row0 =
    `<div class="spy-row spy-commentary">` +
    warnings +
    `<div class="spy-headline">${esc(c.headline)}</div>` +
    `<p class="spy-prose">${sentences}</p></div>`;

  // Row 1 — regime header (4 cards)
  const flipSub = p.zero_gamma == null
    ? "no flip in ±8%"
    : `Flip at ${px(p.zero_gamma)}`;
  const cushVal = p.cushion == null ? "—"
    : `${p.cushion >= 0 ? "+" : ""}$${p.cushion.toFixed(2)} / ${spct(p.cushion_pct)}`;
  const dexShort = p.dex < 0;
  const row1 =
    `<div class="spy-row spy-cards-4">` +
    spyCard("Regime", regimePos ? "Positive gamma" : "Negative gamma", flipSub,
      regimePos ? "pos" : "neg") +
    spyCard("Spot vs Flip", cushVal, `${sym} ${px(p.spot)}`,
      (p.cushion || 0) >= 0 ? "pos" : "neg") +
    spyCard("Net GEX", fmtUsd(p.net_gex), "per 1% move",
      p.net_gex >= 0 ? "pos" : "neg") +
    spyCard("DEX bias", fmtUsd(p.dex),
      dexShort ? "dealers net short delta" : "dealers net long delta",
      dexShort ? "neg" : "pos") +
    `</div>`;

  // Row 2 — gamma by strike chart (dynamic bucket for this ticker's price)
  const row2 = `<div class="spy-row spy-chart-row">${spyGexChart(p, p.bucket || 5)}</div>`;

  // Row 3 — three small cards
  const ladder = [];
  if (p.call_wall != null) ladder.push(["Call wall", p.call_wall, "lvl-call"]);
  const nm = p.nearest_magnet;
  if (nm != null) ladder.push(["OI magnet", nm, "lvl-mag"]);
  if (p.zero_gamma != null) ladder.push(["Zero gamma", p.zero_gamma, "lvl-zero"]);
  if (p.put_wall != null) ladder.push(["Put wall", p.put_wall, "lvl-put"]);
  ladder.push([sym, p.spot, "lvl-spot"]);
  ladder.sort((a, b) => b[1] - a[1]);
  const levelsTbl = `<table class="spy-levels">` + ladder.map((r) =>
    `<tr class="${r[2]}"><td>${esc(r[0])}</td><td>${px(r[1])}</td></tr>`).join("") + `</table>`;

  const vannaSub = Math.abs(p.vanna_pressure) < 1e6 ? "neutral"
    : (p.vanna_pressure > 0
      ? "falling IV forces dealer buying (supportive)"
      : "rising IV forces dealer selling (fragile)");
  const charmSub = p.charm_drift >= 0
    ? "drift to buy into the close"
    : "drift to sell into the close";

  const row3 =
    `<div class="spy-row spy-cards-3">` +
    `<div class="spy-card spy-levels-card"><div class="spy-card-label">Key levels</div>${levelsTbl}</div>` +
    spyCard("Vanna pressure", `${fmtUsd(p.vanna_pressure)} / -1 vol pt`, vannaSub,
      p.vanna_pressure >= 0 ? "pos" : "neg") +
    spyCard("Charm drift", `${fmtUsd(p.charm_drift)} / day`,
      `${charmSub} · OPEX ${esc(p.next_opex || "")}`,
      p.charm_drift >= 0 ? "pos" : "neg") +
    `</div>`;

  const footer =
    `<div class="spy-footer">${sym} · CBOE delayed snapshot ${esc(p.snapshot_ts || "")} · ` +
    `~15-min delayed · expirations ≤ ${p.expiry_window_days || 90}d · ` +
    `${p.n_contracts || 0} contracts · assumes dealers long calls / short puts ` +
    `(a rougher proxy for a single name than for SPY).</div>`;

  body.innerHTML = row0 + row1 + row2 + row3 + footer;
}

// --------------------------------------------------------------------------
// CFTC trader positioning renderer (per-contract gauge + verdict + spark)
// --------------------------------------------------------------------------

// A 0-100 horizontal gauge: state colours the fill, the number is the 3-yr
// percentile. `secondary` renders the thinner Asset-Managers variant.
function cftcGauge(label, block, secondary) {
  if (!block) return "";
  const pctl = block.pctl == null ? 0 : block.pctl;
  const w = Math.max(0, Math.min(100, pctl));
  const state = block.state || "neutral";
  const cls = secondary ? "cftc-gauge secondary" : "cftc-gauge";
  const aria = `${label}: ${pctl.toFixed(0)}th percentile over 3 years, ` +
    `net ${fmtNum(block.net)} contracts`;
  return `<div class="cftc-gauge-row">` +
    `<div class="cftc-gauge-label">${esc(label)}</div>` +
    `<div class="${cls}" role="img" aria-label="${esc(aria)}">` +
      `<div class="cftc-gauge-fill s-${esc(state)}" style="width:${w}%"></div>` +
    `</div>` +
    `<div class="cftc-gauge-num">${pctl.toFixed(0)}</div></div>`;
}

// Compact net-position-vs-price sparkline (dual independent scales) so a
// price/positioning divergence is visible at a glance. Pure SVG, theme colours.
function cftcSpark(series) {
  const pts = (series || []).filter((d) => d.lev_net != null);
  if (pts.length < 2) return "";
  const W = 1000, H = 90, padL = 4, padR = 4, padT = 8, padB = 8;
  const n = pts.length;
  const xs = (i) => padL + (i / (n - 1)) * (W - padL - padR);

  const nets = pts.map((p) => p.lev_net);
  const nmin = Math.min(...nets, 0), nmax = Math.max(...nets, 0);
  const nrange = (nmax - nmin) || 1;
  const yNet = (v) => padT + (1 - (v - nmin) / nrange) * (H - padT - padB);

  const prices = pts.map((p) => p.price).filter((v) => v != null);
  let pricePath = "";
  if (prices.length >= 2) {
    const pmin = Math.min(...prices), pmax = Math.max(...prices);
    const pr = (pmax - pmin) || 1;
    const yP = (v) => padT + (1 - (v - pmin) / pr) * (H - padT - padB);
    pricePath = pts.map((p, i) =>
      p.price == null ? null
        : `${i === 0 ? "M" : "L"}${xs(i).toFixed(1)},${yP(p.price).toFixed(1)}`
    ).filter(Boolean).join(" ");
  }
  const netPath = pts.map((p, i) =>
    `${i === 0 ? "M" : "L"}${xs(i).toFixed(1)},${yNet(p.lev_net).toFixed(1)}`
  ).join(" ");
  const yZero = yNet(0).toFixed(1);

  let svg = `<svg class="cftc-spark" viewBox="0 0 ${W} ${H}" ` +
    `preserveAspectRatio="none" role="img" ` +
    `aria-label="Leveraged Funds net position versus price over the lookback window">`;
  svg += `<line class="cftc-spark-zero" x1="0" y1="${yZero}" x2="${W}" y2="${yZero}"/>`;
  if (pricePath) svg += `<path class="cftc-spark-price" d="${pricePath}"/>`;
  svg += `<path class="cftc-spark-net" d="${netPath}"/></svg>`;
  return svg +
    `<div class="cftc-spark-legend"><span class="net">— LF net</span> · ` +
    `<span class="price">— price</span></div>`;
}

function renderCftcPositioning(body, p) {
  if (!p || !p.contracts || !p.contracts.length) {
    body.innerHTML = `<p class="empty-note">No data yet — click ` +
      `<strong>Refresh CFTC Positioning</strong> to fetch the latest ` +
      `Commitments of Traders report.</p>`;
    return;
  }
  const cards = p.contracts.map((ct) => {
    const lev = ct.lev || {}, am = ct.am;
    const state = lev.state || "neutral";
    const flags = [];
    if (ct.flags) {
      if (ct.flags.stale) flags.push(`<span class="cftc-flag stale">stale</span>`);
      if (ct.flags.price_missing) flags.push(`<span class="cftc-flag">no price</span>`);
      if (ct.flags.short_history) flags.push(`<span class="cftc-flag">short history</span>`);
    }
    const wowSign = lev.wow > 0 ? "+" : "";
    const netLine = `${lev.net >= 0 ? "net-long" : "net-short"} ` +
      `${fmtNum(Math.abs(lev.net))} · WoW ${wowSign}${fmtNum(lev.wow)}`;
    const amLine = am
      ? `<div class="cftc-meta sub">Asset Managers (real money): net ` +
        `${am.net >= 0 ? "+" : ""}${fmtNum(am.net)} · secondary read</div>`
      : "";
    return `<div class="cftc-contract">` +
      `<div class="cftc-contract-head">` +
        `<span class="cftc-contract-label">${esc(ct.label)}</span>${flags.join("")}</div>` +
      `<div class="cftc-verdict s-${esc(state)}">${esc(lev.verdict || "")}</div>` +
      cftcGauge("Leveraged Funds", lev, false) +
      `<div class="cftc-meta">${esc(netLine)}</div>` +
      `<p class="cftc-sentence">${esc(lev.sentence || "")}</p>` +
      (am ? cftcGauge("Asset Managers", am, true) : "") +
      amLine +
      cftcSpark(ct.series) +
    `</div>`;
  }).join("");

  body.innerHTML = `<div class="cftc-grid">${cards}</div>` +
    `<div class="spy-footer">As of ${esc(p.as_of || "")} · ${esc(p.caveat || "")}</div>`;
}

// --------------------------------------------------------------------------
// Refresh wiring
// --------------------------------------------------------------------------

function setStatus(msg) { $("#status-line").textContent = msg; }

async function runRefresh(endpoint, btn, label) {
  const buttons = document.querySelectorAll(".btn");
  buttons.forEach((b) => (b.disabled = true));
  btn.setAttribute("aria-busy", "true");
  setStatus(`${label}…`);
  try {
    const res = await fetch(endpoint, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const updated = await res.json();
    Object.entries(updated).forEach(([key, rec]) => renderPanel(key, rec));
    const errs = Object.values(updated).filter((r) => r && r.status === "error").length;
    setStatus(errs ? `${label} done — ${errs} panel(s) failed, showing cached data.`
                   : `${label} done.`);
  } catch (e) {
    setStatus(`${label} failed: ${e.message}. Cached data preserved.`);
  } finally {
    btn.removeAttribute("aria-busy");
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function init() {
  setStatus("Loading last session…");
  try {
    const res = await fetch("/api/state");
    const state = await res.json();
    renderAll(state);
    const any = Object.values(state).some((r) => r && r.updated_at);
    setStatus(any ? "Last session restored. Use the buttons to fetch fresh data."
                  : "No saved data yet. Use the buttons to fetch data.");
  } catch (e) {
    setStatus("Could not load saved state: " + e.message);
  }

  $("#btn-screeners").addEventListener("click", (e) =>
    runRefresh("/api/refresh/screeners", e.currentTarget, "Refreshing screeners + earnings"));
  $("#btn-earnings").addEventListener("click", (e) =>
    runRefresh("/api/refresh/earnings", e.currentTarget, "Refreshing earnings"));
  $("#btn-news").addEventListener("click", (e) =>
    runRefresh("/api/refresh/news", e.currentTarget, "Refreshing news"));
  $("#btn-analysis").addEventListener("click", (e) =>
    runRefresh("/api/refresh/analysis", e.currentTarget, "Updating analysis"));
  $("#btn-spy").addEventListener("click", (e) =>
    runRefresh("/api/refresh/spy_positioning", e.currentTarget, "Refreshing SPY positioning"));
  $("#btn-cftc").addEventListener("click", (e) =>
    runRefresh("/api/refresh/cftc_positioning", e.currentTarget, "Refreshing CFTC positioning"));

  // Ticker positioning has its own Go box (posts a symbol), so it uses a
  // dedicated handler instead of the body-less shared runRefresh.
  function runTickerPositioning() {
    const sym = ($("#ticker-input").value || "").trim().toUpperCase();
    if (!sym) { setStatus("Enter a ticker first."); return; }
    const btn = $("#btn-ticker");
    const buttons = document.querySelectorAll(".btn");
    buttons.forEach((b) => (b.disabled = true));
    btn.setAttribute("aria-busy", "true");
    setStatus(`Fetching ${sym} positioning…`);
    fetch(`/api/refresh/ticker_positioning?symbol=${encodeURIComponent(sym)}`,
          { method: "POST" })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then((updated) => {
        Object.entries(updated).forEach(([k, rec]) => renderPanel(k, rec));
        const rec = updated.ticker_positioning;
        const nf = rec && rec.payload && rec.payload.not_found;
        setStatus(nf ? `No data found for ${sym}.` : `${sym} positioning loaded.`);
      })
      .catch((e) => setStatus(`Ticker fetch failed: ${e.message}.`))
      .finally(() => {
        btn.removeAttribute("aria-busy");
        buttons.forEach((b) => (b.disabled = false));
      });
  }
  $("#btn-ticker").addEventListener("click", runTickerPositioning);
  $("#ticker-input").addEventListener("keydown",
    (e) => { if (e.key === "Enter") runTickerPositioning(); });

  // Keep relative timestamps fresh without re-fetching.
  setInterval(() => {
    document.querySelectorAll("[data-updated]").forEach((el) => {
      const title = el.title;
      if (title && title.startsWith("Last updated: ")) {
        const t = Date.parse(title.slice("Last updated: ".length)) / 1000;
        if (!isNaN(t)) el.textContent = relTime(t);
      }
    });
  }, 30000);
}

document.addEventListener("DOMContentLoaded", init);
