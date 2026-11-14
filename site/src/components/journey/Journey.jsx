import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useRef, useState } from 'react'
import { journey } from '../../content.js'
import map from '../../data/map.json'
import Hero from './Hero.jsx'
import Widget from './Widgets.jsx'

const CHAPTERS = journey.chapters
const N = CHAPTERS.length
// River position each chapter ends on. Place chapters stop at their station;
// the closing chapters stay at the sea and look back at the whole river.
const STOPS = CHAPTERS.map((c) => map.stations.find((s) => s.id === c.id)?.frac ?? 1)
const LAST_PLACE = CHAPTERS.findLastIndex((c) => map.stations.some((s) => s.id === c.id))
const REACH_AT = map.stations.find((s) => s.id === 'reach').at

const HERO_END = 0.07 // share of the scroll spent on the title page
const SPAN = (1 - HERO_END) / N // share of the scroll per chapter
const TRAVEL = 0.55 // first part of a chapter is the trip; the rest is the stop
const DROPLETS = 9

const clamp01 = (v) => Math.max(0, Math.min(1, v))
const seg = (p, a, b) => clamp01((p - a) / (b - a))
const lerp = (a, b, t) => a + (b - a) * t
const easeOut = (t) => 1 - Math.pow(1 - t, 3)
const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)

function toLatLon(x, y) {
  const { k, tx, ty } = map.proj
  const lon = ((x - tx) / k) * (180 / Math.PI)
  const lat = (2 * Math.atan(Math.exp(-(y - ty) / k)) - Math.PI / 2) * (180 / Math.PI)
  return `${lat.toFixed(2)}°N  ${Math.abs(lon).toFixed(2)}°W`
}

/**
 * The opening of the site: one pinned screen the reader scrolls through.
 *
 * Title page      -> the camera falls through the word RIO into the map
 * Nine stops      -> source to sea; at each, one pressure on the river is named
 * Four steps back -> the 31 counties, the problem, the trigger, the idea
 *
 * Everything that moves every frame is written straight to the DOM from one
 * animation loop. React only re-renders when the chapter changes.
 */
