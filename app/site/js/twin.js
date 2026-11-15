/*
  twin.js: the moving picture of the simulation. One irrigation district, drawn twice.

      left    the district if nothing is done to its canals
      right   the same district if canals are sealed when the forecast warns

  Both sides get the same reservoir, the same weather and the same weeks. The layout follows
  the team's simulation design (visuals/simulation): one district splits in two and the two
  halves are played side by side.

  WHAT IS REAL AND WHAT IS A PICTURE
    Real (from sim/engine.js, week by week):
      - the share of the water farms asked for that arrives (it sets how many fields are dry)
      - which canals are sealed and when, the dollars lost, the dollars spent, the water kept
      - the district boundary and every canal line (real map data)
    A picture only:
      - WHICH squares go dry. The district is tiled with squares and the right share of them
        is coloured dry; the model does not know which farm loses water.
      - the orange dots drifting off the canals. They show that an unsealed canal seeps;
        the amount is in the numbers, not in the dots.

  window.HGTwin.create({ canvas, stage, onTick }) returns { load, play, pause, seek, playing, readTheme }.
*/
(function () {
  "use strict";

  function create(opt) {
    const canvas = opt.canvas, stage = opt.stage, ctx = canvas.getContext("2d");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const SECONDS = 34;                       // how long the whole run takes to play
    const MAX_DOTS = 260;                     // leak dots per side
    let W = 0, H = 0, dpr = 1, data = null, at = 0, playing = false, last = 0, split = 0, clock = 0;
    let zoom = 1;                             // both panels move in on the canals while the right side is sealed
    const ZOOM = 2;
    let shape = null;                         // the district in flat kilometres: rings, canals, fields, box
    let panels = [];                          // the two drawing areas, rebuilt on resize
    const dots = [[], []];                    // leak dots, left side and right side
    const C = {};

    function readTheme() {
      const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      Object.assign(C, { map: css("--map"), card: css("--card"), text: css("--ink"), head: css("--head"), muted: css("--muted"),
                         rule: css("--line"), accent: css("--blue"), river: css("--river"), hl: css("--hl"), casing: css("--casing"),
                         low: css("--low"), watch: css("--watch"), warning: css("--warning"), inspect: css("--inspect"),
                         unknown: css("--unknown"), wet: css("--wet"), dry: css("--dry"), dead: css("--dead"), serif: css("--serif") });
      C.level = { "Inspect first": C.inspect, Watch: C.watch, Low: C.low };
    }
    readTheme();

    /* ---------- Colour helpers ---------- */
    const rgb = (hex) => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16)];
    function mix(a, b, t) {
      const x = rgb(a), y = rgb(b);
      return "rgb(" + [0, 1, 2].map((k) => Math.round(x[k] + (y[k] - x[k]) * t)).join(",") + ")";
    }
    const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

    /* ---------- The district as flat shapes ----------
       Longitude and latitude are turned into kilometres east and south of the district's
       centre. A district is small, so this simple flattening is accurate enough to draw. */
    function build(d) {
      let lon0 = 0, lat0 = 0, n = 0;
      d.rings.forEach((r) => r.forEach((p) => { lon0 += p[0]; lat0 += p[1]; n++; }));
      lon0 /= n; lat0 /= n;
      const kx = 111.32 * Math.cos(lat0 * Math.PI / 180), ky = 110.57;
      const flat = (line) => line.map((p) => [(p[0] - lon0) * kx, -(p[1] - lat0) * ky]);
      const rings = d.rings.map(flat);
      const box = [1e9, 1e9, -1e9, -1e9];
      rings.forEach((r) => r.forEach((p) => { box[0] = Math.min(box[0], p[0]); box[1] = Math.min(box[1], p[1]); box[2] = Math.max(box[2], p[0]); box[3] = Math.max(box[3], p[1]); }));
      const canals = d.canals.map((c) => ({ pts: flat(c.line), funded: c.funded, ranked: c.ranked, level: c.level, weight: c.km * (c.rate || 0) }));
      // Tile the district with squares ("fields"). Each gets a fixed random number from 0 to 1;
      // a field is dry in a week when the share of water that arrived is below its number.
      const inside = (x, y) => {
        let hit = false;
        for (const r of rings) for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
          if ((r[i][1] > y) !== (r[j][1] > y) && x < (r[j][0] - r[i][0]) * (y - r[i][1]) / (r[j][1] - r[i][1]) + r[i][0]) hit = !hit;
        }
        return hit;
      };
      let step = Math.sqrt((box[2] - box[0]) * (box[3] - box[1]) / 700), fields = [];
      for (let tries = 0; tries < 4; tries++) {
        fields = [];
        for (let y = box[1] + step / 2; y < box[3]; y += step) for (let x = box[0] + step / 2; x < box[2]; x += step) if (inside(x, y)) fields.push({ x, y });
        if (fields.length >= 180 && fields.length <= 520) break;
        step *= Math.sqrt(fields.length / 330) || 0.7;
      }
      let seed = 12345;                                             // a fixed seed: the same squares every time
      fields.forEach((f) => { seed = (seed * 1664525 + 1013904223) >>> 0; f.u = seed / 4294967296; });
      // Leak dots start on ranked canals; leakier and longer canals get more of them.
      const leaky = canals.filter((c) => c.ranked && c.weight > 0 && c.pts.length > 1);
      let total = 0; leaky.forEach((c) => { total += c.weight; c.upTo = total; });
      // Where the sealed canals are: the middle of all their points. The picture zooms in on it.
      let fx = 0, fy = 0, fn = 0;
      canals.filter((c) => c.funded).forEach((c) => c.pts.forEach((q) => { fx += q[0]; fy += q[1]; fn++; }));
      const focus = fn ? [fx / fn, fy / fn] : [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
      return { rings, box, canals, fields, step, leaky, total, focus };
    }

    /* ---------- Layout: two panels side by side (stacked on a phone) ---------- */
    function layout() {
      const r = stage.getBoundingClientRect();
      if (!r.width || !r.height) return;
      W = r.width; H = r.height; dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = W * dpr; canvas.height = H * dpr;
      if (!shape) return;
      const narrow = W < 620, top = narrow ? 118 : 128, bottom = 58, gap = 12, side = 14;
      const boxes = narrow
        ? [0, 1].map((k) => ({ x: side, y: top + k * ((H - top - bottom + gap) / 2), w: W - 2 * side, h: (H - top - bottom - gap) / 2 }))
        : [0, 1].map((k) => ({ x: side + k * ((W - 2 * side + gap) / 2), y: top, w: (W - 2 * side - gap) / 2, h: H - top - bottom }));
      panels = boxes.map((b) => {
        // Fit the district into the part of the panel above the numbers.
        const head = 34, foot = narrow ? 64 : 104, mw = b.w - 20, mh = b.h - head - foot;
        const k = Math.min(mw / (shape.box[2] - shape.box[0]), mh / (shape.box[3] - shape.box[1])) * 0.94;
        const cx = (shape.box[0] + shape.box[2]) / 2, cy = (shape.box[1] + shape.box[3]) / 2;
        const sx = (x) => (x - cx) * k + b.w / 2, sy = (y) => (y - cy) * k + head + mh / 2;     // relative to the panel corner
        const path = (lines, close) => { const p = new Path2D(); lines.forEach((l) => { l.forEach((q, i) => (i ? p.lineTo(sx(q[0]), sy(q[1])) : p.moveTo(sx(q[0]), sy(q[1])))); if (close) p.closePath(); }); return p; };
        const pick = (test) => path(shape.canals.filter(test).map((c) => c.pts));
        return Object.assign({ k, sx, sy, narrow, foot, head, mh,
          outline: path(shape.rings, true),
          all: pick((c) => c.ranked),                                 // every canal the model can rank
          other: pick((c) => !c.ranked),                              // canals with no soil data: drawn, never sealed
          byLevel: ["Low", "Watch", "Inspect first"].map((lv) => ({ color: C.level[lv], path: pick((c) => c.ranked && c.level === lv) })),
          funded: pick((c) => c.funded) }, b);
      });
    }
    new ResizeObserver(layout).observe(stage);

    /* ---------- The week being shown ---------- */
    const index = () => Math.min(data.weeks.length - 1, Math.floor(at));
    function arrives(w, s) { return w.demand > 0 ? Math.max(0, 1 - (s.missing - s.recovered) / w.demand) : null; }   // null = outside the season

    /* ---------- Leak dots ---------- */
    function spawn(sideDots, sealedNow) {
      if (!shape.total || sideDots.length >= MAX_DOTS) return;
      const r = Math.random() * shape.total, c = shape.leaky.find((x) => x.upTo >= r) || shape.leaky[0];
      if (c.funded && sealedNow && Math.random() < data.cut) return;   // a sealed canal seeps less, by the sealant's tested share
      const i = Math.floor(Math.random() * (c.pts.length - 1)), u = Math.random(), a = c.pts[i], b = c.pts[i + 1], ang = Math.random() * 6.283;
      sideDots.push({ x: a[0] + (b[0] - a[0]) * u, y: a[1] + (b[1] - a[1]) * u, dx: Math.cos(ang), dy: Math.sin(ang), life: 1 });
    }
    function stepDots(dt) {
      const w = data.weeks[index()];
      [w.left, w.right].forEach((s, k) => {
        if (w.demand > 0) for (let n = 0; n < 3; n++) if (Math.random() < dt * 60) spawn(dots[k], s.sealed);   // canals only carry water in the season
        dots[k].forEach((d) => { d.life -= dt * 0.9; });
        dots[k] = dots[k].filter((d) => d.life > 0);
      });
    }

    /* ---------- Drawing ---------- */
    function text(s, x, y, size, color, o) {
      o = o || {};
      ctx.font = (o.italic ? "italic " : "") + (o.weight || 400) + " " + size + "px " + C.serif;
      ctx.textAlign = o.align || "left"; ctx.textBaseline = "middle"; ctx.globalAlpha = o.alpha == null ? 1 : o.alpha;
      ctx.fillStyle = color; ctx.fillText(s, x, y);
    }
    const money = (v) => (v >= 1e9 ? "$" + (v / 1e9).toFixed(2) + "B" : v >= 1e6 ? "$" + (v / 1e6).toFixed(v >= 1e8 ? 0 : 1) + "M" : v >= 1e4 ? "$" + Math.round(v / 1e3) + "k" : "$" + Math.round(v).toLocaleString("en-US"));
    const num = (v) => Math.round(v).toLocaleString("en-US");

    function drawPanel(p, k, w, i) {
      const s = k ? w.right : w.left, sum = k ? w.sumR : w.sumL, share = arrives(w, s), right = k === 1;
      // Where the panel sits: both start in the middle and slide apart as the district "splits".
      const e = ease(split), mid = p.narrow ? p.x : (W - p.w) / 2, x = mid + (p.x - mid) * e, y = p.y;
      ctx.save(); ctx.translate(x, y);
      ctx.globalAlpha = 1; ctx.fillStyle = C.card; ctx.fillRect(0, 0, p.w, p.h);
      ctx.strokeStyle = right ? C.accent : C.rule; ctx.lineWidth = right ? 2 : 1; ctx.strokeRect(0.5, 0.5, p.w - 1, p.h - 1);

      // Zoom: while canals are sealed, both panels move in on them (the same view on both sides,
      // so the comparison stays fair). Lines are thinned by the same factor so they keep their width.
      ctx.save();
      ctx.beginPath(); ctx.rect(1, p.head - 4, p.w - 2, p.mh + 8); ctx.clip();
      const t = (zoom - 1) / (ZOOM - 1), fx = p.sx(shape.focus[0]), fy = p.sy(shape.focus[1]), z = zoom;
      ctx.translate(fx + (p.w / 2 - fx) * t, fy + (p.head + p.mh / 2 - fy) * t); ctx.scale(z, z); ctx.translate(-fx, -fy);

      // 1. Fields. Dry ones are tan, and darken the longer they have been dry (looking back 26 weeks).
      const size = Math.max(2.5, shape.step * p.k * 0.84), side = k ? "right" : "left", recent = [];
      for (let j = Math.max(0, i - 25); j <= i; j++) { const v = arrives(data.weeks[j], data.weeks[j][side]); if (v != null) recent.push(v); }
      for (const f of shape.fields) {
        let age = 0; for (const v of recent) if (v < f.u) age++;
        age = recent.length ? age / recent.length : 0;
        if (share == null) { ctx.globalAlpha = 0.22; ctx.fillStyle = mix(C.wet, C.dry, age * 0.6); }          // off season: fields rest
        else if (share < f.u) { ctx.globalAlpha = 0.8; ctx.fillStyle = mix(C.dry, C.dead, Math.min(1, age * 1.15)); }
        else { ctx.globalAlpha = 0.5 - 0.2 * age; ctx.fillStyle = mix(C.wet, C.dry, age * 0.5); }
        ctx.fillRect(p.sx(f.x) - size / 2, p.sy(f.y) - size / 2, size, size);
      }
      ctx.globalAlpha = 0.9; ctx.strokeStyle = C.text; ctx.lineWidth = 1.3 / z; ctx.stroke(p.outline);

      // 2. Canals, drawn large. A dark casing first so every line reads against the fields.
      ctx.lineJoin = ctx.lineCap = "round";
      ctx.globalAlpha = 0.5; ctx.strokeStyle = C.unknown; ctx.lineWidth = 1 / z; ctx.stroke(p.other);
      ctx.globalAlpha = 0.9; ctx.strokeStyle = C.map; ctx.lineWidth = 4.6 / z; ctx.stroke(p.all);
      for (const lv of p.byLevel) { ctx.globalAlpha = 1; ctx.strokeStyle = lv.color; ctx.lineWidth = 2.3 / z; ctx.stroke(lv.path); }
      // Water moving in the canals: a dashed line that slides along. Fainter when less water is released.
      if (share != null && !reduced) {
        ctx.setLineDash([5 / z, 11 / z]); ctx.lineDashOffset = -clock * 26 / z;
        ctx.globalAlpha = 0.25 + 0.6 * (1 - s.missing / w.demand); ctx.strokeStyle = C.river; ctx.lineWidth = 1.5 / z; ctx.stroke(p.all);
        ctx.setLineDash([]);
      }
      // Sealed canals: white, with a glow that is strongest in the weeks just after the work.
      if (s.sealed) {
        let since = 0; while (since < 14 && i - since >= 0 && data.weeks[i - since][side].sealed && !(data.weeks[i - since][side].spend > 0)) since++;
        const fresh = Math.max(0, 1 - since / 6);
        ctx.globalAlpha = 0.22 + 0.3 * fresh; ctx.strokeStyle = C.hl; ctx.lineWidth = (7 + 9 * fresh) / z; ctx.stroke(p.funded);
        ctx.globalAlpha = 1; ctx.strokeStyle = C.hl; ctx.lineWidth = 2.8 / z; ctx.stroke(p.funded);
      }
      // 3. Leak dots.
      ctx.fillStyle = C.inspect;
      for (const d of dots[k]) {
        const far = (1 - d.life) * 9 / z;
        ctx.globalAlpha = Math.min(1, d.life * 1.4) * 0.9;
        ctx.beginPath(); ctx.arc(p.sx(d.x) + d.dx * far, p.sy(d.y) + d.dy * far, 1.6 / z, 0, 7); ctx.fill();
      }
      ctx.restore();                                               // end of the zoomed, clipped map

      // 4. The words and numbers.
      const a = Math.min(1, e * 1.5), bad = share != null && share < 0.999;
      text(right ? data.rightName : data.leftName, 12, 18, p.narrow ? 16 : 18, right ? C.accent : C.head, { weight: 700, alpha: a });
      text(s.sealed ? "canals sealed now (" + data.sealedWord + ")" : right ? data.rightNote : data.leftNote, p.w - 12, 18, 13.5, s.sealed ? C.hl : C.muted, { italic: !s.sealed, weight: s.sealed ? 700 : 400, align: "right", alpha: a });
      const base = p.h - p.foot;
      text(money(sum.loss), 12, base + 24, p.narrow ? 26 : 34, sum.loss > 1e4 ? C.head : C.muted, { weight: 700 });
      text("in crops lost so far", 12, base + (p.narrow ? 46 : 52), 13.5, C.muted, { italic: true });
      text(share == null ? "off season" : Math.round(share * 100) + "%", p.w - 12, base + 22, p.narrow ? 19 : 22, bad ? C.warning : C.head, { weight: 700, align: "right" });
      text(share == null ? "canals are not running" : "of the water farms asked for arrives", p.w - 12, base + (p.narrow ? 42 : 46), 13, C.muted, { italic: true, align: "right" });
      if (!p.narrow) {
        text(right ? "Sealing so far: " + money(sum.spend) + ". Water kept: " + num(sum.saved) + " acre-feet, " + num(sum.recovered) + " in a shortage."
                   : "Sealing so far: $0. Every canal keeps seeping.", 12, p.h - 18, 13, C.muted);
      }
      ctx.restore();
    }

    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
      if (!data || !panels.length) return;
      const i = index(), w = data.weeks[i], narrow = panels[0].narrow, tone = C[data.tone] || C.watch;
      // Header: which future this is (left) and the week and reservoir (right).
      text(data.caseName, 14, narrow ? 64 : 70, narrow ? 19 : 24, tone, { weight: 700 });
      const room = Math.floor((W - (narrow ? 28 : 250)) / 6.2);     // letters that fit beside the reservoir reading
      text(data.caseNote.length > room ? data.caseNote.slice(0, room - 1) + "…" : data.caseNote, 14, narrow ? 86 : 96, 13.5, C.muted, { italic: true });
      text(w.date.slice(0, 4), W - 14, narrow ? 64 : 70, narrow ? 24 : 34, C.head, { weight: 700, align: "right" });
      if (!narrow) text(data.system + " " + w.pct.toFixed(1) + "% full", W - 14, 96, 13.5, w.pct < data.fullAt ? C.warning : C.muted, { italic: true, align: "right" });
      panels.forEach((p, k) => drawPanel(p, k, w, i));
      // The verdict, once the run has finished.
      if (i >= data.weeks.length - 1 && split >= 1) {
        const diff = (w.sumL.loss + w.sumL.spend) - (w.sumR.loss + w.sumR.spend), small = Math.abs(diff) < 1000;
        const label = small ? "No measurable difference in this future" : "Acting " + (diff > 0 ? "saves " : "costs ") + money(Math.abs(diff)) + (diff > 0 ? "" : " more") + " in this future";
        ctx.font = "700 " + (narrow ? 16 : 20) + "px " + C.serif;
        const tw = ctx.measureText(label).width + 30, ty = narrow ? panels[1].y - 6 : panels[0].y + 56;
        ctx.globalAlpha = 1; ctx.fillStyle = C.map; ctx.strokeStyle = small ? C.muted : diff > 0 ? C.low : C.warning; ctx.lineWidth = 2;
        ctx.fillRect(W / 2 - tw / 2, ty - 20, tw, 40); ctx.strokeRect(W / 2 - tw / 2, ty - 20, tw, 40);
        text(label, W / 2, ty, narrow ? 16 : 20, small ? C.muted : diff > 0 ? C.low : C.warning, { weight: 700, align: "center" });
      }
    }

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000 || 0); last = now; clock += dt;
      if (data && stage.offsetParent !== null && canvas.offsetParent !== null) {
        if (split < 1) split = reduced ? 1 : Math.min(1, split + dt / 1.4);        // the district splits in two first
        else if (playing) {
          at = Math.min(data.weeks.length - 1, at + dt * data.weeks.length / SECONDS);
          if (at >= data.weeks.length - 1) playing = false;
          opt.onTick(index(), playing);
        }
        const want = data.weeks[index()].right.sealed ? ZOOM : 1;                  // ease the zoom in and out
        zoom = reduced ? want : zoom + (want - zoom) * Math.min(1, dt * 2.5);
        if (!reduced) stepDots(dt);
        draw();
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return {
      /* next: { rings, canals: [{ line, km, rate, level, ranked, funded }], weeks: [{ date, pct, demand, left, right, sumL, sumR }],
                 caseName, caseNote, tone, system, fullAt, cut, leftName, rightName, leftNote, rightNote } */
      load(next) { data = next; shape = build(next); at = 0; split = 0; zoom = 1; dots[0] = []; dots[1] = []; playing = false; layout(); opt.onTick(0, false); },
      play() { if (!data) return; if (at >= data.weeks.length - 1) at = 0; playing = true; },
      pause() { playing = false; if (data) opt.onTick(index(), false); },
      seek(i) { at = i; split = 1; if (data) opt.onTick(index(), playing); },
      playing: () => playing,
      readTheme() { readTheme(); layout(); },
    };
  }

  window.HGTwin = { create };
})();
