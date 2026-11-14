import { solution } from '../content.js'

/**
 * RESERVED. This section is an empty shell on purpose: the heading and the
 * frame are here so the page has its place, and nothing else. Add the content
 * inside the frame (and its text to `solution` in content.js) when it is ready.
 */
export default function Solution() {
  return (
    <section id="solution" className="paper scroll-mt-14 border-t border-rule" aria-labelledby="solution-h">
      <div className="mx-auto max-w-[76rem] px-5 py-20 sm:px-10 lg:py-28">
        <p className="eyebrow">{solution.eyebrow}</p>
        <h2 id="solution-h" className="mt-4 font-display text-[clamp(2rem,4.4vw,3.4rem)] font-normal leading-[1.08] tracking-tight">
          {solution.title}
        </h2>
        <div className="mt-10 grid min-h-[22rem] place-items-center border border-dashed border-rule">
          <p className="text-muted">{solution.empty}</p>
        </div>
      </div>
    </section>
  )
}
