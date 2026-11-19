"use strict";
/* ============================================================
   Nocturne — stats en direct sur le résumé vidéo (prototype)
   Le site ne peut pas lire l'image d'un lecteur YouTube intégré.
   Avec l'accord du visiteur (partage de l'onglet, comme en visio),
   on lit le bandeau du match à l'écran (quart-temps + chrono) avec
   tesseract.js, puis on recalcule les stats ESPN jusqu'à ce moment.
   Rien ne sort du navigateur. Sans spoil : jamais au-delà de l'écran.
   ============================================================ */
const Chrono = (() => {
  const CAN = (DEMO && QS.has("live")) || !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia) && !/Android|iPhone|iPad|Mobile/i.test(navigator.userAgent); // les téléphones ne savent pas partager un onglet
  const TESS = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";
  let S = null; // session en cours (un match, un lecteur)

  /* ---------- le déroulé ESPN, réduit à ce qui sert ---------- */
  const secOf = d => { // « 11:12 » → 672 ; « 45.3 » → 45.3
    let m = /^(\d+):(\d+)/.exec(d || ""); if (m) return +m[1] * 60 + +m[2];
    m = /^(\d+(?:\.\d)?)$/.exec(d || ""); return m ? +m[1] : 0;
  };
  function parsePlays(j) {
    const names = {};
    try {
      for (const side of j.boxscore.players || []) for (const a of side.statistics[0].athletes || [])
        if (a.athlete) names[String(a.athlete.id)] = { n: a.athlete.shortName || a.athlete.displayName, t: +side.team.id };
    } catch (e) { /* pas de feuille */ }
    let ids = {};
    try { for (const c of j.header.competitions[0].competitors) ids[c.homeAway] = +c.team.id; } catch (e) { /* */ }
    const plays = (j.plays || []).map(p => {
      const tt = (p.type && p.type.text) || "", tx = p.text || "";
      const pa = (p.participants || []).map(x => x.athlete ? String(x.athlete.id) : "");
      return {
        per: p.period ? p.period.number : 1, sec: secOf(p.clock && p.clock.displayValue),
        clk: p.clock ? p.clock.displayValue : "", tid: p.team ? +p.team.id : 0,
        hs: +p.homeScore || 0, as: +p.awayScore || 0, tx, tt,
        shoot: !!p.shootingPlay, made: !!p.scoringPlay,
        ft: /free throw/i.test(tt), three: p.pointsAttempted ? p.pointsAttempted === 3 : /three point/i.test(tx),
        a0: pa[0] || "", a1: pa[1] || "", ast: /assists?\)/i.test(tx), stl: /steals?\)/i.test(tx),
      };
    });
    return { names, plays, home: ids.home, away: ids.away };
  }

  /* ---------- démo : un faux déroulé plausible ---------- */
  function demoPlays(sum, g) {
    let seed = 7; for (const c of g.id) seed = (seed * 31 + c.charCodeAt(0)) % 99991;
    const r = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const names = {}; for (const p of sum.players) names[p.aid] = { n: p.name, t: p.tid };
    const home = g.teams.home.id, away = g.teams.away.id;
    const roster = t => sum.players.filter(p => p.tid === t);
    const plays = []; let hs = 0, as = 0;
    const nq = sum.ot ? 5 : 4;
    for (let per = 1; per <= nq; per++) {
      let sec = per <= 4 ? 720 : 300, side = per % 2 ? away : home;
      while ((sec -= 8 + Math.floor(r() * 22)) > 0) {
        const ro = roster(side), sh = ro[Math.floor(r() * r() * ro.length)];
        const three = r() < .36, made = r() < (three ? .37 : .52), val = three ? 3 : 2;
        const mm = Math.floor(sec / 60), ss = String(Math.floor(sec % 60)).padStart(2, "0"), clk = sec >= 60 ? `${mm}:${ss}` : (sec % 60).toFixed(1);
        let a1 = "", ast = false;
        if (made) { if (side === home) hs += val; else as += val; if (r() < .6) { const o = ro.filter(p => p !== sh); a1 = o[Math.floor(r() * o.length)].aid; ast = true; } }
        plays.push({ per, sec, clk, tid: side, hs, as, tt: "Shot", tx: `${sh.name} ${made ? "makes" : "misses"} ${three ? "three point jumper" : "driving layup"}${ast ? ` (${names[a1].n} assists)` : ""}`,
          shoot: true, made, ft: false, three, a0: sh.aid, a1, ast, stl: false });
        if (!made) { const t2 = r() < .73 ? (side === home ? away : home) : side; const rb = roster(t2)[Math.floor(r() * 4)];
          plays.push({ per, sec, clk, tid: t2, hs, as, tt: (t2 === side ? "Offensive" : "Defensive") + " Rebound", tx: `${rb.name} ${t2 === side ? "offensive" : "defensive"} rebound`, shoot: false, made: false, ft: false, three: false, a0: rb.aid, a1: "", ast: false, stl: false });
          side = t2; }
        else side = side === home ? away : home;
        if (r() < .08) { plays.push({ per, sec, clk, tid: side, hs, as, tt: "Bad Pass Turnover", tx: `${roster(side)[0].name} bad pass (turnover)`, shoot: false, made: false, ft: false, three: false, a0: roster(side)[0].aid, a1: "", ast: false, stl: false }); side = side === home ? away : home; }
      }
    }
    return { names, plays, home, away };
  }

  /* ---------- les stats jusqu'au moment affiché ---------- */
  function statsAt(D, per, sec) {
    const T = {}; const P = {};
    for (const t of [D.home, D.away]) T[t] = { fg: 0, fga: 0, tp: 0, tpa: 0, ftm: 0, fta: 0, reb: 0, ast: 0, to: 0, pf: 0 };
    let hs = 0, as = 0, last = [];
    const pl = id => P[id] || (P[id] = { pts: 0, reb: 0, ast: 0, fg: 0, fga: 0 });
    for (const p of D.plays) {
      if (p.per > per || (p.per === per && p.sec < sec)) break;
      hs = p.hs; as = p.as;
      const t = T[p.tid];
      if (!t) continue;
      if (p.shoot) {
        if (p.ft) { t.fta++; if (p.made) t.ftm++; }
        else { t.fga++; if (p.made) t.fg++; if (p.three) { t.tpa++; if (p.made) t.tp++; } }
        if (p.a0) { const q = pl(p.a0); if (!p.ft) { q.fga++; if (p.made) q.fg++; } if (p.made) q.pts += p.ft ? 1 : p.three ? 3 : 2; }
        if (p.made && p.ast && p.a1) { pl(p.a1).ast++; t.ast++; }
      } else if (/rebound/i.test(p.tt)) { if (p.a0) { t.reb++; pl(p.a0).reb++; } } // rebonds « d'équipe » exclus, comme la feuille ESPN
      else if (/turnover/i.test(p.tt)) t.to++;
      else if (/foul/i.test(p.tt) && !/technical/i.test(p.tt)) t.pf++;
      if (p.shoot || /rebound|turnover/i.test(p.tt)) last.push(p);
    }
    return { T, P, hs, as, last: last.slice(-3).reverse() };
  }
  function fr(tx) { // le texte ESPN, en français approximatif
    return tx.replace(/\bmakes\b/g, "réussit").replace(/\bmisses\b/g, "rate")
      .replace(/three point (jumper|jump shot|shot|pullup jump shot|step back jump shot)/gi, "un tir à 3 pts")
      .replace(/free throw (\d) of (\d)/gi, "le lancer franc $1/$2").replace(/\b(\d+)-foot\b/g, "à $1 pieds,")
      .replace(/driving (layup|dunk)/gi, "$1 en pénétration").replace(/\blayup\b/gi, "un lay-up").replace(/\bdunk\b/gi, "un dunk")
      .replace(/(pullup |step back |turnaround |fadeaway )?jump(er| shot)/gi, "un tir").replace(/defensive rebound/gi, "rebond défensif")
      .replace(/offensive rebound/gi, "rebond offensif").replace(/\((.+?) assists\)/g, "(passe de $1)").replace(/bad pass/gi, "mauvaise passe")
      .replace(/\(turnover\)|turnover/gi, "(balle perdue)").replace(/\((.+?) steals\)/g, "(interception de $1)").replace(/blocks/g, "contre");
  }

  /* ---------- lecture du bandeau ---------- */
  const QRX = /^(?:([1lIi|!])(?:s|S|5)(?:t|T)|(2)(?:n|N)(?:d|D)|(3)(?:r|R)(?:d|D)|(4)(?:t|T)(?:h|H)|(OT|0T)(\d?)|Q([1-4]))/;
  function readQuarter(s) {
    const m = QRX.exec(s); if (!m) return 0;
    if (m[1]) return 1; if (m[2]) return 2; if (m[3]) return 3; if (m[4]) return 4; if (m[7]) return +m[7];
    return 4 + (+m[6] || 1);
  }
  function readClock(s) {
    s = s.replace(/[oO]/g, "0").replace(/[lI|!]/g, "1");
    let m = /(n|\d{1,2})[:;](\d{2})(?!\d)/.exec(s);
    if (m) { const mm = m[1] === "n" ? 11 : +m[1], ss = +m[2]; if (mm <= 12 && ss < 60 && mm * 60 + ss <= 720) return mm * 60 + ss; }
    m = /^(\d{1,2})\.(\d)$/.exec(s); // dernière minute : « 45.3 »
    if (m && +m[1] < 60) return +m[1] + +m[2] / 10;
    return null;
  }
  function parseWords(words) { // quart-temps + chrono le plus proche (évite le minutage YouTube « 0:01 / 9:54 »)
    let best = null;
    for (const q of words) {
      const per = readQuarter(q.text); if (!per) continue;
      const h = Math.max(8, q.bbox.y1 - q.bbox.y0), cx = (q.bbox.x0 + q.bbox.x1) / 2, cy = (q.bbox.y0 + q.bbox.y1) / 2;
      for (const c of words) {
        if (c === q) continue;
        const sec = readClock(c.text); if (sec === null) continue;
        const dx = (c.bbox.x0 + c.bbox.x1) / 2 - cx, dy = (c.bbox.y0 + c.bbox.y1) / 2 - cy, d = Math.hypot(dx, dy * 1.5);
        if (d > h * 9) continue;
        if (!best || d < best.d) best = { per, sec, alt: (sec < 180 && /^[^.]*:/.test(c.text) && !/^\d\d/.test(c.text.replace(/^n/, "11"))) ? sec + 600 : null, d, box: { x0: Math.min(q.bbox.x0, c.bbox.x0), y0: Math.min(q.bbox.y0, c.bbox.y0), x1: Math.max(q.bbox.x1, c.bbox.x1), y1: Math.max(q.bbox.y1, c.bbox.y1) } };
      }
    }
    return best;
  }

  async function loadTess() {
    if (!window.Tesseract) await new Promise((ok, ko) => { const s = document.createElement("script"); s.src = TESS; s.onload = ok; s.onerror = ko; document.head.appendChild(s); });
    const w = await Tesseract.createWorker("eng");
    await w.setParameters({ tessedit_pageseg_mode: "11" });
    return w;
  }

  // où est l'iframe dans l'image capturée ?
  function frameRect(vid, iframe, surface) {
    const r = iframe.getBoundingClientRect(), W = vid.videoWidth, H = vid.videoHeight;
    let k, ox = 0, oy = 0;
    if (surface === "browser") k = W / innerWidth;
    else { // fenêtre ou écran entier : on devine la place de la page
      const bx = Math.max(0, (outerWidth - innerWidth) / 2), by = Math.max(0, outerHeight - innerHeight - bx);
      if (surface === "monitor") { k = W / screen.width; ox = screenX + bx; oy = screenY + by; }
      else { k = W / outerWidth; ox = bx; oy = by; }
    }
    return { x: (r.left + ox) * k, y: (r.top + oy) * k, w: r.width * k, h: r.height * k, H };
  }
  function grab(src, sx, sy, sw, sh, scale, inv) {
    const c = S.cv || (S.cv = document.createElement("canvas"));
    c.width = Math.max(1, Math.round(sw * scale)); c.height = Math.max(1, Math.round(sh * scale));
    const x = c.getContext("2d", { willReadFrequently: true });
    x.drawImage(src, sx, sy, sw, sh, 0, 0, c.width, c.height);
    const d = x.getImageData(0, 0, c.width, c.height), p = d.data;
    for (let i = 0; i < p.length; i += 4) { const g = .3 * p[i] + .59 * p[i + 1] + .11 * p[i + 2]; const v = (g > 150) !== inv ? 0 : 255; p[i] = p[i + 1] = p[i + 2] = v; }
    x.putImageData(d, 0, 0);
    return c;
  }
  async function readFrame(src, R) { // R : rectangle de la vidéo dans l'image source
    const lock = S.lock;
    let sx, sy, sw, sh, scale;
    if (lock) { sx = R.x + lock.x * R.w; sy = R.y + lock.y * R.h; sw = lock.w * R.w; sh = lock.h * R.h; scale = Math.min(4, 200 / sh); }
    else { sx = R.x; sy = R.y + R.h * .7; sw = R.w; sh = R.h * .3; scale = Math.max(1, Math.min(2, 2450 / sw)); }
    sx = Math.max(0, sx); sy = Math.max(0, sy);
    const inv = !S.polar; // texte clair sur fond sombre (on essaie l'inverse après un échec)
    const c = grab(src, sx, sy, sw, sh, scale, inv);
    const { data } = await S.worker.recognize(c);
    const hit = parseWords(data.words || []);
    if (!hit) { S.polar = !S.polar; return null; }
    if (!lock) { // on cale la fenêtre de lecture autour du bandeau trouvé
      const b = hit.box, bw = (b.x1 - b.x0) / scale, bh = (b.y1 - b.y0) / scale;
      const lx = sx + b.x0 / scale - bw * .5, ly = sy + b.y0 / scale - bh * .8;
      S.lock = { x: (lx - R.x) / R.w, y: (ly - R.y) / R.h, w: bw * 2 / R.w, h: bh * 2.6 / R.h };
    }
    return hit;
  }

  /* ---------- filtre : on n'accepte qu'un chrono plausible ---------- */
  function accept(hit) { // un « 11:12 » peut être lu « 1:12 » : on garde la lecture qui colle à la précédente
    const nper = Math.max(4, ...S.D.plays.map(p => p.per));
    const cur = S.at, prev = S.cand;
    const opts = [hit.sec, hit.alt].filter(x => x !== null && x !== undefined && x <= (hit.per > 4 ? 300 : 720));
    if (hit.per > nper || !opts.length) return false;
    const near = (a, sec) => a && a.per === hit.per && a.opts.some(x => Math.abs(x - sec) <= 6);
    const forward = sec => cur && ((hit.per === cur.per && cur.sec - sec >= -2 && cur.sec - sec <= 75) || (hit.per === cur.per + 1 && sec >= 600));
    S.cand = { per: hit.per, opts };
    for (const sec of opts) if (forward(sec) || near(prev, sec)) { S.at = { per: hit.per, sec }; return true; }
    return false;
  }

  /* ---------- le panneau ---------- */
  const clockTxt = (per, sec) => `${per > 4 ? "Prol." + (per > 5 ? per - 4 : "") : "Q" + per} · ${sec >= 60 ? Math.floor(sec / 60) + ":" + String(Math.floor(sec % 60)).padStart(2, "0") : sec.toFixed(1)}`;
  function panelIdle() {
    return `<div class="lv-idle">
      <div class="lv-kick">Stats en direct</div>
      <p>Le panneau suit le résumé : à chaque instant, les stats du match <b>jusqu'au moment affiché</b>, pas plus loin.</p>
      <button class="btn amber" data-live-start>📡 Activer</button>
      <p class="lv-small">Ton navigateur va te demander de partager un onglet : choisis <b>cet onglet</b>. L'image reste sur ton ordinateur, rien n'est envoyé.
      Marche sur ordinateur (Chrome ou Edge conseillés).</p>${DEMO ? `<p class="lv-small">Démo : pas de vraie vidéo, un curseur simule le chrono.</p>` : ""}</div>`;
  }
  function render() {
    const el = S && S.el; if (!el) return;
    const st = S.status;
    if (!S.on) { el.innerHTML = panelIdle(); return; }
    const head = `<div class="lv-head"><span class="led lv-clock">${S.at ? clockTxt(S.at.per, S.at.sec) : "--:--"}</span>
      <span class="lv-st ${S.at && st === "ok" ? "ok" : ""}">${st === "load" ? "Préparation…" : st === "ok" ? "● Synchro" : st === "lost" ? "Bandeau introuvable" : "Recherche du chrono…"}</span>
      <button class="lv-stop" data-live-stop title="Arrêter le partage">■</button></div>
      ${DEMO ? `<input class="lv-demo" type="range" min="0" max="${S.D.plays.length - 1}" value="${S.demoI || 0}" aria-label="Simuler le moment du match">` : ""}`;
    if (!S.at) { el.innerHTML = head + `<p class="lv-wait">Lance la vidéo : dès que le bandeau du match est à l'écran, les stats apparaissent.</p>`; return; }
    const D = S.D, A = statsAt(D, S.at.per, S.at.sec), h = team(D.home), a = team(D.away), th = A.T[D.home], ta = A.T[D.away];
    const pc = (m, n) => n ? Math.round(100 * m / n) + " %" : "–";
    const row = (lab, va, vh, sa, sh) => { const tot = (sa + sh) || 1;
      return `<div class="lv-row"><b>${va}</b><span>${lab}</span><b>${vh}</b><i style="--a:${a.color};--h:${h.color};--p:${(sa / tot * 100).toFixed(1)}%"></i></div>`; };
    const top = t => Object.entries(A.P).filter(([id]) => D.names[id] && D.names[id].t === t).sort((x, y) => y[1].pts - x[1].pts).slice(0, 4)
      .map(([id, p]) => `<li><span>${D.names[id].n}</span><b>${p.pts}</b><small>pts</small><b>${p.reb}</b><small>reb</small><b>${p.ast}</b><small>pd</small></li>`).join("");
    el.innerHTML = head + `
      <div class="lv-score"><span class="lv-t" style="--mc:${a.color}">${a.tri}</span><span class="led">${A.as}</span><span class="lv-dash">–</span><span class="led">${A.hs}</span><span class="lv-t" style="--mc:${h.color}">${h.tri}</span></div>
      <div class="lv-rows">
        ${row("Tirs", `${ta.fg}/${ta.fga}`, `${th.fg}/${th.fga}`, ta.fg, th.fg)}
        ${row("Réussite", pc(ta.fg, ta.fga), pc(th.fg, th.fga), ta.fga ? ta.fg / ta.fga : 0, th.fga ? th.fg / th.fga : 0)}
        ${row("3 points", `${ta.tp}/${ta.tpa}`, `${th.tp}/${th.tpa}`, ta.tp, th.tp)}
        ${row("Lancers", `${ta.ftm}/${ta.fta}`, `${th.ftm}/${th.fta}`, ta.ftm, th.ftm)}
        ${row("Rebonds", ta.reb, th.reb, ta.reb, th.reb)}
        ${row("Passes", ta.ast, th.ast, ta.ast, th.ast)}
        ${row("Balles perdues", ta.to, th.to, ta.to, th.to)}
      </div>
      <div class="lv-pl"><div><h4 style="--mc:${a.color}">${a.name}</h4><ol>${top(D.away) || "<li class=e>—</li>"}</ol></div>
        <div><h4 style="--mc:${h.color}">${h.name}</h4><ol>${top(D.home) || "<li class=e>—</li>"}</ol></div></div>
      <div class="lv-last"><h4>Dernières actions</h4>${A.last.map(p => `<p><time>${p.clk}</time>${fr(p.tx)}</p>`).join("") || "<p>—</p>"}</div>`;
  }

  /* ---------- boucle de lecture ---------- */
  async function loop(my) {
    while (S === my && S.on) {
      const R = frameRect(S.vid, S.iframe, S.surface);
      let hit = null;
      if (S.vid.videoWidth && R.w > 50) { try { hit = await readFrame(S.vid, R); } catch (e) { hit = null; } }
      if (S !== my) return;
      if (hit && accept(hit)) { S.miss = 0; S.status = "ok"; render(); }
      else if (++S.miss >= 8) { S.lock = null; S.status = S.at ? "lost" : "seek"; render(); S.miss = 0; }
      await new Promise(r => setTimeout(r, S.lock ? 300 : 900));
    }
  }
  async function start() {
    if (!S) return;
    const my = S;
    if (DEMO) { S.on = true; S.status = "ok"; S.demoI = Math.floor(S.D.plays.length * .3); const p = S.D.plays[S.demoI]; S.at = { per: p.per, sec: p.sec }; render(); return; }
    let stream;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: { displaySurface: "browser", frameRate: 4 }, audio: false,
        preferCurrentTab: true, selfBrowserSurface: "include", surfaceSwitching: "exclude" });
    } catch (e) { toast("Partage refusé : pas de stats en direct cette fois"); return; }
    if (S !== my) { stream.getTracks().forEach(t => t.stop()); return; }
    const tr = stream.getVideoTracks()[0];
    S.stream = stream; S.surface = (tr.getSettings && tr.getSettings().displaySurface) || "browser";
    tr.addEventListener("ended", () => { if (S === my) stop(); });
    S.vid = document.createElement("video"); S.vid.muted = true; S.vid.playsInline = true; S.vid.srcObject = stream;
    await S.vid.play().catch(() => {});
    S.on = true; S.status = "load"; render();
    try { S.worker = S.worker || await loadTess(); } catch (e) { toast("Impossible de charger le lecteur de chrono"); stop(); return; }
    if (S !== my) return;
    S.status = "seek"; render();
    loop(my);
  }
  function stop() {
    if (!S) return;
    if (S.stream) S.stream.getTracks().forEach(t => t.stop());
    S.stream = null; S.on = false; S.at = null; S.cand = null; S.lock = null; S.miss = 0;
    render();
  }

  /* ---------- branchement sur le lecteur vidéo ---------- */
  async function attach(gid, panel, iframe) {
    close();
    const my = S = { gid, el: panel, iframe, on: false, miss: 0, D: null };
    panel.innerHTML = `<p class="lv-wait">Chargement du déroulé du match…</p>`;
    try {
      if (DEMO) { const g = state.games.find(x => x.id === gid); my.D = demoPlays(await window.DEMO.summary(gid), g); }
      else my.D = parsePlays(await fetchJSON(API + "summary?event=" + gid));
    } catch (e) { my.D = null; }
    if (S !== my) return;
    if (!my.D || my.D.plays.length < 20) { panel.innerHTML = `<p class="lv-wait">Pas de déroulé ESPN pour ce match : pas de stats en direct.</p>`; return; }
    render();
  }
  function close() {
    if (!S) return;
    const w = S.worker; stop(); S = null;
    if (w) w.terminate().catch(() => {});
  }
  document.addEventListener("click", e => {
    if (e.target.closest("[data-live-start]")) start();
    else if (e.target.closest("[data-live-stop]")) stop();
  });
  document.addEventListener("input", e => {
    if (!S || !e.target.classList.contains("lv-demo")) return;
    S.demoI = +e.target.value; const p = S.D.plays[S.demoI]; S.at = { per: p.per, sec: p.sec };
    const v = e.target.value; render(); const n = S.el.querySelector(".lv-demo"); if (n) { n.value = v; n.focus(); }
  });

  // tests : lire le bandeau d'une image fixe (capture d'écran), rect = place de la vidéo dans l'image
  async function testImage(url, rect) {
    const img = await new Promise((ok, ko) => { const i = new Image(); i.onload = () => ok(i); i.onerror = ko; i.src = url; });
    const keep = S; S = { lock: null, worker: await loadTess() };
    const out = [];
    for (let i = 0; i < 4; i++) { const t0 = performance.now(); const h = await readFrame(img, rect); out.push({ ms: Math.round(performance.now() - t0), hit: h && { per: h.per, sec: h.sec }, lock: !!S.lock }); }
    await S.worker.terminate(); S = keep;
    return out;
  }
  return { CAN, attach, close, testImage, _parse: parseWords, _plays: parsePlays, _stats: statsAt };
})();
