import { AnimatePresence, motion } from 'framer-motion'
import { useEffect, useImperativeHandle, useRef, useState } from 'react'
import { hero } from '../../content.js'
import map from '../../data/map.json'

const clamp01 = (v) => Math.max(0, Math.min(1, v))
const seg = (p, a, b) => clamp01((p - a) / (b - a))
// The word only swells a little as the map opens through it. An earlier version
// scaled it 110x to "fall through" a letter; scrolling back up from that left
// the browser with a broken, half-drawn copy of the letters.
const SWELL = 1.9

/**
 * The title page. The river's name is cut out of the canyon photograph, the
 * river's real course is drawn beside it, and one line of its recent history
 * changes every few seconds.
 *
 * It does not animate itself on scroll: the journey's loop calls
 *   update(fall)  0 = title page at rest, 1 = the map has fully opened over it
 *   point(x, y)   pointer position, -1..1, for the photo inside the letters
 *   measure()     after a resize or a font load; returns where the map should
 *                 open from (the centre of the letter I), in stage pixels
 */
export default function Hero({ ref }) {
  const root = useRef(null)
  const word = useRef(null)
  const eye = useRef(null) // the letter the camera falls through
  const backdrop = useRef(null)
  const rest = useRef(null)
  const wrap = useRef(null)
  const script = useRef(null)
  const thread = useRef(null)
  const [line, setLine] = useState(0)

  useImperativeHandle(ref, () => {
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    return {
      measure() {
        // Layout offsets, not on-screen rectangles, so this is correct at any moment.
        const e = eye.current
        const w = wrap.current
        const x = e.offsetLeft + e.offsetWidth / 2
        const y = e.offsetTop + e.offsetHeight * 0.55
        word.current.style.transformOrigin = `${x}px ${y}px`
        return [w.offsetLeft + x, w.offsetTop + y]
      },
      update(fall) {
        const gone = fall >= 1
        root.current.style.visibility = gone ? 'hidden' : 'visible'
        if (gone) return
        const fade = String(1 - seg(fall, 0.02, 0.3))
        rest.current.style.opacity = fade
        script.current.style.opacity = fade
        const push = still ? 0 : Math.pow(seg(fall, 0.04, 1), 1.6)
        word.current.style.transform = `scale(${1 + (SWELL - 1) * push})`
      },
      point(x, y) {
        word.current.style.backgroundPosition = `${50 + x * 7}% ${46 + y * 7}%`
        backdrop.current.style.transform = `translate3d(${-x * 16}px, ${-y * 16}px, 0) scale(1.08)`
      },
    }
  }, [])

  // Draw the river's course once, on arrival.
  useEffect(() => {
    const el = thread.current
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.style.strokeDashoffset = '0'
      return
    }
    const start = performance.now() + 500
    let raf = requestAnimationFrame(function draw(now) {
      const t = clamp01((now - start) / 3400)
      el.style.strokeDashoffset = String(1 - (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2))
      if (t < 1) raf = requestAnimationFrame(draw)
    })
    return () => cancelAnimationFrame(raf)
  }, [])

  useEffect(() => {
    const id = setInterval(() => setLine((n) => (n + 1) % hero.datelines.length), 3400)
    return () => clearInterval(id)
  }, [])

  const [year, text] = hero.datelines[line]

  return (
    <div ref={root} className="hero absolute inset-0">
      <img ref={backdrop} src="/images/canyon.jpg" alt="" width="553" height="715" fetchPriority="high" className="hero-backdrop" />
      <div className="hero-shade" />

      <div ref={rest} className="absolute inset-0">
        {/* The river's real course, source at the top, the Gulf at the bottom. */}
        <svg viewBox={`-20 -20 ${map.width + 40} ${map.height + 40}`} className="hero-river" aria-hidden="true">
          <path ref={thread} d={map.river} pathLength="1" />
          {map.stations.map((s) => (
            <motion.circle key={s.id} cx={s.at[0]} cy={s.at[1]} r="7" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.5, delay: 0.7 + s.frac * 3.2 }} />
          ))}
        </svg>
        <p className="label absolute left-5 top-[4.6rem] max-w-[86vw] text-cream/75 max-sm:text-[0.62rem] sm:left-10 lg:left-16">{hero.label}</p>

        <div className="absolute inset-x-5 bottom-8 grid gap-x-16 gap-y-6 sm:inset-x-10 lg:inset-x-16 lg:bottom-12 lg:grid-cols-[minmax(0,30rem)_1fr] lg:items-end">
          <p className="font-display text-xl font-light leading-snug text-cream sm:text-2xl">{hero.hook}</p>
          <div className="lg:justify-self-end lg:text-right">
            <p className="dateline" aria-live="off">
              <AnimatePresence mode="wait">
                <motion.span key={year} className="block" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }} transition={{ duration: 0.45 }}>
                  <span className="font-mono text-amber">{year}</span>
                  <span className="mx-3 text-cream/40">/</span>
                  <span className="text-cream">{text}</span>
                </motion.span>
              </AnimatePresence>
            </p>
            <p className="label cue mt-5 flex items-center gap-3 text-cream/80 lg:justify-end">
              <span aria-hidden="true" className="inline-block h-9 w-px bg-cream/70" />
              {hero.cue}
            </p>
          </div>
        </div>
      </div>

      {/* Entrances are driven from script, not CSS keyframes, so they also run where the browser is saving frames. */}
      <motion.div
        ref={wrap}
        className="absolute left-5 top-[17svh] sm:left-10 lg:left-14 lg:top-[13svh]"
        initial={{ opacity: 0, y: 40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 1.4, ease: [0.16, 1, 0.3, 1] }}
      >
        <h1 ref={word} className="hero-word" aria-label={`${hero.word.join(' ')}, ${hero.script}`}>
          {hero.word.map((w, i) => (
            <span key={w} className="block" aria-hidden="true">
              {i === 0 ? (
                <>
                  {w.slice(0, 1)}
                  <span ref={eye}>{w.slice(1, 2)}</span>
                  {w.slice(2)}
                </>
              ) : (
                w
              )}
            </span>
          ))}
        </h1>
        <div ref={script}>
          <motion.p className="hero-script" aria-hidden="true" initial={{ opacity: 0, x: -30, rotate: -5 }} animate={{ opacity: 1, x: 0, rotate: -5 }} transition={{ duration: 1.1, delay: 0.9, ease: [0.16, 1, 0.3, 1] }}>
            {hero.script}
          </motion.p>
        </div>
      </motion.div>
    </div>
  )
}
