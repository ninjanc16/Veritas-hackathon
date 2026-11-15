/*
  fork.js: "The Fork", the moving picture of the simulation (from the team's simulation design).

  One river runs down the screen and splits into two channels:
      left   what happens if nothing is done
      right  what happens if canals are sealed when the forecast warns

  Both channels get the same reservoir, the same drought and the same weeks.
    - The WIDTH of a channel is the share of the water farms asked for that actually arrived.
    - Blue dots are water. Brown dots peel off and sink: water lost through canal beds.
      While the right channel is sealed, fewer dots peel off.
    - Gold dots are public money: into the canals before the season on the right, and
      relief paid to farms after a loss on either side.

  The dots are a picture, not a measurement. The numbers come from sim/engine.js and are
  shown in the ledger that platform.js draws on top.

  window.HGFork.create({ canvas, stage, onTick }) returns { load, play, pause, seek, playing }.
*/
(function () {
  "use strict";

  function create(opt) {
    const canvas = opt.canvas, stage = opt.stage, ctx = canvas.getContext("2d");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const WEEKS_PER_SECOND = 9, MAX_DOTS = 700;
    let W = 0, H = 0, dpr = 1, data = null, at = 0, playing = false, last = 0, dots = [], spawnDebt = 0, lastWeek = -1;
    const C = {};
    function readTheme() {
      const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      Object.assign(C, { water: css("--river"), bed: css("--casing"), leak: css("--inspect"), gold: css("--watch"), text: css("--ink"),
                         muted: css("--muted"), rule: css("--line"), map: css("--map"), act: css("--fund"), serif: css("--serif") });
    }
    readTheme();

    function resize() {
      const r = stage.getBoundingClientRect();
      if (!r.width || !r.height) return;
      W = r.width; H = r.height; dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = W * dpr; canvas.height = H * dpr;
      narrow = W < 520;                                              // on a phone, leave room for the buttons
      TOP = narrow ? 0.25 : 0.13; FORK = TOP + 0.14; SPLIT = TOP + 0.33; END = narrow ? 0.76 : 0.86;
    }
    new ResizeObserver(resize).observe(stage);

    /* ---------- Geometry: where a channel is, for a position t from 0 (top) to 1 (bottom) ---------- */
    let TOP = 0.13, FORK = 0.27, SPLIT = 0.46, END = 0.86, narrow = false;   // as shares of the height
    const smooth = (u) => { u = Math.max(0, Math.min(1, u)); return u * u * (3 - 2 * u); };
    const spread = () => Math.min(W * 0.27, 300);
    function centre(side, t) {                                         // side: -1 left, +1 right
      const y = H * (TOP + (END - TOP) * t);
      return [W / 2 + side * spread() * smooth((y / H - FORK) / (SPLIT - FORK)), y];
    }
    const fullWidth = () => Math.max(26, Math.min(W * 0.11, 84));     // channel width when every drop arrives

    /* The week being shown, and each side's numbers for it. */
    const week = () => data.weeks[Math.min(data.weeks.length - 1, Math.floor(at))];
    function share(side) {                                             // share of the water asked for that arrives
      const w = week(), s = side < 0 ? w.left : w.right;
      return w.demand > 0 ? Math.max(0, 1 - (s.missing - s.recovered) / w.demand) : null;   // null = outside the season
    }

    /* ---------- Dots ---------- */
    function spawn(kind, side, extra) {
      if (dots.length >= MAX_DOTS) return;
      dots.push(Object.assign({ kind, side, t: 0, off: (Math.random() - 0.5), speed: 0.16 + Math.random() * 0.08, life: 1, drift: 0 }, extra || {}));
    }
    function step(dt) {
      const w = week();
      // Water: a steady stream, split evenly. A dot only enters a channel if that water arrives.
      spawnDebt += dt * 70;
      while (spawnDebt >= 1) {
        spawnDebt -= 1;
        const side = Math.random() < 0.5 ? -1 : 1, s = share(side);
        spawn("water", side, { dries: Math.random() > (s == null ? 0.18 : s) });
      }
      // Money moves when the week changes: sealing before the season, relief after a loss.
      const index = Math.floor(at);
      if (index !== lastWeek) {
        lastWeek = index;
        for (const side of [-1, 1]) {
          const s = side < 0 ? w.left : w.right;
          if (s.spend > 0) for (let i = 0; i < 26; i++) spawn("gold", side, { t: -0.1 - Math.random() * 0.25, to: "canal", speed: 0.5 });
          if (s.relief > 0) for (let i = 0; i < Math.min(30, 4 + Math.round(s.relief / data.reliefUnit)); i++) spawn("gold", side, { t: -0.1 - Math.random() * 0.4, to: "farm", speed: 0.55 });
        }
      }
      for (const d of dots) {
        if (d.kind === "water") {
          d.t += d.speed * dt;
          const y = TOP + (END - TOP) * d.t;
          if (d.dries && y > FORK) d.life -= dt * 2.2;                 // water that never arrived fades at the fork
          const sealed = (d.side < 0 ? w.left : w.right).sealed;
          // Leaks: an unsealed channel loses dots steadily; a sealed one loses far fewer.
          if (!d.dries && y > SPLIT && Math.random() < dt * (sealed ? 0.05 : 0.2)) { d.kind = "leak"; d.drift = (Math.random() < 0.5 ? -1 : 1) * (20 + Math.random() * 30); }
          if (d.t >= 1) d.life = 0;
        } else if (d.kind === "leak") {
          d.t += d.speed * dt * 0.25; d.off += d.drift * dt / fullWidth(); d.life -= dt * 0.9;
        } else {                                                       // gold
          d.t += d.speed * dt;
          if (d.t >= 1) d.life = 0;
        }
      }
      dots = dots.filter((d) => d.life > 0);
    }

    /* ---------- One frame ---------- */
    function ribbon(side, widthAt, color, alpha) {                     // a channel as a filled band
      ctx.beginPath();
      for (let i = 0; i <= 40; i++) { const t = i / 40, p = centre(side, t); ctx.lineTo(p[0] - widthAt(t) / 2, p[1]); }
      for (let i = 40; i >= 0; i--) { const t = i / 40, p = centre(side, t); ctx.lineTo(p[0] + widthAt(t) / 2, p[1]); }
      ctx.closePath(); ctx.fillStyle = color; ctx.globalAlpha = alpha; ctx.fill();
    }
    function text(s, x, y, size, color, o) {
      o = o || {};
      ctx.font = (o.weight || 500) + " " + size + "px " + C.serif; ctx.textAlign = o.align || "center"; ctx.textBaseline = "middle";
      ctx.globalAlpha = o.alpha == null ? 1 : o.alpha; ctx.fillStyle = color; ctx.fillText(s, x, y);
    }
    function draw() {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.globalAlpha = 1; ctx.clearRect(0, 0, W, H);
      if (!data) return;
      const w = week(), full = fullWidth();
      // The reservoir at the top: a bar that fills to today's level in this future.
      const rw = Math.min(W * 0.5, 360), rx = W / 2 - rw / 2, ry = H * TOP - 34;
      ctx.globalAlpha = 1; ctx.fillStyle = C.bed; ctx.fillRect(rx, ry, rw, 16);
      ctx.fillStyle = C.water; ctx.fillRect(rx, ry, rw * Math.max(0, Math.min(1, w.pct / 100)), 16);
      ctx.strokeStyle = C.rule; ctx.lineWidth = 1; ctx.strokeRect(rx + 0.5, ry + 0.5, rw - 1, 15);
      text(data.system + " reservoirs: " + w.pct.toFixed(1) + "% full", W / 2, ry - 12, 14, C.text, { weight: 700 });

      for (const side of [-1, 1]) {
        const s = share(side), state = side < 0 ? w.left : w.right;
        ribbon(side, () => full, C.bed, 0.9);                          // the dry bed: how wide it would be with all the water
        const wet = s == null ? 0.16 : s;
        ribbon(side, (t) => full * (TOP + (END - TOP) * t < FORK ? 1 : wet), side > 0 && state.sealed ? C.act : C.water, 0.34);
        const foot = centre(side, 1);
        text(side < 0 ? data.leftName : (narrow ? "Act early" : data.rightName), foot[0], H * END + 22, 16, C.text, { weight: 700 });
        text(s == null ? (narrow ? "off season" : "outside the irrigation season") : Math.round(s * 100) + (narrow ? "% of water arrives" : "% of the water farms asked for arrives"), foot[0], H * END + 42, 12.5, s != null && s < 0.999 ? C.gold : C.muted);
        if (side > 0 && state.sealed) text("canals sealed", narrow ? foot[0] : foot[0] + full / 2 + 10, narrow ? H * END + 60 : H * (SPLIT + 0.12), 12.5, C.act, { align: narrow ? "center" : "left", weight: 700 });
      }
      // Dots.
      for (const d of dots) {
        if (d.kind === "gold") {
          const end = centre(d.side, d.to === "canal" ? 0.3 : 1), sx = W / 2 + d.side * (W / 2 - 30), sy = H * 0.06;
          const u = Math.max(0, d.t), x = sx + (end[0] - sx) * u, y = sy + (end[1] - sy) * u * u;
          if (d.t < 0) continue;
          ctx.globalAlpha = 0.95; ctx.fillStyle = C.gold; ctx.fillRect(x - 2, y - 2, 4, 4);
          continue;
        }
        const p = centre(d.side, d.t), s = share(d.side), wide = TOP + (END - TOP) * d.t < FORK ? full : full * (d.kind === "leak" ? 1 : (s == null ? 0.16 : Math.max(0.1, s)));
        ctx.globalAlpha = Math.max(0, Math.min(1, d.life)) * (d.kind === "leak" ? 0.9 : 0.85);
        ctx.fillStyle = d.kind === "leak" ? C.leak : C.water;
        ctx.beginPath(); ctx.arc(p[0] + d.off * wide * 0.8, p[1], d.kind === "leak" ? 1.7 : 2, 0, 7); ctx.fill();
      }
      ctx.globalAlpha = 1;
    }

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000 || 0); last = now;
      if (data && stage.offsetParent !== null) {
        if (playing) {
          at = Math.min(data.weeks.length - 1, at + dt * WEEKS_PER_SECOND);
          if (at >= data.weeks.length - 1) playing = false;
          opt.onTick(Math.floor(at), playing);
        }
        if (!reduced) step(dt);
        draw();
      }
      requestAnimationFrame(frame);
    }
    resize();
    requestAnimationFrame(frame);

    return {
      /* weeks: [{ date, pct, demand, left: {missing, recovered, sealed, spend, relief}, right: {...} }] */
      load(next) { data = next; at = 0; dots = []; lastWeek = -1; playing = false; resize(); opt.onTick(0, false); },
      play() { if (!data) return; if (at >= data.weeks.length - 1) at = 0; playing = true; },
      pause() { playing = false; if (data) opt.onTick(Math.floor(at), false); },
      seek(i) { at = i; lastWeek = -1; if (data) opt.onTick(Math.floor(at), playing); },
      playing: () => playing,
      readTheme,
    };
  }

  window.HGFork = { create };
})();
