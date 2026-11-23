/* HN AI Education Reader: coordinated views over a static snapshot. */
(async function () {
  "use strict";

  const GROUP_ORDER = ["detection", "cheating", "response"];
  const SHORT_GROUP = { detection: "Detectors", cheating: "Cheating", response: "Teacher response" };
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const fmt = d3.format(",");
  const fmtS = d3.format("+.2f");
  const parseDate = d3.utcParse("%Y-%m-%d");
  const tip = document.getElementById("tip");

  // ---------- load ----------
  const [itemsRaw, topics, meta, words] = await Promise.all([
    d3.json("data/items.json"), d3.json("data/topics.json"),
    d3.json("data/meta.json"), d3.json("data/words.json"),
  ]);
  const cols = itemsRaw.columns;
  const items = itemsRaw.rows.map((r) => {
    const o = {};
    cols.forEach((c, i) => (o[c] = r[i]));
    o.d = parseDate(o.date);
    return o;
  });
  const byId = new Map(items.map((o) => [o.id, o]));

  // Unmatched thread replies take their thread's groups for filtering.
  for (const o of items) {
    if (o.matched) o.g = o.groups;
    else {
      const root = o.thread != null ? byId.get(o.thread) : null;
      o.g = root ? root.groups : [];
    }
  }
  // Children lists for thread view.
  const children = new Map();
  for (const o of items) {
    if (o.parent == null) continue;
    if (!children.has(o.parent)) children.set(o.parent, []);
    children.get(o.parent).push(o.id);
  }
  // Word index: vocab[i] -> delta-encoded sorted item ids.
  const wordIndex = new Map(words.vocab.map((w, i) => [w, i]));
  function postings(w) {
    const i = wordIndex.get(w);
    if (i == null) return null;
    const out = new Set();
    let acc = 0;
    for (const d of words.postings[i]) { acc += d; out.add(acc); }
    return out;
  }

  // ---------- state ----------
  const state = {
    groups: new Set(GROUP_ORDER), type: "all", scope: "matched", q: "",
    qSet: null, qMissing: [], sent: "s", model: "nmf", torder: "n",
    dates: null, sRange: null, topic: null, sort: "new", page: 0,
    open: new Set(), seed: 1,
  };
  const PAGE = 25;

  function pass(o, skip) {
    if (state.type !== "all" && o.type !== state.type) return false;
    if (state.scope === "matched" && !o.matched) return false;
    if (!o.g.some((g) => state.groups.has(g))) return false;
    if (state.qSet && !state.qSet.has(o.id)) return false;
    if (skip !== "dates" && state.dates && (o.d < state.dates[0] || o.d >= state.dates[1])) return false;
    if (skip !== "sent" && state.sRange) {
      const s = o[state.sent];
      if (s < state.sRange[0] || s > state.sRange[1]) return false;
    }
    if (skip !== "topic" && state.topic != null && o[state.model] !== state.topic) return false;
    return true;
  }
  const filtered = (skip) => items.filter((o) => pass(o, skip));

  // ---------- header ----------
  document.getElementById("lede").textContent =
    `${fmt(meta.n_stories)} stories and ${fmt(meta.n_comments)} comments from Hacker News, ` +
    `${d3.utcFormat("%-d %b %Y")(parseDate(meta.window[0]))} – ${d3.utcFormat("%-d %b %Y")(parseDate(meta.window[1]))}, ` +
    `about AI detectors, cheating with AI, and how teachers are responding. Snapshot taken ${meta.snapshot}. ` +
    `Usernames removed; posts appear as short excerpts.`;

  // ---------- filter controls ----------
  const gWrap = document.getElementById("f-groups");
  for (const g of GROUP_ORDER) {
    const b = document.createElement("button");
    b.className = "chip"; b.setAttribute("aria-pressed", "true"); b.dataset.g = g;
    const dot = document.createElement("span");
    dot.className = "dot"; dot.style.background = `var(--g-${g})`;
    b.append(dot, document.createTextNode(meta.groups[g]));
    b.title = "Toggle this group";
    b.addEventListener("click", () => {
      if (state.groups.has(g)) state.groups.delete(g); else state.groups.add(g);
      if (state.groups.size === 0) GROUP_ORDER.forEach((x) => state.groups.add(x));
      gWrap.querySelectorAll(".chip").forEach((c) =>
        c.setAttribute("aria-pressed", state.groups.has(c.dataset.g)));
      update();
    });
    gWrap.append(b);
  }
  function seg(id, key, after) {
    const el = document.getElementById(id);
    el.querySelectorAll("button").forEach((b) =>
      b.addEventListener("click", () => {
        state[key] = b.dataset.v;
        el.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
        if (after) after();
        update();
      }));
  }
  seg("f-type", "type");
  seg("f-scope", "scope");
  seg("f-sent", "sent", () => { state.sRange = null; });
  seg("f-model", "model", () => { state.topic = null; });
  seg("f-torder", "torder");

  const qInput = document.getElementById("f-q");
  let qTimer;
  qInput.addEventListener("input", () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { setQuery(qInput.value); update(); }, 200);
  });
  // A word matches a post if the word index lists it for that post, or if it
  // appears in what the page already shows (the excerpt, and a story's
  // title). Short posts are not in the index, so they are searched this way.
  const TOKEN = /[a-z0-9][a-z0-9+#.'-]*[a-z0-9+#]|[a-z0-9]/g;
  for (const o of items) {
    const shown = (o.excerpt || "").replace(/ …$/, "") + (o.type === "story" ? " " + o.title : "");
    o.shownWords = new Set(shown.toLowerCase().match(TOKEN) || []);
  }
  function setQuery(q) {
    state.q = q.trim();
    const toks = state.q.toLowerCase().match(TOKEN) || [];
    state.qMissing = [];
    if (!toks.length) { state.qSet = null; return; }
    let set = null;
    for (const t of toks) {
      const p = postings(t) || new Set();
      for (const o of items) if (o.shownWords.has(t)) p.add(o.id);
      if (!p.size) state.qMissing.push(t);
      set = set ? new Set([...set].filter((x) => p.has(x))) : p;
    }
    state.qSet = set;
  }

  document.getElementById("f-sort").addEventListener("change", (e) => {
    state.sort = e.target.value; state.page = 0;
    document.getElementById("reshuffle").hidden = state.sort !== "random";
    renderReader();
  });
  document.getElementById("reshuffle").addEventListener("click", () => {
    state.seed++; state.page = 0; renderReader();
  });

  function renderActive() {
    const el = document.getElementById("f-active");
    el.replaceChildren();
    const add = (label, clear) => {
      const b = document.createElement("button");
      b.className = "chip"; b.textContent = label + "  ×";
      b.title = "Remove this filter";
      b.addEventListener("click", () => { clear(); update(); });
      el.append(b);
    };
    const f = d3.utcFormat("%-d %b %Y");
    if (state.dates) add(`${f(state.dates[0])} – ${f(d3.utcDay.offset(state.dates[1], -1))}`, () => (state.dates = null));
    if (state.sRange) add(`score ${fmtS(state.sRange[0])} to ${fmtS(state.sRange[1])}`, () => (state.sRange = null));
    if (state.topic != null) add(`${state.model.toUpperCase()} topic ${state.topic + 1}`, () => (state.topic = null));
  }

  // ---------- tooltip ----------
  function showTip(ev, rows) {
    tip.replaceChildren();
    for (const [v, k] of rows) {
      const line = document.createElement("div");
      const a = document.createElement("span"); a.className = "v"; a.textContent = v;
      const b = document.createElement("span"); b.className = "k"; b.textContent = k ? " " + k : "";
      line.append(a, b); tip.append(line);
    }
    tip.style.opacity = 1;
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + r.width > window.innerWidth - 8) x = ev.clientX - r.width - 14;
    if (y + r.height > window.innerHeight - 8) y = ev.clientY - r.height - 14;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  const hideTip = () => (tip.style.opacity = 0);

  // Draw charts at their on-screen width so text stays at its real size.
  function chartWidth(sel, max) {
    const w = document.querySelector(sel).clientWidth;
    return Math.max(280, Math.min(max, w || max));
  }

  // ---------- timeline ----------
  const weeks = d3.utcMonday.range(d3.utcMonday.floor(parseDate(meta.window[0])), parseDate(meta.window[1]));
  const tl = (() => {
    const W = chartWidth("#c-time", 1100), H = 220, m = { t: 10, r: 10, b: 26, l: 44 };
    const svg = d3.select("#c-time").append("svg").attr("viewBox", `0 0 ${W} ${H}`)
      .attr("role", "img").attr("aria-label", "Bar chart of items per week");
    const x = d3.scaleUtc().domain([weeks[0], d3.utcWeek.offset(weeks[weeks.length - 1], 1)]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().range([H - m.b, m.t]);
    const gGrid = svg.append("g").attr("class", "gridline").attr("transform", `translate(${m.l},0)`);
    const gBars = svg.append("g");
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`)
      .call(d3.axisBottom(x).ticks(d3.utcMonth.every(W < 700 ? 3 : 1)).tickFormat(d3.utcFormat("%b %y")).tickSizeOuter(0));
    const gY = svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`);
    const brush = d3.brushX().extent([[m.l, m.t], [W - m.r, H - m.b]])
      .on("end", (ev) => {
        if (!ev.sourceEvent) return;
        if (!ev.selection) { state.dates = null; }
        else {
          const [a, b] = ev.selection.map(x.invert);
          state.dates = [d3.utcMonday.round(a), d3.utcMonday.round(b)];
          if (+state.dates[0] === +state.dates[1]) state.dates[1] = d3.utcWeek.offset(state.dates[0], 1);
        }
        update();
      });
    const gBrush = svg.append("g").attr("class", "brush").call(brush);
    // Hover layer sits under the brush overlay; use brush overlay events.
    gBrush.select(".overlay")
      .on("pointermove.tip", (ev) => {
        const [px] = d3.pointer(ev);
        const wk = d3.utcMonday.floor(x.invert(px));
        const v = tl.counts.get(+wk) || 0;
        showTip(ev, [[fmt(v), "items"], [`week of ${d3.utcFormat("%-d %b %Y")(wk)}`, ""]]);
      })
      .on("pointerleave.tip", hideTip);
    return { svg, x, y, gBars, gY, gGrid, brush, gBrush, m, W, H, counts: new Map() };
  })();

  function renderTimeline() {
    const data = filtered("dates");
    const counts = d3.rollup(data, (v) => v.length, (o) => +d3.utcMonday.floor(o.d));
    tl.counts = counts;
    const rows = weeks.map((w) => ({ w, n: counts.get(+w) || 0 }));
    tl.y.domain([0, d3.max(rows, (r) => r.n) || 1]).nice();
    tl.gY.call(d3.axisLeft(tl.y).ticks(4).tickFormat(d3.format("~s")).tickSizeOuter(0));
    tl.gGrid.call(d3.axisLeft(tl.y).ticks(4).tickSize(-(tl.W - tl.m.l - tl.m.r)).tickFormat(""));
    const bw = tl.x(weeks[1]) - tl.x(weeks[0]) - 2;
    tl.gBars.selectAll("path").data(rows).join("path")
      .attr("fill", css("--accent"))
      .attr("class", (r) => state.dates && (r.w < state.dates[0] || r.w >= state.dates[1]) ? "dim" : null)
      .attr("d", (r) => barPath(tl.x(r.w) + 1, tl.y(r.n), bw, tl.y(0) - tl.y(r.n), 2));
    if (!state.dates) tl.gBrush.call(tl.brush.move, null);
    // table
    const t = document.getElementById("t-time");
    t.replaceChildren(table(["Week of", "Items"], rows.map((r) => [d3.utcFormat("%Y-%m-%d")(r.w), fmt(r.n)])));
  }

  // Bar with rounded top, square base.
  function barPath(x, y, w, h, r) {
    if (h <= 0) return "";
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }

  // ---------- sentiment ----------
  // 21 bins: 10 negative, exactly zero, 10 positive.
  const BINS = d3.range(21).map((i) => {
    if (i < 10) return { i, lo: -1 + i * 0.1, hi: -1 + (i + 1) * 0.1, label: `${(-1 + i * 0.1).toFixed(1)} to ${(-1 + (i + 1) * 0.1).toFixed(1)}` };
    if (i === 10) return { i, lo: 0, hi: 0, label: "exactly 0" };
    const k = i - 11;
    return { i, lo: k * 0.1, hi: (k + 1) * 0.1, label: `${(k * 0.1).toFixed(1)} to ${((k + 1) * 0.1).toFixed(1)}` };
  });
  function binOf(s) {
    if (s === 0) return 10;
    if (s < 0) return Math.min(9, Math.floor((s + 1) / 0.1));
    return 11 + Math.min(9, Math.floor(s / 0.1));
  }
  function binColor(i) {
    if (i === 10) return css("--zero");
    if (i < 10) return i < 3 ? css("--neg-3") : i < 7 ? css("--neg-2") : css("--neg-1");
    return i > 17 ? css("--pos-3") : i > 13 ? css("--pos-2") : css("--pos-1");
  }
  const sc = (() => {
    const W = chartWidth("#c-sent", 520), H = 220, m = { t: 10, r: 8, b: 30, l: 44 };
    const svg = d3.select("#c-sent").append("svg").attr("viewBox", `0 0 ${W} ${H}`)
      .attr("role", "img").attr("aria-label", "Histogram of sentiment scores");
    const x = d3.scaleBand().domain(d3.range(21)).range([m.l, W - m.r]).paddingInner(0.08);
    const y = d3.scaleLinear().range([H - m.b, m.t]);
    const gGrid = svg.append("g").attr("class", "gridline").attr("transform", `translate(${m.l},0)`);
    const gBars = svg.append("g");
    const gX = svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`);
    gX.call(d3.axisBottom(x).tickValues([0, 5, 10, 15, 20])
      .tickFormat((i) => ({ 0: "−1", 5: "−0.5", 10: "0", 15: "+0.5", 20: "+1" })[i]).tickSizeOuter(0));
    const gY = svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`);
    const brush = d3.brushX().extent([[m.l, m.t], [W - m.r, H - m.b]]).on("end", (ev) => {
      if (!ev.sourceEvent) return;
      if (!ev.selection) state.sRange = null;
      else {
        const idx = x.domain().filter((i) => {
          const c = x(i) + x.bandwidth() / 2;
          return c >= ev.selection[0] && c <= ev.selection[1];
        });
        if (!idx.length) state.sRange = null;
        else state.sRange = [BINS[idx[0]].lo, BINS[idx[idx.length - 1]].hi];
      }
      update();
    });
    const gBrush = svg.append("g").attr("class", "brush").call(brush);
    gBrush.select(".overlay").on("pointermove.tip", (ev) => {
      const [px] = d3.pointer(ev);
      const i = Math.max(0, Math.min(20, Math.floor((px - m.l) / x.step())));
      showTip(ev, [[fmt(sc.counts[i] || 0), "items"], [BINS[i].label, ""]]);
    }).on("pointerleave.tip", hideTip);
    return { svg, x, y, gBars, gY, gGrid, brush, gBrush, m, W, H, counts: [] };
  })();

  function renderSentiment() {
    const data = filtered("sent");
    const counts = new Array(21).fill(0);
    for (const o of data) counts[binOf(o[state.sent])]++;
    sc.counts = counts;
    sc.y.domain([0, d3.max(counts) || 1]).nice();
    sc.gY.call(d3.axisLeft(sc.y).ticks(4).tickFormat(d3.format("~s")).tickSizeOuter(0));
    sc.gGrid.call(d3.axisLeft(sc.y).ticks(4).tickSize(-(sc.W - sc.m.l - sc.m.r)).tickFormat(""));
    const inSel = (i) => !state.sRange || (i === 10 ? state.sRange[0] <= 0 && state.sRange[1] >= 0
      : BINS[i].lo >= state.sRange[0] - 1e-9 && BINS[i].hi <= state.sRange[1] + 1e-9);
    sc.gBars.selectAll("path").data(counts).join("path")
      .attr("fill", (_, i) => binColor(i))
      .attr("class", (_, i) => (inSel(i) ? null : "dim"))
      .attr("d", (n, i) => barPath(sc.x(i), sc.y(n), sc.x.bandwidth(), sc.y(0) - sc.y(n), 2));
    if (!state.sRange) sc.gBrush.call(sc.brush.move, null);
    const zero = counts[10], tot = data.length || 1;
    document.getElementById("sent-note").textContent =
      `${d3.format(".0%")(zero / tot)} of these items score exactly 0. ` +
      (state.sent === "s_tn"
        ? `Topic-neutral: ${meta.topic_neutral_words.length} words about the subject itself (cheating, ban, fail, integrity…) count as 0.`
        : `Stock lexicon: words like “cheating” (−2.6) and “ban” (−2.6) count as negative even when only naming the subject.`);
    document.getElementById("t-sent").replaceChildren(
      table(["Score", "Items"], BINS.map((b, i) => [b.label, fmt(counts[i])])));
  }

  // ---------- sentiment by group (small multiples) ----------
  function renderGroups() {
    const data = filtered("sent");
    const el = d3.select("#c-groups");
    el.selectAll("*").remove();
    const W = chartWidth("#c-groups", 520), rowH = 62, m = { l: W < 420 ? 110 : 140, r: 8, t: 4 };
    const shown = GROUP_ORDER.filter((g) => state.groups.has(g));
    const H = shown.length * rowH + 26;
    const svg = el.append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("role", "img")
      .attr("aria-label", "Sentiment histograms by group, as share of each group");
    const x = d3.scaleBand().domain(d3.range(21)).range([m.l, W - m.r]).paddingInner(0.08);
    const per = shown.map((g) => {
      const sub = data.filter((o) => o.g.includes(g));
      const c = new Array(21).fill(0);
      for (const o of sub) c[binOf(o[state.sent])]++;
      return { g, n: sub.length, share: c.map((v) => (sub.length ? v / sub.length : 0)) };
    });
    const maxShare = d3.max(per, (p) => d3.max(p.share)) || 1;
    per.forEach((p, r) => {
      const y0 = m.t + r * rowH, h = rowH - 18;
      const y = d3.scaleLinear().domain([0, maxShare]).range([y0 + h, y0]);
      const g = svg.append("g");
      g.append("circle").attr("cx", 8).attr("cy", y0 + h / 2 - 6).attr("r", 4.5).attr("fill", css(`--g-${p.g}`));
      g.append("text").attr("x", 18).attr("y", y0 + h / 2 - 2).attr("fill", css("--ink")).attr("font-size", 12)
        .text(W < 420 ? SHORT_GROUP[p.g] : meta.groups[p.g].replace(/\s*\(.*\)/, ""));
      g.append("text").attr("x", 18).attr("y", y0 + h / 2 + 13).attr("fill", css("--muted")).attr("font-size", 11)
        .text(`${fmt(p.n)} items`);
      g.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y0 + h + 0.5).attr("y2", y0 + h + 0.5).attr("stroke", css("--axis"));
      g.selectAll("path").data(p.share).join("path")
        .attr("fill", (_, i) => binColor(i))
        .attr("d", (v, i) => barPath(x(i), y(v), x.bandwidth(), y(0) - y(v), 1.5));
      g.selectAll("rect.hit").data(p.share).join("rect").attr("class", "hit")
        .attr("x", (_, i) => x(i) - 1).attr("width", x.step()).attr("y", y0).attr("height", h)
        .attr("fill", "transparent")
        .on("pointermove", (ev) => {
          const idx = Math.round((d3.pointer(ev, svg.node())[0] - m.l) / x.step() - 0.5);
          const k = Math.max(0, Math.min(20, idx));
          showTip(ev, [[d3.format(".1%")(p.share[k]), `of ${meta.groups[p.g].replace(/\s*\(.*\)/, "")}`], [BINS[k].label, ""]]);
        })
        .on("pointerleave", hideTip);
    });
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - 20})`)
      .call(d3.axisBottom(x).tickValues([0, 5, 10, 15, 20])
        .tickFormat((i) => ({ 0: "−1", 5: "−0.5", 10: "0", 15: "+0.5", 20: "+1" })[i]).tickSize(0).tickPadding(6))
      .call((a) => a.select(".domain").remove());
    const f = d3.format(".1%");
    document.getElementById("t-groups").replaceChildren(table(
      ["Group", "Items", "< 0", "= 0", "> 0"],
      per.map((p) => [meta.groups[p.g], fmt(p.n), f(d3.sum(p.share.slice(0, 10))), f(p.share[10]), f(d3.sum(p.share.slice(11)))])));
  }

  // ---------- topics ----------
  function renderTopics() {
    const model = topics[state.model];
    const data = filtered("topic");
    const counts = d3.rollup(data, (v) => v.length, (o) => o[state.model]);
    const sentBy = d3.group(data, (o) => o[state.model]);
    const maxN = d3.max(model.topics, (t) => counts.get(t.id) || 0) || 1;
    const none = counts.get(null) || 0;
    document.getElementById("topic-note").textContent =
      `${model.k} topics (k chosen by coherence) · ${fmt(none)} filtered items too short for a topic`;
    const list = model.topics.slice().sort((a, b) =>
      state.torder === "n" ? (counts.get(b.id) || 0) - (counts.get(a.id) || 0) : a.id - b.id);
    const wrap = document.getElementById("c-topics");
    wrap.replaceChildren();
    for (const t of list) {
      const n = counts.get(t.id) || 0;
      const b = document.createElement("button");
      b.className = "topic";
      b.setAttribute("aria-pressed", state.topic === t.id);
      if (state.topic != null && state.topic !== t.id) b.classList.add("dim");
      const head = document.createElement("div"); head.className = "head";
      const h1 = document.createElement("span"); h1.textContent = `Topic ${t.id + 1}`;
      const h2 = document.createElement("span"); h2.textContent = `${fmt(n)} items`;
      head.append(h1, h2);
      const terms = document.createElement("div"); terms.className = "terms";
      t.terms.slice(0, 8).forEach(([w, wt], i) => {
        const s = document.createElement("span");
        s.textContent = w + (i < 7 ? "," : "");
        s.style.fontWeight = wt > 0.6 ? 650 : wt > 0.35 ? 500 : 400;
        s.style.color = wt > 0.35 ? "var(--ink)" : "var(--ink-2)";
        terms.append(s, document.createTextNode(" "));
      });
      const bar = document.createElement("div"); bar.className = "bar";
      const fill = document.createElement("i"); fill.style.width = `${(100 * n) / maxN}%`;
      bar.append(fill);
      // mini sentiment distribution
      const c = new Array(21).fill(0);
      for (const o of sentBy.get(t.id) || []) c[binOf(o[state.sent])]++;
      const mx = d3.max(c) || 1;
      const svg = d3.create("svg").attr("viewBox", "0 0 210 22").attr("preserveAspectRatio", "none")
        .attr("aria-hidden", "true");
      svg.selectAll("rect").data(c).join("rect")
        .attr("x", (_, i) => i * 10).attr("width", 8.5)
        .attr("y", (v) => 22 - (20 * v) / mx).attr("height", (v) => (20 * v) / mx)
        .attr("fill", (_, i) => binColor(i));
      const cap = document.createElement("div"); cap.className = "hint";
      cap.textContent = "sentiment spread, −1 to +1";
      b.append(head, terms, bar, svg.node(), cap);
      b.title = "Top terms: " + t.terms.map((x) => x[0]).join(", ");
      b.addEventListener("click", () => {
        state.topic = state.topic === t.id ? null : t.id;
        update();
      });
      wrap.append(b);
    }
  }

  // ---------- reader ----------
  function rng(seed) {
    let s = seed >>> 0;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }
  function topicLabel(o) {
    const t = o[state.model];
    if (t == null) return null;
    const tt = topics[state.model].topics[t];
    return `Topic ${t + 1}: ${tt.terms.slice(0, 3).map((x) => x[0]).join(", ")}`;
  }
  function scoreEl(o) {
    const s = document.createElement("span"); s.className = "score";
    const sw = document.createElement("span"); sw.className = "sw";
    sw.style.background = binColor(binOf(o[state.sent]));
    const v = document.createElement("span");
    v.textContent = `score ${fmtS(o[state.sent])}` +
      (state.sent === "s" ? ` (topic-neutral ${fmtS(o.s_tn)})` : ` (stock ${fmtS(o.s)})`);
    s.append(sw, v);
    return s;
  }
  function itemEl(o, compact) {
    const li = document.createElement(compact ? "div" : "li");
    li.className = compact ? "titem" : "item";
    const meta1 = document.createElement("div"); meta1.className = "meta";
    const add = (txt) => { const s = document.createElement("span"); s.textContent = txt; meta1.append(s); return s; };
    add(d3.utcFormat("%-d %b %Y")(o.d));
    add(o.type === "story" ? `Story${o.points != null ? ` · ${o.points} points` : ""}` :
      o.source === "standalone" ? "Comment (thread not collected)" : `Comment · reply depth ${o.depth}`);
    if (!o.matched) add("not keyword-matched");
    for (const g of o.matched ? o.groups : []) {
      const s = document.createElement("span"); s.className = "g";
      const d = document.createElement("span"); d.className = "dot"; d.style.background = `var(--g-${g})`;
      s.append(d, document.createTextNode(meta.groups[g].replace(/\s*\(.*\)/, "")));
      meta1.append(s);
    }
    const tl = topicLabel(o);
    if (tl && !compact) add(tl);
    li.append(meta1);
    if (!compact) {
      const ctx = document.createElement("div"); ctx.className = "ctx";
      if (o.type === "story") { const b = document.createElement("b"); b.textContent = o.title; ctx.append(b); }
      else if (o.title) ctx.append(document.createTextNode("In thread: "), Object.assign(document.createElement("b"), { textContent: o.title }));
      li.append(ctx);
    } else if (o.type === "story") {
      const b = document.createElement("div"); b.className = "ctx";
      b.append(Object.assign(document.createElement("b"), { textContent: o.title })); li.append(b);
    }
    if (o.excerpt) {
      const p = document.createElement("p"); p.className = "excerpt"; p.textContent = o.excerpt;
      li.append(p);
    }
    const foot = document.createElement("div"); foot.className = "foot";
    foot.append(scoreEl(o));
    if (o.lex && o.lex.length) {
      const lw = document.createElement("span"); lw.className = "lexw";
      lw.textContent = "lexicon words: " + o.lex.map(([w, v]) => `${w} ${v > 0 ? "+" : ""}${v}`).join(", ");
      lw.title = "Sentiment-bearing words VADER found in the full post (before negation and intensity rules).";
      foot.append(lw);
    }
    if (!compact && o.thread != null) {
      const size = threadSize(o.thread);
      if (size > 1) {
        const btn = document.createElement("button"); btn.className = "linkbtn";
        const open = state.open.has(o.id);
        btn.textContent = open ? "Hide thread" : `Show thread (${fmt(size)} items)`;
        btn.setAttribute("aria-expanded", open);
        btn.addEventListener("click", () => {
          if (state.open.has(o.id)) state.open.delete(o.id); else state.open.add(o.id);
          renderReader(true);
        });
        foot.append(btn);
      }
    }
    li.append(foot);
    if (!compact && state.open.has(o.id)) li.append(threadEl(o));
    return li;
  }
  const tsCache = new Map();
  function threadSize(root) {
    if (tsCache.has(root)) return tsCache.get(root);
    let n = 0; const st = [root];
    while (st.length) { const id = st.pop(); if (!byId.has(id)) continue; n++; for (const c of children.get(id) || []) st.push(c); }
    tsCache.set(root, n); return n;
  }
  function threadEl(o) {
    const box = document.createElement("div"); box.className = "thread";
    const order = [];
    (function walk(id) {
      if (byId.has(id)) order.push(byId.get(id));
      for (const c of children.get(id) || []) walk(c);
    })(o.thread);
    // Show a window around the selected item.
    const at = order.findIndex((x) => x.id === o.id);
    const lo = Math.max(0, at - 20), hi = Math.min(order.length, at + 40);
    if (lo > 0) box.append(Object.assign(document.createElement("div"), { className: "hint", textContent: `${lo} earlier items not shown` }));
    for (const x of order.slice(lo, hi)) {
      const el = itemEl(x, true);
      el.style.marginLeft = `${Math.min(x.depth || 0, 8) * 14}px`;
      if (x.id === o.id) el.classList.add("self");
      box.append(el);
    }
    if (hi < order.length) box.append(Object.assign(document.createElement("div"), { className: "hint", textContent: `${order.length - hi} later items not shown` }));
    return box;
  }

  function renderReader(keepScroll) {
    let data = filtered();
    if (state.sort === "points") data = data.filter((o) => o.type === "story");
    const k = state.sent;
    const sorters = {
      new: (a, b) => b.d - a.d || b.id - a.id,
      old: (a, b) => a.d - b.d || a.id - b.id,
      neg: (a, b) => a[k] - b[k],
      pos: (a, b) => b[k] - a[k],
      points: (a, b) => (b.points || 0) - (a.points || 0),
    };
    if (state.sort === "random") {
      const r = rng(state.seed);
      data = data.map((o) => [r(), o]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
    } else data = data.slice().sort(sorters[state.sort]);
    const pages = Math.max(1, Math.ceil(data.length / PAGE));
    state.page = Math.min(state.page, pages - 1);
    const list = document.getElementById("items");
    list.replaceChildren();
    if (!data.length) {
      list.append(Object.assign(document.createElement("li"), { className: "empty", textContent: "No items match these filters." }));
    }
    for (const o of data.slice(state.page * PAGE, (state.page + 1) * PAGE)) list.append(itemEl(o));
    const pager = document.getElementById("pager");
    pager.replaceChildren();
    if (data.length > PAGE) {
      const prev = Object.assign(document.createElement("button"), { textContent: "← Previous", disabled: state.page === 0 });
      const next = Object.assign(document.createElement("button"), { textContent: "Next →", disabled: state.page >= pages - 1 });
      const lbl = Object.assign(document.createElement("span"), { textContent: `Page ${state.page + 1} of ${fmt(pages)}` });
      prev.onclick = () => { state.page--; renderReader(); document.getElementById("reader").scrollIntoView(); };
      next.onclick = () => { state.page++; renderReader(); document.getElementById("reader").scrollIntoView(); };
      pager.append(prev, lbl, next);
    }
  }

  function renderCount() {
    const n = filtered().length;
    const el = document.getElementById("count-line");
    el.replaceChildren(Object.assign(document.createElement("strong"), { textContent: fmt(n) }),
      document.createTextNode(` of ${fmt(items.length)} items`));
    if (state.qMissing.length) el.append(document.createTextNode(` · no posts contain: ${state.qMissing.join(", ")}`));
  }

  function table(head, rows) {
    const t = document.createElement("table");
    const tr = t.insertRow();
    head.forEach((h) => { const th = document.createElement("th"); th.textContent = h; tr.append(th); });
    rows.forEach((r) => { const row = t.insertRow(); r.forEach((c) => (row.insertCell().textContent = c)); });
    return t;
  }

  function update() {
    state.page = 0;
    renderActive(); renderCount(); renderTimeline(); renderSentiment(); renderGroups(); renderTopics(); renderReader();
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", update);
  update();
})().catch((e) => {
  document.getElementById("lede").textContent = "Could not load the data: " + e.message;
  console.error(e);
});