export default function Journey() {
  const section = useRef(null)
  const stage = useRef(null)
  const heroApi = useRef(null)
  const mapLayer = useRef(null)
  const svg = useRef(null)
  const cam = useRef(null)
  const river = useRef(null)
  const drawn = useRef([])
  const dry = useRef(null)
  const head = useRef(null)
  const drops = useRef([])
  const countyEls = useRef([])
  const timed = useRef([]) // everything that appears when the river reaches it
  const count = useRef(null)
  const latest = useRef(null)
  const coords = useRef(null)
  const ghost = useRef(null)
  const bar = useRef(null)
  const glow = useRef(null)
  const [chapter, setChapter] = useState(-1)
  const [tip, setTip] = useState(null)

  useEffect(() => {
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const total = river.current.getTotalLength()
    const timedEls = timed.current.filter(Boolean)
    let vw = 0
    let vh = 0
    let k0 = 1
    let kz = 1
    let anchor = [0, 0]
    let anchorOut = [0, 0]
    let iris = [0, 0] // where the map opens from: the letter I of RIO
    let irisReach = 0 // radius at which the circle covers the whole screen
    let camNow = null
    let lit = 0
    let shown = -2
    let raf = 0
    let running = false
    let lastTime = 0
    let disposed = false

    function measure() {
      vw = stage.current.clientWidth
      vh = stage.current.clientHeight
      const wide = vw >= 1024
      k0 = wide ? Math.min((vw * 0.5) / map.width, (vh * 0.8) / map.height) : Math.min((vw * 0.94) / map.width, (vh * 0.42) / map.height)
      kz = k0 * (wide ? 4.2 : 4.6)
      anchor = wide ? [vw * 0.67, vh * 0.52] : [vw * 0.5, vh * 0.27]
      // On a phone the closing panels are tall, so the overview sits higher and smaller.
      anchorOut = wide ? anchor : [vw * 0.5, vh * 0.2]
      if (!wide) k0 = Math.min((vw * 0.94) / map.width, (vh * 0.26) / map.height)
      iris = heroApi.current?.measure() ?? [vw / 2, vh / 2]
      irisReach = Math.hypot(Math.max(iris[0], vw - iris[0]), Math.max(iris[1], vh - iris[1])) + 4
    }

    function tick(time) {
      const rect = section.current.getBoundingClientRect()
      const p = clamp01(-rect.top / (rect.height - vh))
      bar.current.style.transform = `scaleX(${p})`

      // 1. Title page: the map opens over it as a circle growing out of a letter.
      const fall = seg(p, 0, HERO_END)
      heroApi.current?.update(fall)
      const open = Math.pow(seg(fall, 0.08, 1), 2.2)
      mapLayer.current.style.clipPath = fall >= 1 ? 'none' : `circle(${(irisReach * open).toFixed(1)}px at ${iris[0]}px ${iris[1]}px)`

      // 2. Which chapter, and how far through it.
      const raw = (p - HERO_END) / SPAN
      const i = p < HERO_END ? -1 : Math.min(N - 1, Math.floor(raw))
      const u = i < 0 ? 0 : clamp01(raw - i)
      const trip = i <= 0 ? 1 : easeInOut(seg(u, 0, TRAVEL))
      const from = i <= 0 ? 0 : STOPS[i - 1]
      const to = i < 0 ? 0 : STOPS[i]
      const t = lerp(from, to, trip)

      // 3. The river, its head and the water running down it.
      for (const el of drawn.current) el.style.strokeDashoffset = String(1 - t)
      dry.current.style.strokeDashoffset = String(1 - seg(t, map.dryReach.from, map.dryReach.to))
      const pt = river.current.getPointAtLength(total * t)
      head.current.setAttribute('transform', `translate(${pt.x} ${pt.y})`)
      if (!still && t > 0.002) {
        drops.current.forEach((el, n) => {
          const along = ((time / 6000 + n / DROPLETS) % 1) * t
          const d = river.current.getPointAtLength(total * along)
          el.setAttribute('transform', `translate(${d.x} ${d.y})`)
          // Water thins out through the Forgotten Reach.
          const parched = along > map.dryReach.from && along < map.dryReach.to ? 0.15 : 1
          el.style.opacity = String(Math.min(1, along * 40, (t - along) * 40) * parched)
        })
      }

      // 4. The camera. It lifts as it travels and settles in close at each stop;
      //    after the sea it rises until the whole river is in view.
      const out = i > LAST_PLACE + 1 ? 1 : i === LAST_PLACE + 1 ? easeInOut(seg(u, 0, 0.6)) : 0
      const hop = i > 0 && i <= LAST_PLACE ? Math.sin(Math.PI * trip) * Math.min(0.62, 0.3 + (to - from) * 1.6) : 0
      const arrive = i < 0 ? seg(fall, 0.1, 1) * 0.5 : i === 0 ? 0.5 + seg(u, 0, 0.5) * 0.5 : 1
      const dive = 1 + 1.4 * (1 - easeOut(arrive))
      const want = {
        x: lerp(pt.x, map.width / 2, out),
        y: lerp(pt.y, map.height / 2, out),
        k: lerp(kz * (1 - hop) * dive, k0, out),
      }
      const dt = Math.min(200, time - lastTime)
      lastTime = time
      const follow = still || !camNow ? 1 : 1 - Math.exp(-dt / 150)
      camNow = camNow
        ? { x: lerp(camNow.x, want.x, follow), y: lerp(camNow.y, want.y, follow), k: lerp(camNow.k, want.k, follow) }
        : want
      cam.current.setAttribute('transform', `translate(${lerp(anchor[0], anchorOut[0], out)} ${lerp(anchor[1], anchorOut[1], out)}) scale(${camNow.k}) translate(${-camNow.x} ${-camNow.y})`)
      svg.current.style.setProperty('--k', String(camNow.k))

      // 5. Counties, towns, tributaries and reservoirs appear as the river reaches them.
      const reach = t + 0.006
      const before = lit
      while (lit < map.counties.length && t > 0 && map.counties[lit].frac <= reach) countyEls.current[lit++].classList.add('lit')
      while (lit > 0 && (t === 0 || map.counties[lit - 1].frac > reach)) countyEls.current[--lit].classList.remove('lit')
      if (lit !== before) {
        count.current.textContent = String(lit).padStart(2, '0')
        const c = map.counties[lit - 1]
        latest.current.textContent = c ? `${c.name} County, ${c.state}` : ''
      }
      for (const el of timedEls) el.classList.toggle('lit', t > 0 && Number(el.dataset.frac) <= reach)
      coords.current.textContent = toLatLon(pt.x, pt.y)

      // 6. The big word behind the map drifts across as the chapter is read.
      ghost.current.style.transform = `translate3d(${lerp(5, -9, u)}vw, 0, 0)`

      if (i !== shown) {
        shown = i
        setChapter(i)
      }
      if (running) raf = requestAnimationFrame(tick)
    }

    function onPointer(ev) {
      heroApi.current?.point((ev.clientX / vw) * 2 - 1, (ev.clientY / vh) * 2 - 1)
      if (glow.current) glow.current.style.transform = `translate3d(${ev.clientX - 260}px, ${ev.clientY - 260}px, 0)`
    }

    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !running) {
        running = true
        raf = requestAnimationFrame(tick)
      } else if (!entry.isIntersecting) {
        running = false
        cancelAnimationFrame(raf)
      }
    })
    // Phones fire "resize" whenever the address bar shows or hides, which is
    // every time the reader scrolls back up. Only a real change of size counts.
    const onResize = () => {
      if (stage.current.clientWidth === vw && stage.current.clientHeight === vh) return
      measure()
      camNow = null
    }

    measure()
    // Letter positions shift when the display font arrives.
    document.fonts?.ready.then(() => !disposed && measure())
    io.observe(section.current)
    window.addEventListener('resize', onResize)
    if (!still) window.addEventListener('pointermove', onPointer, { passive: true })
    return () => {
      disposed = true
      running = false
      cancelAnimationFrame(raf)
      io.disconnect()
      window.removeEventListener('resize', onResize)
      window.removeEventListener('pointermove', onPointer)
    }
  }, [])

  /** Scroll so that chapter `i` is at rest on screen. Used by the chapter rail. */
  function goTo(i) {
    const el = section.current
    const y = el.offsetTop + (el.offsetHeight - window.innerHeight) * (HERO_END + SPAN * (i + 0.8))
    window.scrollTo({ top: y })
  }

  const ch = CHAPTERS[chapter]
  const pressures = CHAPTERS.slice(0, Math.max(0, chapter + 1)).filter((c) => c.pressure)
  const addTimed = (el) => {
    if (el && !timed.current.includes(el)) timed.current.push(el)
  }
  const stageClass = ch ? `ch-${ch.id} ${chapter > LAST_PLACE ? 'whole' : 'place-stop'}` : ''

  return (
    <section ref={section} id="top" className="relative bg-night" style={{ height: `${100 + N * 105}svh` }} aria-label="The Rio Grande, from source to sea">
      <div ref={stage} className={'journey sticky top-0 h-svh overflow-hidden ' + stageClass}>
        <Hero ref={heroApi} />

        {/* ---- The map. It sits over the title page and opens through it as a
            growing circle (see step 1 of the loop). ---- */}
        <div ref={mapLayer} className="map-layer absolute inset-0">
          {/* ---- The big word behind the map ----
              The drift is applied to this wrapper, which never unmounts. (Putting the
              ref on the word itself broke on every chapter change: the old word's
              unmount cleared the ref the new word had just taken.) */}
          <div ref={ghost} className="ghost-drift pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
            {/* No exit animation on purpose. With one, a quick scroll left a dozen
                of these screen-sized words fading out on top of each other. */}
            {ch && (
              <motion.p key={ch.id} className="ghost-wrap" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.8 }}>
                <span className="ghost">{ch.ghost}</span>
              </motion.p>
            )}
          </div>

          <svg ref={svg} className="h-full w-full" role="img" aria-label={journey.mapLabel}>
            <g ref={cam}>
              <path d={map.mexico} className="mexico" />
              {map.states.map((s) => (
                <path key={s.name} d={s.d} className="state" />
              ))}
              {map.labels.concat(map.states.map((s) => ({ name: s.name, at: s.at }))).map((l) => (
                <text key={l.name} x={l.at[0]} y={l.at[1]} className="region-name" textAnchor="middle">
                  {l.name}
                </text>
              ))}
              {map.counties.map((c, i) => (
                <path
                  key={c.id}
                  ref={(el) => (countyEls.current[i] = el)}
                  d={c.d}
                  className="county"
                  onPointerEnter={(ev) => setTip({ text: `${c.name} County, ${c.state}`, x: ev.clientX, y: ev.clientY })}
                  onPointerMove={(ev) => setTip({ text: `${c.name} County, ${c.state}`, x: ev.clientX, y: ev.clientY })}
                  onPointerLeave={() => setTip(null)}
                />
              ))}
              {/* A second copy of each county, used only for the wave of light in the
                  last chapter, so that turning the wave on or off never restarts
                  the counties' own arrival animation. */}
              {map.counties.map((c) => (
                <path key={c.id} d={c.d} className="county-wave" style={{ '--wave': `${(c.frac * 2.4).toFixed(2)}s` }} />
              ))}
              {map.tributaries.map((tr) => (
                <path key={tr.name} ref={addTimed} data-frac={tr.frac} d={tr.d} pathLength="1" className="tributary" />
              ))}
              <path d={map.river} className="river-ghost" />
              <path ref={(el) => (drawn.current[0] = el)} d={map.river} pathLength="1" className="river-glow" />
              <path
                ref={(el) => {
                  drawn.current[1] = el
                  river.current = el
                }}
                d={map.river}
                pathLength="1"
                className="river-core"
              />
              <path ref={dry} d={map.dryReach.d} pathLength="1" className="river-dry" />
              {Array.from({ length: DROPLETS }, (_, i) => (
                <g key={i} ref={(el) => (drops.current[i] = el)} style={{ opacity: 0 }}>
                  <circle className="unscale drop" r="2.2" />
                </g>
              ))}
              {map.reservoirs.map((r) => (
                <g key={r.name} ref={addTimed} data-frac={r.frac} className="mark reservoir" transform={`translate(${r.at[0]} ${r.at[1]})`}>
                  <g className="unscale">
                    <rect x="-5" y="-5" width="10" height="10" transform="rotate(45)" />
                    <text x="0" y="22" textAnchor="middle">
                      {r.name} Reservoir
                    </text>
                  </g>
                </g>
              ))}
              {map.places.map((pl) => (
                <g key={pl.name} ref={addTimed} data-frac={pl.frac} className="mark place" transform={`translate(${pl.at[0]} ${pl.at[1]})`}>
                  <g className="unscale">
                    <circle r="2.6" />
                    <text x="9" y="4">
                      {pl.name}
                    </text>
                  </g>
                </g>
              ))}
              <g ref={addTimed} data-frac={map.dryReach.from + 0.03} className="mark dry-label" transform={`translate(${REACH_AT[0]} ${REACH_AT[1]})`}>
                <g className="unscale">
                  <text x="14" y="-12">
                    {journey.dryLabel}
                  </text>
                </g>
              </g>
              <g ref={head}>
                <g className="unscale head">
                  <circle className="pulse" r="18" />
                  <circle className="pulse pulse-2" r="18" />
                  <circle className="dot" r="5.5" />
                </g>
              </g>
            </g>
          </svg>
        </div>

        {/* ---- The story beside the river ---- */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 px-3 pb-5 sm:px-8 lg:inset-y-0 lg:right-auto lg:flex lg:w-[min(42vw,35rem)] lg:items-center lg:px-0 lg:pb-0 lg:pl-16">
          <AnimatePresence mode="wait">
            {ch && (
              <motion.article
                key={ch.id}
                className="panel pointer-events-auto w-full"
                initial={{ opacity: 0, y: 30, filter: 'blur(10px)' }}
                animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                exit={{ opacity: 0, y: -20, filter: 'blur(8px)' }}
                transition={{ duration: 0.42, ease: [0.16, 1, 0.3, 1] }}
              >
                <p className="label text-amber">
                  <span className="tabular-nums text-cream/55">
                    {String(chapter + 1).padStart(2, '0')}/{N}
                  </span>
                  &ensp;{ch.kicker}
                </p>
                <h2 className="mt-3 font-display text-[clamp(1.75rem,3.9vw,3.6rem)] font-light leading-[1.03] tracking-tight text-cream">{ch.title}</h2>
                {ch.body.map((text) => (
                  <p key={text} className="mt-3.5 max-w-md leading-relaxed text-cream/90 max-lg:text-[0.94rem] max-lg:leading-snug">
                    {text}
                  </p>
                ))}
                {ch.affects && (
                  <dl className="mt-5 grid max-w-md grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 border-t border-cream/15 pt-3 text-sm">
                    <dt className="text-cream/55">{journey.affectsLabel}</dt>
                    <dd className="text-cream">{ch.affects}</dd>
                    <dt className="text-cream/55">{journey.sourceLabel}</dt>
                    <dd>
                      <a href={ch.source[1]} target="_blank" rel="noreferrer" className="text-cream/85 underline decoration-cream/30 underline-offset-4 hover:decoration-amber">
                        {ch.source[0]}
                      </a>
                    </dd>
                  </dl>
                )}
                <Widget chapter={ch} />
              </motion.article>
            )}
          </AnimatePresence>
        </div>

        {/* ---- Pressures collected so far ---- */}
        <aside className={'pressures absolute bottom-8 right-16 hidden w-64 transition-opacity duration-700 xl:block ' + (pressures.length && chapter <= LAST_PLACE ? 'opacity-100' : 'opacity-0')} aria-label={journey.pressuresTitle}>
          <p className="label text-cream/55">
            {journey.pressuresTitle} <span className="tabular-nums text-magenta">{String(pressures.length).padStart(2, '0')}</span>
          </p>
          <ol className="mt-2">
            {pressures.map((c, i) => (
              <li key={c.id} className={'pressure ' + (i === chapter ? 'now' : '')}>
                {c.pressure}
              </li>
            ))}
          </ol>
        </aside>

        {/* ---- Instrument readout ---- */}
        <div className={'label absolute right-4 top-[4.6rem] text-right text-cream/70 transition-opacity duration-500 sm:right-16 ' + (chapter >= 0 ? 'opacity-100' : 'opacity-0')} aria-hidden="true">
          <p ref={coords} className="tabular-nums text-jade" />
          <p className="mt-1">
            <span ref={count} className="tabular-nums text-cream">
              00
            </span>
            /{map.counties.length} {journey.reached}
          </p>
          <p ref={latest} className="mt-1 normal-case tracking-normal text-cream/55 max-sm:hidden" />
        </div>

        {/* ---- Chapter rail ---- */}
        <nav className={'rail absolute right-3 top-1/2 hidden -translate-y-1/2 transition-opacity duration-500 sm:block ' + (chapter >= 0 ? 'opacity-100' : 'pointer-events-none opacity-0')} aria-label="Chapters of the journey">
          <ol>
            {CHAPTERS.map((c, i) => (
              <li key={c.id}>
                <button type="button" onClick={() => goTo(i)} aria-current={i === chapter ? 'step' : undefined} className={i === chapter ? 'now' : i < chapter ? 'done' : ''}>
                  <span className="sr-only">
                    {i + 1}. {c.title}
                  </span>
                  <span className="rail-tip" aria-hidden="true">
                    {c.kicker.split(' · ')[0]}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </nav>

        {tip && (
          <p className="pointer-events-none fixed z-30 -translate-x-1/2 -translate-y-[160%] whitespace-nowrap bg-cream px-3 py-1.5 text-sm font-medium text-night" style={{ left: tip.x, top: tip.y }}>
            {tip.text}
          </p>
        )}

        <div ref={glow} className="cursor-glow" aria-hidden="true" />
        <div className="grain" aria-hidden="true" />
        <div ref={bar} className="absolute inset-x-0 bottom-0 h-[3px] origin-left scale-x-0 bg-amber" aria-hidden="true" />
      </div>
    </section>
  )
}
