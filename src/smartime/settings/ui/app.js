// 順打輸入法 settings page. Talks to the local settings server (api.py).
(() => {
  "use strict";

  // ------------------------------------------------------------ API
  const token = new URLSearchParams(location.search).get("t") || "";
  async function api(method, path, body, raw) {
    const opts = { method, headers: { "X-SmartIME-Token": token } };
    if (raw !== undefined) {
      opts.body = raw;
      opts.headers["Content-Type"] = "application/octet-stream";
    } else if (body !== undefined) {
      opts.body = JSON.stringify(body);
      opts.headers["Content-Type"] = "application/json";
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      document.getElementById("offline").hidden = false;
      throw new Error("和輸入法的連線中斷了");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `錯誤 ${res.status}`);
    return data;
  }

  // ------------------------------------------------------------ toast
  const toastEl = document.getElementById("toast");
  let toastTimer = 0;
  function toast(msg, isError) {
    toastEl.textContent = msg;
    toastEl.className = "toast" + (isError ? " err" : "");
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, isError ? 5000 : 1800);
  }

  // ------------------------------------------------------------ navigation
  const rail = document.querySelectorAll("nav.rail button");
  const views = document.querySelectorAll("section.view");
  function show(id) {
    if (!document.getElementById("view-" + id)) id = "general";
    views.forEach(v => { v.hidden = v.id !== "view-" + id; });
    rail.forEach(b => b.setAttribute("aria-current", b.dataset.view === id ? "page" : "false"));
    try { localStorage.setItem("smartime-view", id); } catch (e) { /* storage may be blocked */ }
    if (id === "dict") loadEntries();
    if (id === "voice") loadVoice();
    if (id === "snippets") { loadSnippets(); loadCustomSymbols(); loadSymbolsExtra(); }
  }
  rail.forEach(b => b.addEventListener("click", () => show(b.dataset.view)));

  // ------------------------------------------------------------ state + config binding
  let state = null;
  let config = {};

  function setText(key, value) {
    document.querySelectorAll(`[data-text="${key}"]`).forEach(el => { el.textContent = value; });
  }

  function renderConfig() {
    document.querySelectorAll("[data-cfg]").forEach(el => {
      const key = el.dataset.cfg;
      const value = config[key];
      if (value === undefined) {
        // a setting this version of the IME does not have yet
        const row = el.closest(".row");
        if (row) row.classList.add("disabled");
        return;
      }
      if (el.matches("input[type=checkbox]")) el.checked = !!value;
      else if (el.matches("input, select")) el.value = String(value);
      else el.querySelectorAll("[data-value]").forEach(b =>
        b.setAttribute("aria-pressed", b.dataset.value === String(value) ? "true" : "false"));
    });
    document.querySelectorAll("[data-out]").forEach(el => { el.textContent = config[el.dataset.out]; });
    renderSuggestions();
    renderPunct();
    renderKeyboard();
    renderModeCycle();
  }

  // Shift cycle: config.mode_cycle is "auto,chinese,english" (kept in this order)
  const MODES = [["auto", "中英自動"], ["chinese", "注音"], ["english", "英文"], ["pinyin", "拼音"], ["cangjie", "倉頡"]];
  // 一般: one card per input method. The switch puts it in the Shift cycle,
  // 「開啟時」 makes it the starting mode, the card opens to its own settings.
  function renderModeCycle() {
    if (config.mode_cycle === undefined) return;
    const on = new Set(config.mode_cycle.split(","));
    document.querySelectorAll(".method").forEach(m => {
      const mode = m.dataset.mode;
      m.querySelector("[data-cycle]").checked = on.has(mode);
      const start = config.start_mode === mode;
      m.classList.toggle("off", !on.has(mode) && !start);
      const st = m.querySelector(".m-start");
      st.setAttribute("aria-pressed", start ? "true" : "false");
      st.textContent = start ? "開啟時 ✓" : "開啟時";
    });
    const names = Object.fromEntries(MODES);
    const order = MODES.map(m => m[0]).filter(m => on.has(m)).map(m => names[m]);
    const line = document.getElementById("cycle-order");
    if (line) line.textContent = config.shift_cycle === "two"
      ? "兩段：單按 Shift 在英文和上次用的中文模式之間切換。"
      : `現在單按 Shift 的順序：${order.join(" → ")}${order.length > 1 ? " → " + order[0] + " …" : ""}`;
  }
  document.querySelectorAll(".method").forEach(m => {
    const mode = m.dataset.mode;
    const cb = m.querySelector("[data-cycle]");
    cb.addEventListener("change", () => {
      const on = new Set(config.mode_cycle.split(","));
      if (cb.checked) on.add(mode); else on.delete(mode);
      const next = MODES.map(x => x[0]).filter(x => on.has(x));
      if (!next.length) { cb.checked = true; toast("至少要留一個模式", true); return; }
      save({ mode_cycle: next.join(",") });
    });
    m.querySelector(".m-start").addEventListener("click", () => save({ start_mode: mode }));
    const toggle = m.querySelector(".m-toggle");
    const body = m.querySelector(".m-body");
    toggle.addEventListener("click", () => {
      const open = body.hidden;
      body.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      try {
        const keep = new Set(JSON.parse(localStorage.getItem("smartime-open-methods") || "[]"));
        if (open) keep.add(mode); else keep.delete(mode);
        localStorage.setItem("smartime-open-methods", JSON.stringify([...keep]));
      } catch (e) { /* storage may be blocked */ }
    });
  });
  (function restoreOpenMethods() {
    let keep = ["auto"];
    try { keep = JSON.parse(localStorage.getItem("smartime-open-methods") || '["auto"]'); } catch (e) { /* default */ }
    document.querySelectorAll(".method").forEach(m => {
      const open = keep.includes(m.dataset.mode);
      m.querySelector(".m-body").hidden = !open;
      m.querySelector(".m-toggle").setAttribute("aria-expanded", open ? "true" : "false");
    });
  })();
  const cjRoots = document.getElementById("cj-roots");
  if (cjRoots) {
    "日月金木水火土竹戈十大中一弓人心手口尸廿山女田難卜重".split("").forEach((r, i) => {
      const cell = document.createElement("span");
      cell.innerHTML = `<kbd></kbd>`;
      cell.querySelector("kbd").textContent = String.fromCharCode(97 + i);
      cell.appendChild(document.createTextNode(r));
      cjRoots.appendChild(cell);
    });
  }

  let pending = {};
  let saveTimer = 0;
  function save(patch) {
    Object.assign(config, patch);
    Object.assign(pending, patch);
    renderConfig();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      const body = pending;
      pending = {};
      try {
        config = await api("POST", "/api/config", body);
        renderConfig();
        toast("已儲存，下一個按鍵就生效");
      } catch (e) {
        toast(e.message, true);
      }
    }, 250);
  }

  document.querySelectorAll("[data-cfg]").forEach(el => {
    const key = el.dataset.cfg;
    const typed = v => (el.dataset.type === "int" ? parseInt(v, 10) : v);
    if (el.matches("input[type=checkbox]")) {
      el.addEventListener("change", () => save({ [key]: el.checked }));
    } else if (el.matches("input[type=range]")) {
      el.addEventListener("input", () => save({ [key]: typed(el.value) }));
    } else if (el.matches("input, select")) {
      el.addEventListener("change", () => save({ [key]: typed(el.value) }));
    } else {
      el.addEventListener("click", e => {
        const b = e.target.closest("[data-value]");
        if (b) save({ [key]: b.dataset.value });
      });
    }
  });

  async function loadState() {
    state = await api("GET", "/api/state");
    config = state.config;
    setText("product", state.product);
    setText("version", state.version);
    setText("userDir", state.userDir);
    setText("debugPath", state.debugLog.path);
    document.title = `${state.product} 設定`;
    renderConfig();
    renderDebug();
    loadUpdate();
    renderCategories();
    renderShortcuts();
    for (const feature of ["correction_mode", "palette_hotkey"]) {
      const on = feature in config;
      const badge = document.getElementById(feature === "correction_mode" ? "badge-correction" : "badge-palette");
      if (badge && on) { badge.textContent = "已完成"; badge.className = "badge done"; }
    }
    document.getElementById("row-correction-toggle").hidden = !("correction_mode" in config);
  }

  // ------------------------------------------------------------ keyboard (大千)
  const KB = {
    dachen: [
      [["1","ㄅ"],["2","ㄉ"],["3","ˇ",1],["4","ˋ",1],["5","ㄓ"],["6","ˊ",1],["7","˙",1],["8","ㄚ"],["9","ㄞ"],["0","ㄢ"],["-","ㄦ"]],
      [["q","ㄆ"],["w","ㄊ"],["e","ㄍ"],["r","ㄐ"],["t","ㄔ"],["y","ㄗ"],["u","ㄧ"],["i","ㄛ"],["o","ㄟ"],["p","ㄣ"]],
      [["a","ㄇ"],["s","ㄋ"],["d","ㄎ"],["f","ㄑ"],["g","ㄕ"],["h","ㄘ"],["j","ㄨ"],["k","ㄜ"],["l","ㄠ"],[";","ㄤ"]],
      [["z","ㄈ"],["x","ㄌ"],["c","ㄏ"],["v","ㄒ"],["b","ㄖ"],["n","ㄙ"],["m","ㄩ"],[",","ㄝ"],[".","ㄡ"],["/","ㄥ"]],
    ],
    eten: [
      [["1","˙",1],["2","ˊ",1],["3","ˇ",1],["4","ˋ",1],["5",""],["6",""],["7","ㄑ"],["8","ㄢ"],["9","ㄣ"],["0","ㄤ"],["-","ㄥ"],["=","ㄦ"]],
      [["q","ㄟ"],["w","ㄝ"],["e","ㄧ"],["r","ㄜ"],["t","ㄊ"],["y","ㄡ"],["u","ㄩ"],["i","ㄞ"],["o","ㄛ"],["p","ㄆ"]],
      [["a","ㄚ"],["s","ㄙ"],["d","ㄉ"],["f","ㄈ"],["g","ㄐ"],["h","ㄏ"],["j","ㄖ"],["k","ㄎ"],["l","ㄌ"],[";","ㄗ"],["'","ㄘ"]],
      [["z","ㄠ"],["x","ㄨ"],["c","ㄒ"],["v","ㄍ"],["b","ㄅ"],["n","ㄋ"],["m","ㄇ"],[",","ㄓ"],[".","ㄔ"],["/","ㄕ"]],
    ],
  };
  function cap(k, z, cls) {
    const d = document.createElement("div");
    d.className = "kcap" + (cls ? " " + cls : "");
    const a = document.createElement("span"); a.className = "k"; a.textContent = k;
    const b = document.createElement("span"); b.className = "z"; b.textContent = z;
    d.append(a, b);
    return d;
  }
  const kb = document.getElementById("keyboard");
  let kbShown = "";
  function renderKeyboard() {
    const name = KB[config.layout] ? config.layout : "dachen";
    if (name === kbShown) return;
    kbShown = name;
    kb.innerHTML = "";
    KB[name].forEach(r => {
      const row = document.createElement("div"); row.className = "krow";
      r.forEach(([k, z, tone]) => row.appendChild(cap(k, z, tone ? "tone" : "")));
      kb.appendChild(row);
    });
    const spaceRow = document.createElement("div"); spaceRow.className = "krow space";
    spaceRow.appendChild(cap("space", "一聲", "tone wide"));
    kb.appendChild(spaceRow);
  }

  // ------------------------------------------------------------ previews
  const candList = document.getElementById("cand-list");
  [["mvp", "英文"], ["MVP", ""], ["Mvp", ""], ["勳", "ㄒㄩㄣ"], ["薰", ""], ["燻", ""], ["勛", ""], ["醺", ""], ["熏", ""]]
    .forEach(([t, tag], i) => {
      const li = document.createElement("li");
      if (i === 0) li.className = "sel";
      li.innerHTML = `<span class="n">${i + 1}</span><span></span><span class="tag"></span>`;
      li.children[1].textContent = t;
      li.children[2].textContent = tag;
      candList.appendChild(li);
    });
  function renderSuggestions() {
    const sugg = ["會", "會議", "心", "始", "車", "放", "門", "學", "口"];
    const k = config.suggestion_count || 1;
    const tip = document.getElementById("sugg-tip");
    tip.textContent = config.autocomplete === false ? "（接續建議已關閉）"
      : sugg.slice(0, k).map((s, i) => (i === 0 ? `${s} ⇥` : s)).join(" · ");
  }
  const kao = document.getElementById("kao-sample");
  ["(＾▽＾)", "(｡♥‿♥｡)", "(╥﹏╥)", "(╯°□°）╯︵ ┻━┻", "¯\\_(ツ)_/¯", "m(_ _)m", "ʕ•ᴥ•ʔ", "(ง •̀_•́)ง"].forEach(k => {
    const s = document.createElement("span"); s.textContent = k; kao.appendChild(s);
  });
  const pg = document.getElementById("palette-grid");
  [..."，。、；：？！…—「」『』（）《》“”αβγΔπΣ±×÷≠≤≥∞√→←↑↓℃㎡％"].slice(0, 27).forEach(c => {
    const s = document.createElement("span"); s.textContent = c; pg.appendChild(s);
  });

  // ------------------------------------------------------------ punctuation
  // One table: every symbol key and what it types alone, with Shift, with
  // Ctrl and with Ctrl+Shift (engine/punct.py). Style "keycap": alone/Shift
  // type what is printed on the key, Ctrl/Ctrl+Shift the Chinese
  // punctuation, so no two combinations type the same thing. Ctrl cells
  // can be changed one by one; cells typing the same as another cell of the
  // key are tinted, so duplicates are easy to spot.
  const STYLE_DESC = {
    keycap: "單按、Shift 打鍵帽上印的符號（Shift+, 是 <）；中文標點用 Ctrl（Ctrl+, 是 ，）。同一個鍵四種按法都不重複。",
    fullwidth: "以前的打法：Shift+, 也打 ，（和 Ctrl+, 一樣），鍵帽上的 < 要按 ↓ 換。",
    custom: "每個符號自己決定單按／Shift 打全形還是半形：點表格裡的「全／半」切換。",
  };
  function punctHalf() {
    const p = state.punct;
    if (config.punct_style === "keycap") return new Set(Object.keys(p.fullwidth));
    if (config.punct_style === "fullwidth") return new Set(['"']);
    return new Set([...(config.halfwidth_symbols || "")]);
  }
  function zhuyinOf(key) {
    const rows = KB[KB[config.layout] ? config.layout : "dachen"];
    for (const r of rows) for (const [k, z] of r) if (k === key) return z;
    if (key === " ") return "一聲";
    return "";
  }
  function renderPunct() {
    if (!state || !state.punct) return;
    const tbody = document.querySelector("#punct-grid tbody");
    const p = state.punct;
    const half = punctHalf();
    const custom = config.punct_style === "custom";
    const overrides = config.punct_overrides || {};
    document.getElementById("punct-style-desc").textContent = STYLE_DESC[config.punct_style] || "";
    tbody.innerHTML = "";
    p.keycaps.forEach(([lower, upper]) => {
      const tr = document.createElement("tr");
      const tdKey = document.createElement("td"); tdKey.className = "pk-key";
      const k = document.createElement("kbd"); k.textContent = lower === " " ? "␣" : lower;
      const up = document.createElement("span"); up.className = "pk-upper"; up.textContent = upper;
      tdKey.append(k, up);
      const outOf = ch => (ch in p.fullwidth && !half.has(ch)) ? p.fullwidth[ch] : ch;
      const zy = zhuyinOf(lower);
      const alone = zy ? "" : outOf(lower);
      const shift = outOf(upper);
      const ctrl = (`C+${lower}` in overrides) ? overrides[`C+${lower}`] : (p.ctrl[`C+${lower}`] || "");
      const ctrlS = (`CS+${lower}` in overrides) ? overrides[`CS+${lower}`] : (p.ctrl[`CS+${lower}`] || "");
      const outs = [alone, shift, ctrl, ctrlS];
      const dup = v => v && outs.filter(x => x === v).length > 1;

      function symbolCell(ch, out) {
        const td = document.createElement("td");
        const span = document.createElement("span"); span.className = "pk-out" + (dup(out) ? " dup" : "");
        span.textContent = out;
        td.appendChild(span);
        if (ch in p.fullwidth) {
          const alt = out === ch ? p.fullwidth[ch] : ch;
          if (custom) {
            const b = document.createElement("button"); b.type = "button"; b.className = "pk-toggle";
            b.textContent = out === ch ? "半" : "全";
            b.title = `改成 ${alt}`;
            b.addEventListener("click", () => {
              const h = new Set([...(config.halfwidth_symbols || "")]);
              if (h.has(ch)) h.delete(ch); else h.add(ch);
              save({ halfwidth_symbols: [...h].join("") });
            });
            td.appendChild(b);
          } else {
            const a = document.createElement("span"); a.className = "pk-alt"; a.textContent = `↓ ${alt}`;
            a.title = "選字框裡的另一種寬度";
            td.appendChild(a);
          }
        }
        return td;
      }
      function ctrlCell(combo, out) {
        const td = document.createElement("td");
        const inp = document.createElement("input"); inp.type = "text"; inp.maxLength = 2;
        inp.className = "pk-input" + (dup(out) ? " dup" : "");
        inp.value = out; inp.placeholder = "—";
        inp.setAttribute("aria-label", combo.replace("CS+", "Ctrl+Shift+").replace("C+", "Ctrl+"));
        inp.addEventListener("change", () => {
          const next = Object.assign({}, config.punct_overrides || {});
          const v = inp.value.trim();
          if (v === (p.ctrl[combo] || "")) delete next[combo]; else next[combo] = v;
          save({ punct_overrides: next });
        });
        td.appendChild(inp);
        if (combo in overrides) {
          const r = document.createElement("button"); r.type = "button"; r.className = "pk-reset"; r.textContent = "↺";
          r.title = `恢復預設（${p.ctrl[combo] || "交給程式"}）`;
          r.addEventListener("click", () => {
            const next = Object.assign({}, config.punct_overrides || {});
            delete next[combo];
            save({ punct_overrides: next });
          });
          td.appendChild(r);
        }
        return td;
      }
      let tdAlone;
      if (zy) {
        tdAlone = document.createElement("td");
        tdAlone.innerHTML = '<span class="pk-zy"></span>';
        tdAlone.firstChild.textContent = `注音 ${zy}`;
      } else {
        tdAlone = symbolCell(lower, alone);
      }
      tr.append(tdKey, tdAlone, symbolCell(upper, shift), ctrlCell(`C+${lower}`, ctrl), ctrlCell(`CS+${lower}`, ctrlS));
      tbody.appendChild(tr);
    });
  }

  // ------------------------------------------------------------ dictionary
  // Two areas: 自動收集 (what the IME learned from your choices and fixes,
  // not sorted yet) and 我的詞庫 (words with a category, yours to keep).
  // Giving an inbox word a category moves it over. Long lists scroll in a
  // fixed-height box and load 100 rows at a time.
  const DICT_PAGE = 100;
  const DICT_EXPLAIN = {
    inbox: "輸入法從你的選字、修正和 Tab 接續自動記下來的詞，還沒整理。給它一個分類，就會移到「我的詞庫」；用不到的直接刪掉。",
    mine: "你自己加的詞，和你分類過的詞。打字時排在最前面，候選窗標上綠色。",
    blocked: "在候選窗按 Delete 不想再看到的詞。按「還原」就會再出現在候選裡。",
  };
  const ORIGIN = { fix: ["修正", "plan"], pick: ["選字", "later"], tab: ["接續", "predict"] };
  let dictView = "inbox";
  let dictCat = "";
  let dictSort = "recent";
  let dictQuery = "";
  let dictRows = [];
  let dictTotal = 0;
  let dictLoading = false;
  let dictToken = 0;  // ignore answers to requests made before the view changed

  function ago(ts) {
    if (!ts) return "—";
    const s = Date.now() / 1000 - ts;
    if (s < 60) return "剛剛";
    if (s < 3600) return `${Math.floor(s / 60)} 分鐘前`;
    if (s < 86400) return `${Math.floor(s / 3600)} 小時前`;
    if (s < 86400 * 30) return `${Math.floor(s / 86400)} 天前`;
    const d = new Date(ts * 1000);
    return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
  }

  function renderCategories() {
    const chips = document.getElementById("cat-chips");
    const manage = document.getElementById("cat-manage");
    const select = document.getElementById("add-cat");
    const cats = state.categories;
    const s = state.stats;
    // the three areas, with their sizes
    document.querySelectorAll("#dict-tabs [data-dict]").forEach(b => {
      b.setAttribute("aria-pressed", b.dataset.dict === dictView ? "true" : "false");
      b.querySelector(".n").textContent = { inbox: s.inbox, mine: s.mine, blocked: s.blocked }[b.dataset.dict] ?? 0;
    });
    document.getElementById("dict-explain").textContent = DICT_EXPLAIN[dictView];
    // categories filter inside 我的詞庫
    chips.hidden = dictView !== "mine";
    chips.innerHTML = "";
    [["", "全部", s.mine], ...cats.map(c => [c.name, c.name, c.entries])].forEach(([value, label, n]) => {
      const b = document.createElement("button");
      b.className = "chip"; b.type = "button";
      b.textContent = label;
      if (n !== undefined) { const sp = document.createElement("span"); sp.className = "n"; sp.textContent = n; b.appendChild(sp); }
      b.setAttribute("aria-pressed", value === dictCat ? "true" : "false");
      b.addEventListener("click", () => { dictCat = value; renderCategories(); loadEntries(); });
      chips.appendChild(b);
    });
    document.querySelectorAll("#dict-sort [data-sort]").forEach(b =>
      b.setAttribute("aria-pressed", b.dataset.sort === dictSort ? "true" : "false"));
    const keep = select.value;
    select.innerHTML = "";
    cats.forEach(c => { const o = document.createElement("option"); o.textContent = c.name; select.appendChild(o); });
    if (keep && cats.some(c => c.name === keep)) select.value = keep;
    else if (cats.some(c => c.name === "朋友")) select.value = "朋友";

    manage.innerHTML = "";
    cats.forEach(c => {
      const wrap = document.createElement("span");
      wrap.className = "chip";
      wrap.textContent = `${c.name}（${c.entries}）`;
      const del = document.createElement("button");
      del.className = "btn small"; del.type = "button"; del.textContent = "刪除";
      del.style.marginLeft = "6px";
      del.addEventListener("click", async () => {
        try {
          await api("DELETE", `/api/categories/${c.id}`);
          toast(`已刪除分類「${c.name}」，裡面的詞保留`);
          if (dictCat === c.name) dictCat = "";
          await refreshState();
        } catch (e) { toast(e.message, true); }
      });
      wrap.appendChild(del);
      manage.appendChild(wrap);
    });
    document.getElementById("dict-stats").textContent = `自動收集 ${s.inbox} · 我的詞庫 ${s.mine} · 已封鎖 ${s.blocked}`;
    const kb = Math.max(1, Math.round((s.bytes || 0) / 1024));
    document.getElementById("memory-size").textContent =
      `自己加的 ${s.manual} 個詞、學到的 ${s.learned} 個、封鎖 ${s.blocked} 個，檔案約 ${kb >= 1024 ? (kb / 1024).toFixed(1) + " MB" : kb + " KB"}。`;
  }
  document.querySelectorAll("#dict-tabs [data-dict]").forEach(b => b.addEventListener("click", () => {
    dictView = b.dataset.dict; dictCat = ""; renderCategories(); loadEntries();
  }));
  document.querySelectorAll("#dict-sort [data-sort]").forEach(b => b.addEventListener("click", () => {
    dictSort = b.dataset.sort; renderCategories(); loadEntries();
  }));
  document.getElementById("tidy-memory").addEventListener("click", async () => {
    try {
      const r = await api("POST", "/api/memory/tidy");
      toast(r.removed ? `整理好了：清掉 ${r.removed} 個很久沒用的學習紀錄` : "整理好了：沒有需要清掉的紀錄");
      await refreshState();
    } catch (e) { toast(e.message, true); }
  });

  async function refreshState() {
    const fresh = await api("GET", "/api/state");
    state.categories = fresh.categories;
    state.stats = fresh.stats;
    renderCategories();
    await loadEntries();
  }

  const HEADS = {
    inbox: ["詞", "讀音", "怎麼來的", "用過", "最近", ""],
    mine: ["詞", "讀音", "分類", "用過", "最近", ""],
    blocked: ["詞", "讀音", "", "", "", ""],
  };

  async function loadEntries(more) {
    if (!state) return;
    if (more && (dictLoading || dictRows.length >= dictTotal)) return;
    const token = more ? dictToken : ++dictToken;
    dictLoading = true;
    const params = new URLSearchParams({ view: dictView, q: dictQuery, sort: dictSort, paged: "1",
      offset: more ? dictRows.length : 0, limit: DICT_PAGE });
    if (dictView === "mine" && dictCat) params.set("category", dictCat);
    let page;
    try { page = await api("GET", "/api/entries?" + params); }
    catch (e) { toast(e.message, true); dictLoading = false; return; }
    dictLoading = false;
    if (token !== dictToken) return;
    const body = document.getElementById("dict-body");
    if (!more) {
      dictRows = [];
      body.innerHTML = "";
      const head = document.getElementById("dict-head");
      head.innerHTML = "";
      HEADS[dictView].forEach((h, i) => {
        const th = document.createElement("th"); th.textContent = h;
        if (i === 3) th.style.textAlign = "right";
        head.appendChild(th);
      });
      document.getElementById("dict-scroll").scrollTop = 0;
    }
    dictTotal = page.total;
    dictRows = dictRows.concat(page.rows);
    page.rows.forEach(r => body.appendChild(entryRow(r)));
    if (!dictRows.length) {
      body.innerHTML = `<tr><td colspan="6" class="note empty">${dictQuery ? "找不到符合的詞。" :
        dictView === "blocked" ? "沒有封鎖的詞。在候選窗對不想再看到的詞按 Delete 就會出現在這裡。" :
        dictView === "inbox" ? "還沒有自動收集的詞。從候選窗選字、修正錯字或按 Tab 接受接續後，會出現在這裡。" :
        "這裡還沒有詞。用上面的表單加入第一個，或打字時按 Ctrl+D。"}</td></tr>`;
    }
    document.getElementById("dict-count").textContent = dictTotal ? `共 ${dictTotal} 個，顯示 ${dictRows.length} 個` : "";
    document.getElementById("dict-more").hidden = dictRows.length >= dictTotal;
  }
  document.getElementById("dict-scroll").addEventListener("scroll", e => {
    const el = e.target;
    if (el.scrollTop + el.clientHeight > el.scrollHeight - 120) loadEntries(true);
  });
  document.querySelector("#dict-more button").addEventListener("click", () => loadEntries(true));

  function categorySelect(r, placeholder) {
    const sel = document.createElement("select"); sel.className = "cat-select"; sel.setAttribute("aria-label", "分類");
    const none = document.createElement("option"); none.value = ""; none.textContent = placeholder; sel.appendChild(none);
    state.categories.forEach(c => { const o = document.createElement("option"); o.textContent = c.name; sel.appendChild(o); });
    sel.value = r.category || "";
    sel.addEventListener("change", async () => {
      if (!sel.value) return;
      try {
        await api("PATCH", `/api/entries/${r.id}`, { category: sel.value });
        toast(dictView === "inbox" ? `「${r.phrase}」加入「${sel.value}」，移到我的詞庫` : `「${r.phrase}」移到「${sel.value}」`);
        await refreshState();
      } catch (e) { toast(e.message, true); }
    });
    return sel;
  }

  function entryRow(r) {
    const tr = document.createElement("tr");
    const tdWord = document.createElement("td"); tdWord.className = "word"; tdWord.textContent = r.phrase; tdWord.title = r.phrase;
    const tdRead = document.createElement("td");
    const code = document.createElement("code"); code.textContent = r.kind === "en" ? "英文" : r.readingDisplay; tdRead.appendChild(code);
    const tdMid = document.createElement("td");
    const tdN = document.createElement("td"); tdN.className = "num";
    const tdWhen = document.createElement("td"); tdWhen.className = "when";
    const tdAct = document.createElement("td"); tdAct.className = "actions";
    if (dictView === "inbox") {
      const [label, cls] = ORIGIN[r.origin] || ["學到的", "later"];
      const b = document.createElement("span"); b.className = `badge ${cls}`; b.textContent = label;
      if (r.origin === "fix") b.title = "你在句子裡修正這個字時，連同前後文記成的詞";
      tdMid.appendChild(b);
    } else if (dictView === "mine") {
      tdMid.appendChild(categorySelect(r, "（未分類）"));
    }
    if (dictView !== "blocked") {
      tdN.textContent = r.count;
      tdWhen.textContent = ago(r.last_used || r.created);
    }
    if (dictView === "inbox") tdAct.appendChild(categorySelect(r, "加到分類…"));
    const btn = document.createElement("button"); btn.type = "button";
    if (dictView === "blocked") {
      btn.className = "btn small"; btn.textContent = "還原";
      btn.addEventListener("click", async () => {
        try { await api("PATCH", `/api/entries/${r.id}`, { blocked: false }); toast(`「${r.phrase}」會再出現在候選裡`); await refreshState(); }
        catch (e) { toast(e.message, true); }
      });
    } else {
      btn.className = "btn small danger"; btn.textContent = "刪除";
      btn.addEventListener("click", async () => {
        try { await api("DELETE", `/api/entries/${r.id}`); toast(`已刪除「${r.phrase}」`); await refreshState(); }
        catch (e) { toast(e.message, true); }
      });
    }
    tdAct.appendChild(btn);
    tr.append(tdWord, tdRead, tdMid, tdN, tdWhen, tdAct);
    return tr;
  }

  let searchTimer = 0;
  document.getElementById("dict-search").addEventListener("input", e => {
    dictQuery = e.target.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadEntries, 200);
  });

  // reading suggestion + 多音字 picker
  const wordEl = document.getElementById("add-word");
  const readingEl = document.getElementById("add-reading");
  const pick = document.getElementById("charpick");
  const addError = document.getElementById("add-error");
  let readingTimer = 0;
  let readingEdited = false;
  readingEl.addEventListener("input", () => { readingEdited = readingEl.value.trim() !== ""; });
  wordEl.addEventListener("input", () => {
    clearTimeout(readingTimer);
    readingTimer = setTimeout(suggestReading, 250);
  });
  async function suggestReading() {
    const text = wordEl.value.trim();
    pick.innerHTML = "";
    addError.hidden = true;
    if (!text) { if (!readingEdited) readingEl.value = ""; return; }
    let r;
    try { r = await api("POST", "/api/reading", { text }); } catch (e) { return; }
    if (r.kind === "en") { readingEl.value = ""; readingEl.placeholder = "英文詞不需要注音"; return; }
    readingEl.placeholder = "注音（留空會自動產生）";
    if (!readingEdited) readingEl.value = r.reading;
    const syllables = readingEl.value.split(/\s+/);
    r.chars.forEach((c, i) => {
      if (c.readings.length < 2) return;  // only 多音字 need a choice
      const box = document.createElement("span"); box.className = "ch";
      const b = document.createElement("b"); b.textContent = c.char; box.appendChild(b);
      c.readings.forEach(rd => {
        const btn = document.createElement("button"); btn.type = "button"; btn.textContent = rd;
        btn.setAttribute("aria-pressed", syllables[i] === rd ? "true" : "false");
        btn.addEventListener("click", () => {
          const parts = readingEl.value.split(/\s+/);
          parts[i] = rd;
          readingEl.value = parts.join(" ");
          readingEdited = true;
          box.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", x === btn ? "true" : "false"));
        });
        box.appendChild(btn);
      });
      pick.appendChild(box);
    });
  }
  document.getElementById("add-form").addEventListener("submit", async e => {
    e.preventDefault();
    addError.hidden = true;
    const phrase = wordEl.value.trim();
    if (!phrase) { wordEl.focus(); return; }
    try {
      await api("POST", "/api/entries", { phrase, reading: readingEl.value, category: document.getElementById("add-cat").value });
      toast(`已加入「${phrase}」`);
      wordEl.value = ""; readingEl.value = ""; readingEdited = false; pick.innerHTML = "";
      await refreshState();
      wordEl.focus();
    } catch (err) {
      addError.textContent = err.message;
      addError.hidden = false;
    }
  });
  document.getElementById("cat-form").addEventListener("submit", async e => {
    e.preventDefault();
    const input = document.getElementById("cat-name");
    const name = input.value.trim();
    if (!name) return;
    try { await api("POST", "/api/categories", { name }); input.value = ""; toast(`已新增分類「${name}」`); await refreshState(); }
    catch (err) { toast(err.message, true); }
  });

  // ------------------------------------------------------------ 片語 (snippets)
  // Saved texts typed with ;; + keyword, or from the symbol panel's 片語 tab.
  async function loadSnippets() {
    let rows;
    try { rows = await api("GET", "/api/snippets"); } catch (e) { toast(e.message, true); return; }
    const list = document.getElementById("snip-list");
    document.getElementById("snip-count").textContent = rows.length ? `${rows.length} 個` : "";
    list.innerHTML = "";
    if (!rows.length) {
      list.innerHTML = '<p class="note" style="margin:0">還沒有片語。上面加入第一個，例如常用的回覆、地址或簽名；之後打字時打 <kbd>;</kbd><kbd>;</kbd> 就能叫出來。</p>';
      return;
    }
    rows.forEach((r, i) => list.appendChild(snippetCard(r, i, rows.length)));
  }

  function snippetCard(r, i, n) {
    const card = document.createElement("div");
    card.className = "snip";
    const head = document.createElement("div"); head.className = "snip-head";
    const title = document.createElement("b"); title.textContent = r.title || r.body.split("\n")[0].slice(0, 30);
    head.appendChild(title);
    if (r.keyword) {
      const kw = document.createElement("code"); kw.className = "snip-key"; kw.textContent = `;;${r.keyword}`;
      kw.title = "打字時打這個就會叫出來"; head.appendChild(kw);
    }
    if (r.count) { const u = document.createElement("span"); u.className = "note"; u.textContent = `用過 ${r.count} 次`; head.appendChild(u); }
    const acts = document.createElement("span"); acts.className = "snip-acts";
    const mk = (label, cls, fn, disabled) => {
      const b = document.createElement("button"); b.type = "button"; b.className = "btn small" + (cls ? " " + cls : "");
      b.textContent = label; b.disabled = !!disabled; b.addEventListener("click", fn); acts.appendChild(b);
    };
    mk("↑", "", () => moveSnippet(r.id, -1), i === 0);
    mk("↓", "", () => moveSnippet(r.id, 1), i === n - 1);
    mk("編輯", "", () => card.replaceWith(snippetEditor(r)));
    mk("刪除", "danger", async () => {
      try { await api("DELETE", `/api/snippets/${r.id}`); toast("已刪除片語"); loadSnippets(); }
      catch (e) { toast(e.message, true); }
    });
    head.appendChild(acts);
    const body = document.createElement("div"); body.className = "snip-body"; body.textContent = r.body;
    card.append(head, body);
    return card;
  }

  function snippetEditor(r) {
    const form = document.createElement("form");
    form.className = "snip snipform editing";
    form.innerHTML = `<input type="text" aria-label="標題" placeholder="標題（可省略）">
      <input type="text" aria-label="關鍵字" placeholder="關鍵字">
      <textarea rows="3" aria-label="內容"></textarea>
      <div class="snip-edit-acts"><button class="btn primary small" type="submit">儲存</button>
      <button class="btn small" type="button">取消</button></div>`;
    const [t, k] = form.querySelectorAll("input");
    const body = form.querySelector("textarea");
    t.value = r.title; k.value = r.keyword; body.value = r.body;
    form.addEventListener("submit", async e => {
      e.preventDefault();
      try {
        await api("PATCH", `/api/snippets/${r.id}`, { title: t.value, keyword: k.value, body: body.value });
        toast("已儲存片語"); loadSnippets();
      } catch (err) { toast(err.message, true); }
    });
    form.querySelector("button[type=button]").addEventListener("click", loadSnippets);
    setTimeout(() => body.focus(), 0);
    return form;
  }

  async function moveSnippet(id, delta) {
    try { await api("PATCH", `/api/snippets/${id}`, { move: delta }); loadSnippets(); }
    catch (e) { toast(e.message, true); }
  }

  document.getElementById("snip-form").addEventListener("submit", async e => {
    e.preventDefault();
    const title = document.getElementById("snip-title");
    const key = document.getElementById("snip-key");
    const body = document.getElementById("snip-body");
    try {
      await api("POST", "/api/snippets", { title: title.value, keyword: key.value, body: body.value });
      toast("已加入片語");
      title.value = ""; key.value = ""; body.value = "";
      loadSnippets();
    } catch (err) { toast(err.message, true); }
  });

  // ------------------------------------------------------------ 我的符號 (custom symbols)
  // Pasted kaomoji/symbols the user collected elsewhere — one per line (see
  // UserDict.add_custom_symbols for why not whitespace: some kaomoji carry
  // their own internal spaces). Shown in the symbol panel's own tab,
  // reachable with :: : (or :::), most recently used first.
  async function loadCustomSymbols() {
    let rows;
    try { rows = await api("GET", "/api/custom-symbols"); } catch (e) { toast(e.message, true); return; }
    const list = document.getElementById("sym-list");
    document.getElementById("sym-count").textContent = rows.length ? `${rows.length} 個` : "";
    list.innerHTML = "";
    if (!rows.length) {
      list.innerHTML = '<p class="note" style="margin:0">還沒有：上面貼上第一批，一行一個。</p>';
      return;
    }
    rows.forEach(text => list.appendChild(symbolChip(text)));
  }

  function symbolChip(text) {
    const chip = document.createElement("span");
    chip.className = "sym-chip";
    const label = document.createElement("span");
    label.textContent = text;
    const del = document.createElement("button");
    del.type = "button"; del.textContent = "×"; del.setAttribute("aria-label", `刪除「${text}」`);
    del.addEventListener("click", async () => {
      try { await api("POST", "/api/custom-symbols/remove", { text }); loadCustomSymbols(); }
      catch (e) { toast(e.message, true); }
    });
    chip.append(label, del);
    return chip;
  }

  // ------------------------------------------------------------ 更多符號 (symbols_extra)
  // Not bundled with the app: the user downloads it from here, same shape as
  // the voice models below. _emoji_items merges it in only once both this
  // file exists *and* the toggle (symbols_extra_enabled, bound by the
  // generic [data-cfg] handling above) is on.
  let symxTimer = 0;
  async function loadSymbolsExtra() {
    let s;
    try { s = await api("GET", "/api/symbols-extra"); } catch (e) { return; }
    const job = s.job || {};
    const badge = document.getElementById("symx-status");
    const btn = document.getElementById("symx-download");
    const err = document.getElementById("symx-error");
    if (job.active) {
      const pct = job.total ? Math.floor(job.done * 100 / job.total) : 0;
      badge.className = "badge plan";
      badge.textContent = `下載中 ${pct}%`;
      btn.disabled = true;
      btn.textContent = "下載中…";
      err.hidden = true;
    } else {
      badge.className = "badge " + (s.installed ? "done" : "later");
      badge.textContent = s.installed ? `已下載 · ${s.count} 個符號` : "未下載";
      btn.disabled = false;
      btn.textContent = s.installed ? "重新下載" : "下載";
      err.hidden = !job.error;
      err.textContent = job.error ? "下載失敗：" + job.error : "";
    }
    clearTimeout(symxTimer);
    const visible = !document.getElementById("view-snippets").hidden;
    if (job.active) symxTimer = setTimeout(loadSymbolsExtra, 800);
    else if (visible) symxTimer = setTimeout(loadSymbolsExtra, 4000);
  }
  document.getElementById("symx-download").addEventListener("click", async () => {
    try { await api("POST", "/api/symbols-extra/download"); loadSymbolsExtra(); }
    catch (e) { toast(e.message, true); }
  });

  document.getElementById("sym-form").addEventListener("submit", async e => {
    e.preventDefault();
    const paste = document.getElementById("sym-paste");
    try {
      const r = await api("POST", "/api/custom-symbols", { block: paste.value });
      toast(r.added ? `加入了 ${r.added} 個` : "沒有新的（可能都已經加過了）");
      paste.value = "";
      loadCustomSymbols();
    } catch (err) { toast(err.message, true); }
  });

  // ------------------------------------------------------------ shortcuts
  function renderShortcuts() {
    const D = ["done", "已完成"], S = ["plan", "即將推出"];
    const corr = "correction_mode" in config ? D : S;
    const pal = "palette_hotkey" in config ? D : S;
    const more = "suggestion_count" in config ? D : S;
    const rows = [
      ["打字", "<kbd>␣</kbd> <kbd>6</kbd> <kbd>3</kbd> <kbd>4</kbd> <kbd>7</kbd>", "聲調鍵（一 ˊ ˇ ˋ ˙），把注音轉成中文", D],
      ["打字", "<kbd>Enter</kbd>", "送出整段", D],
      ["打字", "<kbd>Backspace</kbd>", "刪掉游標前看得到的一個字（還沒打聲調時刪一個鍵），連同緊貼著它被略過的雜鍵；其他字不變", D],
      ["打字", "<kbd>Ctrl</kbd>+<kbd>Z</kbd> <kbd>Ctrl</kbd>+<kbd>Y</kbd>", "組字中復原／重做（打字以一個字為一步）；沒在組字時交給程式", D],
      ["打字", "<kbd>Ctrl</kbd>+<kbd>V</kbd> 等其他快捷鍵、點滑鼠", "組字中：先把字送出，再交給程式（貼上不會插進組字中間）", D],
      ["打字", "<kbd>Tab</kbd>", "帶入接續建議", D],
      ["打字", "<kbd>Shift</kbd>+<kbd>Tab</kbd>", "打開完整接續清單；提示列上的 2 3 4 就是這裡的編號", more],
      ["打字", "<kbd>;</kbd><kbd>;</kbd>（＋關鍵字）", "叫出片語，先預覽，Enter 打出", D],
      ["打字", "<kbd>Ctrl</kbd>+<kbd>D</kbd>", "把游標前的中文加入我的詞庫", D],
      ["選字", "<kbd>↓</kbd> <kbd>↑</kbd>", "打開候選窗（游標前／後的字），選取停在目前的字", D],
      ["選字", "<kbd>1</kbd>–<kbd>9</kbd>", "直接選候選（上排或數字鍵盤，NumLock 開不開都可以）", D],
      ["選字", "<kbd>Tab</kbd> <kbd>Shift</kbd>+<kbd>Tab</kbd>", "只看某一組：我的詞庫、學過、詞庫、原始按鍵…", D],
      ["選字", "<kbd>←</kbd> <kbd>→</kbd>", "在上面那排分類籤之間走（只看我的詞庫、只看學過…）", D],
      ["選字", "<kbd>PageUp</kbd> <kbd>PageDown</kbd>", "翻頁", D],
      ["選字", "<kbd>Shift</kbd>+<kbd>→</kbd> <kbd>Shift</kbd>+<kbd>←</kbd>", "多欄：打開下一欄／收起", D],
      ["選字", "<kbd>Ctrl</kbd>+<kbd>D</kbd>", "把選中的候選加入詞庫", D],
      ["選字", "選字框裡按 <kbd>Delete</kbd>", "忘記這個詞的使用紀錄；沒學過的就不再建議", D],
      ["修正", "<kbd>Esc</kbd>", "進入修正模式（再按一次回到打字；連按 D D 清除整段）", corr],
      ["修正", "<kbd>h</kbd> <kbd>l</kbd> / <kbd>j</kbd> <kbd>k</kbd>", "移動 / 換成下一個、上一個候選", corr],
      ["修正", "聲調鍵（<kbd>空白</kbd> <kbd>6</kbd> <kbd>3</kbd> <kbd>4</kbd> <kbd>7</kbd>）", "改這個字的聲調：檢（ㄐㄧㄢˇ）按 4 變 ㄐㄧㄢˋ", corr],
      ["修正", "<kbd>R</kbd>", "重新判定這一段：清掉自己選過的記號讓解碼器重算（連按擴大範圍）", corr],
      ["修正", "<kbd>v</kbd> <kbd>x</kbd> <kbd>e</kbd> <kbd>r</kbd> <kbd>a</kbd> <kbd>u</kbd> <kbd>i</kbd>", "換檢視 / 刪 / 中⇄英（停在被略過的鍵上＝保留它） / 重打 / 加詞 / 復原 / 回到打字", corr],
      ["模式", "單按 <kbd>Shift</kbd>", "切換模式（上面設定左／右／兩邊；輪流哪些在「一般」）", D],
      ["模式", "系統匣圖示右鍵", "直接選任何模式、開啟設定", D],
      ["模式", "<kbd>Caps Lock</kbd>", "直接打英文大寫", D],
      ["標點", '<a href="#punct" data-goto="punct">見「標點與符號」</a>', "單按／Shift 打鍵帽上的符號，Ctrl／Ctrl+Shift 打中文標點", D],
      ["符號", "<kbd>:</kbd><kbd>:</kbd> 或熱鍵", "符號面板：標點、希臘字母、數學、箭頭、單位、片語、顏文字、我的符號、搜尋符號（<kbd>Tab</kbd> 換分頁）", pal],
      ["符號", "<kbd>:</kbd><kbd>:</kbd><kbd>:</kbd>（面板開著時再打一個 <kbd>:</kbd> 也一樣）", "直接跳到「搜尋符號」，打關鍵字（star、heart、星座……）即時篩選", D],
      ["符號", "「常用」分頁的 <kbd>⏎</kbd>", "送出目前的字，再打一個換行（Shift+Enter 傳不過去時用）", D],
      ["語音", "按住右 <kbd>Ctrl</kbd>", "說話，放開後打到游標位置（右 Ctrl＋其他鍵＝一般快捷鍵，不錄音）", D],
    ];
    const tbody = document.querySelector("#keys-table tbody");
    tbody.innerHTML = "";
    rows.forEach(([ctx, keys, what, [cls, label]]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td></td><td>${keys}</td><td></td><td><span class="badge ${cls}"></span></td>`;
      tr.children[0].textContent = ctx;
      tr.children[2].textContent = what;
      tr.querySelector(".badge").textContent = label;
      tbody.appendChild(tr);
    });
    document.querySelectorAll("#view-keys [data-goto], #view-snippets [data-goto]").forEach(a => a.addEventListener("click", e => {
      e.preventDefault();
      show(a.dataset.goto);
    }));
  }

  // ------------------------------------------------------------ voice
  let voiceTimer = 0;
  async function loadVoice() {
    let v;
    try { v = await api("GET", "/api/voice"); } catch (e) { return; }
    document.getElementById("voice-no-runtime").hidden = v.runtime && !(v.install && v.install.active);
    const inst = v.install || {};
    const instBtn = document.getElementById("voice-install");
    instBtn.disabled = !!inst.active;
    instBtn.textContent = inst.active ? "安裝中…" : "安裝語音元件";
    document.getElementById("voice-install-log").textContent =
      (inst.log || []).join("\n") + (inst.error ? "\n錯誤：" + inst.error : "");
    // what the service itself reports (voice-status.json): loading / ready / error, microphone
    const st = v.status || {};
    let text = "未開啟", cls = "later";
    if (!config.voice_enabled) { text = v.running ? "關閉中…" : "未開啟"; }
    else if (!v.running) { text = "啟動中…"; cls = "plan"; }
    else if (st.state === "ready") { text = `待命中 · ${st.engine}（${st.device === "cuda" ? "顯示卡" : "CPU"}）`; cls = "done"; }
    else if (st.state === "error") { text = "模型載入失敗"; cls = "warn"; }
    else { text = "載入模型中…"; cls = "plan"; }
    const badge = document.getElementById("voice-running");
    badge.className = "badge " + cls;
    badge.textContent = text;
    const warn = document.getElementById("voice-warn");
    const noMic = v.running && st.mic === "";
    warn.hidden = !(config.voice_enabled && v.running && (st.state === "error" || noMic));
    warn.textContent = st.state === "error" ? `模型載入失敗：${st.error}`
      : "找不到麥克風：請接上麥克風（藍牙耳機要先連上），或到 Windows 設定 > 系統 > 音效 選擇輸入裝置。";
    const body = document.getElementById("voice-models");
    body.innerHTML = "";
    const dl = v.download || {};
    Object.entries(v.models).forEach(([key, m]) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td><b></b></td><td class="note"></td><td class="num"></td><td class="actions"></td>`;
      tr.children[0].firstChild.textContent = m.name;
      tr.children[1].textContent = m.description;
      tr.children[2].textContent = (m.size / 1e6 >= 1000 ? (m.size / 1e9).toFixed(1) + " GB" : Math.round(m.size / 1e6) + " MB");
      const cell = tr.children[3];
      if (m.installed) {
        const ok = document.createElement("span"); ok.className = "badge done"; ok.textContent = "已安裝"; cell.appendChild(ok);
      } else if (dl.key === key && dl.active) {
        const pct = dl.total ? Math.floor(dl.done * 100 / dl.total) : 0;
        cell.textContent = `下載中 ${pct}%`;
      } else {
        const b = document.createElement("button"); b.type = "button"; b.className = "btn small primary"; b.textContent = "下載";
        b.addEventListener("click", async () => {
          try { await api("POST", "/api/voice/download", { key }); loadVoice(); } catch (e) { toast(e.message, true); }
        });
        cell.appendChild(b);
        if (dl.key === key && dl.error) { const e = document.createElement("div"); e.className = "error"; e.textContent = dl.error; cell.appendChild(e); }
      }
      body.appendChild(tr);
    });
    clearTimeout(voiceTimer);
    // keep the page current while it is open (turning voice on/off takes a few seconds)
    const visible = !document.getElementById("view-voice").hidden;
    if (dl.active || inst.active) voiceTimer = setTimeout(loadVoice, 1000);
    else if (visible) voiceTimer = setTimeout(loadVoice, 2000);
  }
  document.getElementById("voice-install").addEventListener("click", async () => {
    try { await api("POST", "/api/voice/install"); loadVoice(); } catch (e) { toast(e.message, true); }
  });
  document.querySelector('[data-cfg="voice_enabled"]').addEventListener("change", () => setTimeout(loadVoice, 800));

  // ------------------------------------------------------------ data
  document.getElementById("open-folder").addEventListener("click", async () => {
    try { await api("POST", "/api/open-folder"); } catch (e) { toast(e.message, true); }
  });
  document.getElementById("export-link").href = "/api/export?t=" + encodeURIComponent(token);
  document.getElementById("import-file").addEventListener("change", async e => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const withSettings = document.getElementById("import-settings").checked ? "1" : "0";
    try {
      const r = await api("POST", "/api/import?settings=" + withSettings, undefined, await file.arrayBuffer());
      // Say what was actually combined: the whole point is that nothing was
      // replaced, and with several machines' files it is worth seeing which
      // one brought what (and when a file was already imported before).
      const parts = [];
      if (r.words) parts.push(`${r.words} 個新的詞`);
      if (r.updated) parts.push(`${r.updated} 個詞合併次數`);
      if (r.snippets) parts.push(`${r.snippets} 則片語`);
      if (r.symbols) parts.push(`${r.symbols} 個符號`);
      if (r.categories) parts.push(`${r.categories} 個分類`);
      const what = parts.length ? parts.join("、") : "沒有新東西";
      const again = r.repeat ? "（這個檔案匯入過了，次數不再累加）" : "";
      toast(`已合併：${what}${again}${r.settingsApplied ? "，並套用設定" : ""}`);
      if (r.settingsApplied) { const s = await api("GET", "/api/state"); config = s.config; renderConfig(); }
      await refreshState();
    } catch (err) { toast(err.message, true); }
  });

  function confirmBox(boxId, question, action) {
    const box = document.getElementById(boxId);
    const original = box.innerHTML;
    box.innerHTML = "";
    box.className = "confirm";
    const q = document.createElement("span"); q.className = "note"; q.textContent = question;
    const yes = document.createElement("button"); yes.type = "button"; yes.className = "btn danger small"; yes.textContent = "確定";
    const no = document.createElement("button"); no.type = "button"; no.className = "btn small"; no.textContent = "取消";
    const restore = () => { box.innerHTML = original; box.className = ""; bindDanger(); };
    yes.addEventListener("click", async () => { await action(); restore(); });
    no.addEventListener("click", restore);
    box.append(q, yes, no);
  }
  function bindDanger() {
    const clear = document.getElementById("clear-learned");
    if (clear) clear.addEventListener("click", () => confirmBox("clear-box", "清除所有自動學到的紀錄？", async () => {
      try { const r = await api("POST", "/api/clear-learned"); toast(`已清除 ${r.removed} 個學到的詞`); await refreshState(); }
      catch (e) { toast(e.message, true); }
    }));
    const reset = document.getElementById("reset-config");
    if (reset) reset.addEventListener("click", () => confirmBox("reset-box", "所有設定恢復預設值？", async () => {
      try { config = await api("POST", "/api/config/reset"); renderConfig(); toast("設定已恢復預設值"); }
      catch (e) { toast(e.message, true); }
    }));
  }
  bindDanger();

  function renderDebug() {
    const on = state.debugLog.on;
    document.getElementById("debug-log").checked = on;
    document.getElementById("debug-badge").hidden = !on;
  }
  document.getElementById("debug-log").addEventListener("change", async e => {
    try {
      state.debugLog = await api("POST", "/api/debug-log", { on: e.target.checked });
      renderDebug();
      toast(state.debugLog.on ? "已開啟除錯紀錄（輸入法已重新啟動）" : "已關閉除錯紀錄（輸入法已重新啟動）");
    } catch (err) { toast(err.message, true); }
  });

  // ------------------------------------------------------------ updates
  function fmtSize(n) { return n ? (n / 1048576).toFixed(0) + " MB" : ""; }

  function renderUpdate(u) {
    const status = document.getElementById("update-status");
    const install = document.getElementById("update-install");
    install.hidden = !(u.newer && u.canInstall);
    if (u.job && u.job.active) {
      const pct = u.job.total ? Math.round(100 * u.job.done / u.job.total) : 0;
      status.textContent = `下載中… ${pct}%（${fmtSize(u.job.total)}）`;
      install.hidden = true;
      setTimeout(loadUpdate, 700);
      return;
    }
    if (u.job && u.job.error) { status.textContent = "下載失敗：" + u.job.error; return; }
    if (u.job && u.job.path) { status.textContent = "安裝檔已下載，請在安裝視窗繼續。"; return; }
    if (u.error && !u.latest) { status.textContent = "這次連不上 GitHub（離線也沒關係，輸入法照常用）。"; return; }
    if (!u.latest) { status.textContent = "尚未檢查。"; return; }
    if (u.newer) {
      status.textContent = `有新版本 ${u.latest}${u.size ? "（" + fmtSize(u.size) + "）" : ""}。`;
    } else {
      status.textContent = `已經是最新版本（GitHub 上也是 ${u.latest}）。`;
    }
  }

  async function loadUpdate(force) {
    try {
      renderUpdate(await api("GET", "/api/update" + (force ? "?force=1" : "")));
    } catch (e) { document.getElementById("update-status").textContent = e.message; }
  }
  document.getElementById("update-check").addEventListener("click", async () => {
    document.getElementById("update-status").textContent = "檢查中…";
    await loadUpdate(true);
  });
  document.getElementById("update-install").addEventListener("click", async () => {
    try {
      await api("POST", "/api/update/install");
      loadUpdate();
    } catch (e) { toast(e.message, true); }
  });

  // ------------------------------------------------------------ start
  setInterval(() => { api("GET", "/api/ping").catch(() => {}); }, 15000);
  loadState().then(() => {
    let start = location.hash.replace("#", "");
    if (!start) { try { start = localStorage.getItem("smartime-view") || "general"; } catch (e) { start = "general"; } }
    show(start);
  }).catch(e => toast(e.message, true));
})();
