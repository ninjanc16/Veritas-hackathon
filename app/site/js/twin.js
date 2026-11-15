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
      - the dots on the canals. Red dots show an unsealed canal leaking, white dots a sealed
        stretch holding its water. The amounts are in the numbers, not in the dots.

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
      // Flatten each district about its own centre.
      const flatPart = (part) => {
        let lon0 = 0, lat0 = 0, n = 0;
        part.rings.forEach((r) => r.forEach((p) => { lon0 += p[0]; lat0 += p[1]; n++; }));
        lon0 /= n; lat0 /= n;
        const kx = 111.32 * Math.cos(lat0 * Math.PI / 180), ky = 110.57;
        const flat = (line) => line.map((p) => [(p[0] - lon0) * kx, -(p[1] - lat0) * ky]);
        const rings = part.rings.map(flat); let half = 0;
        rings.forEach((r) => r.forEach((p) => { half = Math.max(half, Math.abs(p[0]), Math.abs(p[1])); }));
        return { rings, half, canals: part.canals.map((c) => ({ pts: flat(c.line), funded: c.funded, ranked: c.ranked, level: c.level, weight: c.km * (c.rate || 0) })) };
      };
      const parts = d.parts.slice().sort((a, b) => (b.km || 0) - (a.km || 0)).map(flatPart);
      // One district keeps its real shape and size. Several districts are laid out in a grid,
      // each one scaled to fill its own cell, so small districts stay readable (not to scale).
      const many = parts.length > 1, cols = Math.ceil(Math.sqrt(parts.length * 0.8));
      const rings = [], canals = [];
      parts.forEach((part, k) => {
        const f = many ? 0.44 / part.half : 1, ox = many ? k % cols : 0, oy = many ? Math.floor(k / cols) : 0;
        const move = (line) => line.map((q) => [q[0] * f + ox, q[1] * f + oy]);
        part.rings.forEach((r) => rings.push(move(r)));
        part.canals.forEach((c) => canals.push(Object.assign(c, { pts: move(c.pts) })));
      });
      const box = [1e9, 1e9, -1e9, -1e9];
      rings.forEach((r) => r.forEach((p) => { box[0] = Math.min(box[0], p[0]); box[1] = Math.min(box[1], p[1]); box[2] = Math.max(box[2], p[0]); box[3] = Math.max(box[3], p[1]); }));
      // Tile the district with squares ("fields"). Each gets a fixed random number from 0 to 1;
      // a field is dry in a week when the share of water that arrived is below its number.
      const inside = (x, y) => {
        let hit = false;
        for (const r of rings) for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
          if ((r[i][1] > y) !== (r[j][1] > y) && x < (r[j][0] - r[i][0]) * (y - r[i][1]) / (r[j][1] - r[i][1]) + r[i][0]) hit = !hit;
        }
        return hit;
      };
      let step = Math.sqrt((box[2] - box[0]) * (box[3] - box[1]) / (many ? 1500 : 700)), fields = [];
      for (let tries = 0; tries < 4; tries++) {
        fields = [];
        for (let y = box[1] + step / 2; y < box[3]; y += step) for (let x = box[0] + step / 2; x < box[2]; x += step) if (inside(x, y)) fields.push({ x, y });
        if (fields.length >= 180 && fields.length <= (many ? 900 : 520)) break;
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

    /* ---------- Dots on the canals ----------
       A red dot is water leaking out of an unsealed canal. A white dot marks a sealed stretch
       holding its water. On a sealed canal the sealant's tested share of dots turn white. */
    function spawn(sideDots, sealedNow) {
      if (!shape.total || sideDots.length >= MAX_DOTS) return;
      const r = Math.random() * shape.total, c = shape.leaky.find((x) => x.upTo >= r) || shape.leaky[0];
      const fixed = c.funded && sealedNow && Math.random() < data.cut;
      const i = Math.floor(Math.random() * (c.pts.length - 1)), u = Math.random(), a = c.pts[i], b = c.pts[i + 1], ang = Math.random() * 6.283;
      sideDots.push({ x: a[0] + (b[0] - a[0]) * u, y: a[1] + (b[1] - a[1]) * u, dx: Math.cos(ang), dy: Math.sin(ang), life: 1, fixed });
    }
    function stepDots(dt) {
      const w = data.weeks[index()];
      [w.left, w.right].forEach((s, k) => {
        if (w.demand > s.missing) for (let n = 0; n < 3; n++) if (Math.random() < dt * 60) spawn(dots[k], s.sealed);   // only a canal with water in it can leak
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

      // 1. Fields: the main thing to look at. Watered fields are green; dry ones are brown and
      //    darken the longer they have been dry (looking back 26 weeks). On the right, a field
      //    that is dry on the left but watered here is drawn brighter: sealing kept it going.
      const size = Math.max(2.5, shape.step * p.k * 0.93), side = k ? "right" : "left", recent = [];
      const other = arrives(w, w.left);                               // what the do-nothing side gets this week
      for (let j = Math.max(0, i - 25); j <= i; j++) { const v = arrives(data.weeks[j], data.weeks[j][side]); if (v != null) recent.push(v); }
      for (const f of shape.fields) {
        let age = 0; for (const v of recent) if (v < f.u) age++;
        age = recent.length ? age / recent.length : 0;
        const kept = right && share != null && share >= f.u && other < f.u;
        if (share == null) { ctx.globalAlpha = 0.3; ctx.fillStyle = mix(C.wet, C.dry, age * 0.6); }           // off season: fields rest
        else if (share < f.u) { ctx.globalAlpha = 0.95; ctx.fillStyle = mix(C.dry, C.dead, Math.min(1, age * 1.15)); }
        else { ctx.globalAlpha = kept ? 1 : 0.8; ctx.fillStyle = kept ? C.low : mix(C.wet, C.dry, age * 0.4); }
        ctx.fillRect(p.sx(f.x) - size / 2, p.sy(f.y) - size / 2, size, size);
      }
      ctx.globalAlpha = 0.95; ctx.strokeStyle = C.text; ctx.lineWidth = 1.6; ctx.stroke(p.outline);

      // 2. Canals. Red = unsealed and leaking. White = sealed. Both sides start red; only the
      //    acting side ever turns white. Canals with no soil reading stay thin and grey.
      ctx.lineJoin = ctx.lineCap = "round";
      const running = share != null && w.demand > s.missing;         // is any water in the canals this week?
      ctx.globalAlpha = 0.35; ctx.strokeStyle = C.unknown; ctx.lineWidth = 0.8; ctx.stroke(p.other);
      ctx.globalAlpha = running ? 0.95 : 0.45; ctx.strokeStyle = C.warning; ctx.lineWidth = 1.5; ctx.stroke(p.all);
      if (s.sealed) {
        ctx.globalAlpha = 0.3; ctx.strokeStyle = C.low; ctx.lineWidth = 6; ctx.stroke(p.funded);                // a soft green glow
        ctx.globalAlpha = 1; ctx.strokeStyle = C.hl; ctx.lineWidth = 1.9; ctx.stroke(p.funded);
      }
      for (const d of dots[k]) {
        const far = d.fixed ? 0 : (1 - d.life) * 9;
        ctx.globalAlpha = Math.min(1, d.life * 1.4); ctx.fillStyle = d.fixed ? C.hl : C.warning;
        ctx.beginPath(); ctx.arc(p.sx(d.x) + d.dx * far, p.sy(d.y) + d.dy * far, d.fixed ? 2.2 * d.life + 0.6 : 1.7, 0, 7); ctx.fill();
      }
      ctx.restore();                                               // end of the clipped map

      // 3. The numbers. Left: what is lost. Right: what acting has saved. Few words on purpose.
      const a = Math.min(1, e * 1.5), base = p.h - p.foot, big = p.narrow ? 26 : 38, med = p.narrow ? 18 : 24;
      const savedSoFar = Math.max(0, w.sumL.loss - w.sumR.loss);     // crops the right side kept that the left side lost
      text(right ? data.rightName : data.leftName, 12, 18, p.narrow ? 16 : 18, right ? C.accent : C.head, { weight: 700, alpha: a });
      text(share == null ? "off season" : Math.round((1 - share) * 100) + "% of fields dry", p.w - 12, 18, 14, share != null && share < 0.999 ? (right && share > other + 0.005 ? C.watch : C.warning) : C.muted, { weight: 600, align: "right", alpha: a });
      text(money(right ? savedSoFar : sum.loss), 12, base + 26, big, right ? C.low : C.warning, { weight: 700 });
      text(right ? "crops saved" : "crops lost", 12, base + (p.narrow ? 48 : 56), 13.5, C.muted);
      text(num(right ? sum.saved : sum.leak), p.w - 12, base + 30, med, right ? C.low : C.warning, { weight: 700, align: "right" });
      text(right ? "acre-feet kept in canals" : "acre-feet leaked", p.w - 12, base + (p.narrow ? 48 : 56), 13.5, C.muted, { align: "right" });
      if (!p.narrow && right) text("still leaking: " + num(sum.leak) + " acre-feet", p.w - 12, base + 78, 12.5, C.muted, { align: "right" });
      ctx.restore();
    }

    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
      if (!data || !panels.length) return;
      const i = index(), w = data.weeks[i], narrow = panels[0].narrow, tone = C[data.tone] || C.watch;
      // Header: which future this is (left) and the week and reservoir (right).
      if (!narrow) text(data.caseName, 14, 70, 24, tone, { weight: 700 });
      if (!narrow && data.parts.length > 1) text(data.parts.length + " districts, each drawn to fill its own cell", 14, 96, 13.5, C.muted);
      text(w.date.slice(0, 4), W - 14, narrow ? 64 : 70, narrow ? 24 : 34, C.head, { weight: 700, align: "right" });
      text("reservoirs " + w.pct.toFixed(0) + "% full", narrow ? 14 : W - 14, narrow ? 86 : 96, 13.5, w.pct < data.fullAt ? C.warning : C.muted, { align: narrow ? "left" : "right" });
      panels.forEach((p, k) => drawPanel(p, k, w, i));
      // The verdict, once the run has finished.
      if (i >= data.weeks.length - 1 && split >= 1) {
        const diff = (w.sumL.loss + w.sumL.spend) - (w.sumR.loss + w.sumR.spend), small = Math.abs(diff) < 1000;
        const label = small ? "No measurable difference" : "Acting " + (diff > 0 ? "saves " : "costs ") + money(Math.abs(diff)) + (diff > 0 ? "" : " more");
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
        const want = 1;                                                              // no zoom: the whole district stays in view
        if (!reduced) stepDots(dt);
        zoom = reduced ? want : zoom + (want - zoom) * Math.min(1, dt * 2.5);
        draw();
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return {
      /* next: { parts: [{ rings, km, canals: [{ line, km, rate, level, ranked, funded }] }], weeks: [{ date, pct, demand, left, right, sumL, sumR }],
                 caseName, caseNote, tone, system, fullAt, cut, leftName, rightName, leftNote, rightNote } */
      load(next) { data = next; shape = build(next); at = 0; split = 0; zoom = 1; dots[0] = []; dots[1] = []; playing = false; layout(); opt.onTick(0, false); },
      play() { if (!data) return; if (at >= data.weeks.length - 1) at = 0; playing = true; opt.onTick(index(), true); },   // tell the page at once, so the button reads Pause
      pause() { playing = false; if (data) opt.onTick(index(), false); },
      seek(i) { at = i; split = 1; if (data) opt.onTick(index(), playing); },
      playing: () => playing,
      readTheme() { readTheme(); layout(); },
    };
  }

  window.HGTwin = { create };
})();
