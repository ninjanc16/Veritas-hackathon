/*
  twin.js: the picture of the simulation. The same district (or group of districts), twice.

      left    if nothing is done to the canals
      right   if canals are sealed when the forecast warns

  Both sides get the same reservoir, the same weather and the same weeks.

  HOW TO READ IT (the picture is kept deliberately simple)
    - At the top is the one thing that drives everything: how full the reservoir is.
    - Each district shape is a gauge. The green part, rising from the bottom, is the share
      of the water farms asked for that reached them this week. The brown part is what did
      not arrive. More green on the right means sealing got more water to the farms.
    - Canal lines are red while they leak and white once they are sealed.
    - Under each side are three plain numbers: water reaching farms, crops lost or saved,
      and water leaked or saved, in gallons.

  Every number comes from sim/engine.js. Nothing in the picture is measured in the field.

  window.HGTwin.create({ canvas, stage, onTick }) returns { load, play, pause, seek, playing, readTheme }.
*/
(function () {
  "use strict";
  const GALLONS_PER_ACRE_FOOT = 325851;

  function create(opt) {
    const canvas = opt.canvas, stage = opt.stage, ctx = canvas.getContext("2d");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const SECONDS = 34;                       // how long the whole run takes to play
    let W = 0, H = 0, dpr = 1, data = null, at = 0, playing = false, last = 0;
    let shape = null;                         // the districts as flat shapes
    let panels = [];                          // the two drawing areas, rebuilt on resize
    const shown = [1, 1];                     // the green level drawn on each side (it glides to the real value)
    const C = {};

    function readTheme() {
      const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      Object.assign(C, { map: css("--map"), card: css("--card"), text: css("--ink"), head: css("--head"), muted: css("--muted"),
                         rule: css("--line"), accent: css("--blue"), hl: css("--hl"), low: css("--low"), watch: css("--watch"),
                         warning: css("--warning"), wet: css("--wet"), dry: css("--dry"), serif: css("--serif"), sans: css("--sans") });
    }
    readTheme();

    /* ---------- The districts as flat shapes ----------
       Longitude and latitude become kilometres east and south of each district's centre.
       One district keeps its real shape. Several are laid out in a grid, each scaled to
       fill its own cell, so small districts stay readable (they are not to scale). */
    function build(d) {
      const flatPart = (part) => {
        let lon0 = 0, lat0 = 0, n = 0;
        part.rings.forEach((r) => r.forEach((p) => { lon0 += p[0]; lat0 += p[1]; n++; }));
        lon0 /= n; lat0 /= n;
        const kx = 111.32 * Math.cos(lat0 * Math.PI / 180), ky = 110.57;
        const flat = (line) => line.map((p) => [(p[0] - lon0) * kx, -(p[1] - lat0) * ky]);
        const rings = part.rings.map(flat); let half = 0;
        rings.forEach((r) => r.forEach((p) => { half = Math.max(half, Math.abs(p[0]), Math.abs(p[1])); }));
        return { rings, half, canals: part.canals.map((c) => ({ pts: flat(c.line), funded: c.funded, ranked: c.ranked })) };
      };
      const parts = d.parts.slice().sort((a, b) => (b.km || 0) - (a.km || 0)).map(flatPart);
      const many = parts.length > 1, cols = Math.ceil(Math.sqrt(parts.length * 0.8));
      const box = [1e9, 1e9, -1e9, -1e9];
      parts.forEach((part, k) => {
        const f = many ? 0.44 / part.half : 1, ox = many ? k % cols : 0, oy = many ? Math.floor(k / cols) : 0;
        const move = (line) => line.map((q) => [q[0] * f + ox, q[1] * f + oy]);
        part.rings = part.rings.map(move);
        part.canals.forEach((c) => { c.pts = move(c.pts); });
        part.top = 1e9; part.bottom = -1e9;                          // how tall this district is, for its gauge
        part.rings.forEach((r) => r.forEach((p) => {
          part.top = Math.min(part.top, p[1]); part.bottom = Math.max(part.bottom, p[1]);
          box[0] = Math.min(box[0], p[0]); box[1] = Math.min(box[1], p[1]); box[2] = Math.max(box[2], p[0]); box[3] = Math.max(box[3], p[1]);
        }));
      });
      return { parts, box };
    }

    /* ---------- Layout: two panels side by side (stacked on a phone) ---------- */
    function layout() {
      const r = stage.getBoundingClientRect();
      if (!r.width || !r.height) return;
      W = r.width; H = r.height; dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = W * dpr; canvas.height = H * dpr;
      if (!shape) return;
      // bottom: room for the play bar and, above it, the caption the page puts on the picture (two lines on a phone).
      const narrow = W < 620, top = narrow ? 104 : 118, bottom = narrow ? 100 : 82, gap = 12, side = 14;
      const boxes = narrow
        ? [0, 1].map((k) => ({ x: side, y: top + k * ((H - top - bottom + gap) / 2), w: W - 2 * side, h: (H - top - bottom - gap) / 2 }))
        : [0, 1].map((k) => ({ x: side + k * ((W - 2 * side + gap) / 2), y: top, w: (W - 2 * side - gap) / 2, h: H - top - bottom }));
      panels = boxes.map((b) => {
        // The districts sit above the three numbers; on a phone they sit to the left of them.
        const head = 40, foot = narrow ? 8 : 132, mw = narrow ? b.w * 0.36 : b.w - 24, mh = b.h - head - foot;
        const k = Math.min(mw / (shape.box[2] - shape.box[0]), mh / (shape.box[3] - shape.box[1])) * 0.94;
        const cx = (shape.box[0] + shape.box[2]) / 2, cy = (shape.box[1] + shape.box[3]) / 2, mx = narrow ? 10 + mw / 2 : b.w / 2;
        const sx = (x) => (x - cx) * k + mx, sy = (y) => (y - cy) * k + head + mh / 2;     // relative to the panel corner
        const path = (lines, close) => { const p = new Path2D(); lines.forEach((l) => { l.forEach((q, i) => (i ? p.lineTo(sx(q[0]), sy(q[1])) : p.moveTo(sx(q[0]), sy(q[1])))); if (close) p.closePath(); }); return p; };
        const canals = [].concat.apply([], shape.parts.map((part) => part.canals));
        return Object.assign({ narrow, head, foot, mw, mh,
          parts: shape.parts.map((part) => ({ path: path(part.rings, true), top: sy(part.top), bottom: sy(part.bottom) })),
          outline: path([].concat.apply([], shape.parts.map((part) => part.rings)), true),
          all: path(canals.filter((c) => c.ranked).map((c) => c.pts)),          // canals the model can rank
          other: path(canals.filter((c) => !c.ranked).map((c) => c.pts)),       // canals with no soil reading
          funded: path(canals.filter((c) => c.funded).map((c) => c.pts)) }, b);
      });
    }
    new ResizeObserver(layout).observe(stage);

    /* ---------- The week being shown ---------- */
    const index = () => Math.min(data.weeks.length - 1, Math.floor(at));
    /* Share of the water farms asked for that reached them. null = outside the irrigation season. */
    function arrives(w, s) { return w.demand > 0 ? Math.max(0, 1 - (s.missing - s.recovered) / w.demand) : null; }

    /* ---------- Words and numbers ---------- */
    function text(s, x, y, size, color, o) {
      o = o || {};
      ctx.font = (o.weight || 400) + " " + size + "px " + (o.serif ? C.serif : C.sans);
      ctx.textAlign = o.align || "left"; ctx.textBaseline = "middle"; ctx.globalAlpha = o.alpha == null ? 1 : o.alpha;
      ctx.fillStyle = color; ctx.fillText(s, x, y);
    }
    const money = (v) => (v >= 1e9 ? "$" + (v / 1e9).toFixed(2) + " billion" : v >= 1e6 ? "$" + (v / 1e6).toFixed(v >= 1e8 ? 0 : 1) + " million" : "$" + Math.round(v).toLocaleString("en-US"));
    function gallons(acreFeet) {
      const g = acreFeet * GALLONS_PER_ACRE_FOOT;
      return g >= 1e9 ? (g / 1e9).toFixed(g >= 1e10 ? 0 : 1) + " billion gallons" : g >= 1e6 ? Math.round(g / 1e6) + " million gallons" : Math.round(g).toLocaleString("en-US") + " gallons";
    }

    function drawPanel(p, k, w, dt) {
      const s = k ? w.right : w.left, sum = k ? w.sumR : w.sumL, share = arrives(w, s), right = k === 1;
      ctx.save(); ctx.translate(p.x, p.y);
      ctx.globalAlpha = 1; ctx.fillStyle = C.card; ctx.fillRect(0, 0, p.w, p.h);
      ctx.strokeStyle = right ? C.low : C.rule; ctx.lineWidth = right ? 2 : 1; ctx.strokeRect(0.5, 0.5, p.w - 1, p.h - 1);
      text(right ? "If canals are sealed early" : "If nothing is done", 14, 20, p.narrow ? 15 : 18, right ? C.low : C.head, { weight: 600, serif: true });

      // 1. Each district is a gauge: green from the bottom up for the water that arrived.
      //    The level glides to its new value so it does not jump from week to week.
      const want = share == null ? 1 : share;
      shown[k] = reduced ? want : shown[k] + (want - shown[k]) * Math.min(1, dt * 6);
      for (const part of p.parts) {
        ctx.save(); ctx.clip(part.path, "evenodd");
        const height = part.bottom - part.top, level = part.bottom - height * shown[k];
        ctx.globalAlpha = share == null ? 0.35 : 1;                  // faded outside the season: fields are resting
        ctx.fillStyle = C.dry; ctx.fillRect(0, part.top - 2, p.w, height + 4);
        ctx.fillStyle = C.wet; ctx.fillRect(0, level, p.w, part.bottom - level + 2);
        ctx.restore();
      }
      // 2. Canals over the top: red while they leak, white once sealed. Then the outline.
      ctx.lineJoin = ctx.lineCap = "round";
      ctx.globalAlpha = 0.3; ctx.strokeStyle = C.map; ctx.lineWidth = 0.8; ctx.stroke(p.other);
      ctx.globalAlpha = share == null ? 0.4 : 0.9; ctx.strokeStyle = C.warning; ctx.lineWidth = 1.2; ctx.stroke(p.all);
      if (s.sealed) { ctx.globalAlpha = 1; ctx.strokeStyle = C.hl; ctx.lineWidth = 1.5; ctx.stroke(p.funded); }
      ctx.globalAlpha = 0.95; ctx.strokeStyle = C.text; ctx.lineWidth = 1.4; ctx.stroke(p.outline);
      if (right && s.sealed) text("canals sealed", p.w - 14, 20, 13, C.hl, { weight: 600, align: "right" });

      // 3. Three plain numbers. Label on the left, value on the right.
      const rows = [
        ["Share of the water farms asked for that arrives", share == null ? "off season" : Math.round(share * 100) + "%", share == null ? C.muted : share > 0.999 ? C.low : right && share > arrives(w, w.left) + 0.005 ? C.watch : C.warning],
        right ? ["Crops saved so far", money(Math.max(0, w.sumL.loss - w.sumR.loss)), C.low] : ["Crops lost so far", money(sum.loss), C.warning],
        right ? ["Water saved from leaking", gallons(sum.saved), C.low] : ["Water leaked out of canals", gallons(sum.leak), C.warning],
      ];
      if (p.narrow) {
        const x = 10 + p.mw + 14, step = (p.h - p.head) / 3;
        rows.forEach((r, n) => { const y = p.head + step * n + step / 2; text(n ? r[0] : "Water reaching farms", x, y - 9, 11.5, C.muted); text(r[1], x, y + 9, n === 1 ? 17 : 14, r[2], { weight: 600 }); });
      } else {
        const y0 = p.h - p.foot + 22;
        rows.forEach((r, n) => {
          const y = y0 + n * 38;
          ctx.globalAlpha = 1; ctx.fillStyle = C.rule; ctx.fillRect(14, y - 19, p.w - 28, 1);
          text(r[0], 14, y, 14, C.muted); text(r[1], p.w - 14, y, n === 1 ? 22 : 16, r[2], { weight: 600, align: "right", serif: n === 1 });
        });
      }
      ctx.restore();
    }

    function draw(dt) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
      if (!data || !panels.length) return;
      const i = index(), w = data.weeks[i], narrow = panels[0].narrow, y = narrow ? 76 : 80;
      // The driver, at the top: the date, and how full the reservoir is, as a bar with the
      // level marked below which farms start getting less than they asked for.
      const month = new Date(w.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", year: "numeric" });
      text(month, 14, y, narrow ? 20 : 26, C.head, { weight: 600, serif: true });
      const bw = narrow ? W - 150 : Math.min(360, W * 0.34), bx = W - 14 - bw, short = w.pct < data.fullAt;
      ctx.globalAlpha = 1; ctx.fillStyle = C.card; ctx.fillRect(bx, y - 2, bw, 10);
      ctx.fillStyle = short ? C.warning : C.accent; ctx.fillRect(bx, y - 2, bw * Math.max(0, Math.min(1, w.pct / 100)), 10);
      ctx.fillStyle = C.text; ctx.fillRect(bx + bw * data.fullAt / 100, y - 6, 1.5, 18);
      text("Reservoir " + Math.round(w.pct) + "% full", bx, y - 16, 13.5, short ? C.warning : C.text, { weight: 600 });
      if (!narrow) text("below the mark (" + data.fullAt + "%), farms get less water than they asked for", bx + bw, y + 22, 12, C.muted, { align: "right" });
      panels.forEach((p, k) => drawPanel(p, k, w, dt));
      // The result, once the run has finished.
      if (i >= data.weeks.length - 1) {
        const diff = (w.sumL.loss + w.sumL.spend) - (w.sumR.loss + w.sumR.spend), small = Math.abs(diff) < 1000;
        const label = small ? "No measurable difference" : "Sealing early " + (diff > 0 ? "saves " : "costs ") + money(Math.abs(diff)) + (diff > 0 ? "" : " more");
        const size = narrow ? 15 : 20, color = small ? C.muted : diff > 0 ? C.low : C.warning;
        ctx.font = "600 " + size + "px " + C.serif;
        const tw = ctx.measureText(label).width + 30, ty = narrow ? panels[1].y - 6 : panels[0].y + 62;
        ctx.globalAlpha = 1; ctx.fillStyle = C.map; ctx.strokeStyle = color; ctx.lineWidth = 2;
        ctx.fillRect(W / 2 - tw / 2, ty - 20, tw, 40); ctx.strokeRect(W / 2 - tw / 2, ty - 20, tw, 40);
        text(label, W / 2, ty, size, color, { weight: 600, align: "center", serif: true });
      }
    }

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000 || 0); last = now;
      if (data && stage.offsetParent !== null && canvas.offsetParent !== null) {
        if (playing) {
          at = Math.min(data.weeks.length - 1, at + dt * data.weeks.length / SECONDS);
          if (at >= data.weeks.length - 1) playing = false;
          opt.onTick(index(), playing);
        }
        draw(dt);
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return {
      /* next: { parts: [{ rings, km, canals: [{ line, ranked, funded }] }], fullAt,
                 weeks: [{ date, pct, demand, left, right, sumL, sumR }] }
         left / right are the engine's weekly rows; sumL / sumR are running totals with
         loss ($), spend ($), saved, recovered and leak (acre-feet). */
      load(next) { data = next; shape = build(next); at = 0; shown[0] = shown[1] = 1; playing = false; layout(); opt.onTick(0, false); },
      play() { if (!data) return; if (at >= data.weeks.length - 1) at = 0; playing = true; opt.onTick(index(), true); },   // tell the page at once, so the button reads Pause
      pause() { playing = false; if (data) opt.onTick(index(), false); },
      seek(i) { at = i; if (data) opt.onTick(index(), playing); },
      playing: () => playing,
      readTheme() { readTheme(); layout(); },
    };
  }

  window.HGTwin = { create };
})();
