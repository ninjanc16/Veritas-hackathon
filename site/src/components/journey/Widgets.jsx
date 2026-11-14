import { journey } from '../../content.js'
import map from '../../data/map.json'
import ProductButton from '../ProductButton.jsx'

/** The small graphic under a chapter's text. Chosen by `chapter.widget` in content.js. */
export default function Widget({ chapter }) {
  return (
    <>
      {chapter.stat && (
        <div className="mt-6 flex items-start gap-5 border-l-2 border-magenta pl-5">
          <p className="font-mono text-6xl font-medium leading-none tabular-nums text-cream max-lg:text-5xl">{chapter.stat.value}</p>
          <p className="max-w-[15rem] text-sm leading-snug text-cream/90">
            {chapter.stat.text}
            <span className="label mt-2 block text-[0.62rem] text-magenta">{chapter.stat.tag}</span>
          </p>
        </div>
      )}

      {chapter.widget === 'counties' && (
        <dl className="mt-6 flex max-w-md items-end gap-7">
          <div>
            <dd className="font-mono text-7xl font-medium leading-none tabular-nums text-amber max-lg:text-6xl">{map.counties.length}</dd>
            <dt className="label mt-2 text-cream/70">counties</dt>
          </div>
          {chapter.breakdown.map(([n, state], i) => (
            <div key={state} className="horizon" style={{ animationDelay: `${0.25 + i * 0.14}s` }}>
              <dd className="font-mono text-3xl tabular-nums text-cream">{n}</dd>
              <dt className="label mt-2 text-cream/70">{state}</dt>
            </div>
          ))}
        </dl>
      )}

      {chapter.widget === 'scale' && (
        <div className="mt-6">
          <ol className="grid max-w-sm grid-cols-6 gap-1" aria-label={journey.scaleNote}>
            {journey.scale.map(([name, severe], i) => (
              <li key={name} className="text-center">
                <span className={'block h-3 ' + (severe ? 'bg-magenta' : 'bg-cream')} style={{ opacity: severe ? 0.55 + (i - 3) * 0.22 : 0.12 + i * 0.12 }} />
                <span className={'label mt-1.5 block text-[0.62rem] ' + (severe ? 'text-magenta' : 'text-cream/60')}>{name}</span>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-sm text-cream/70">{journey.scaleNote}</p>
        </div>
      )}

      {chapter.widget === 'eight' && (
        <ol className="mt-6 flex max-w-sm gap-1.5" aria-label="Eight consecutive weeks">
          {Array.from({ length: 8 }, (_, i) => (
            <li key={i} className="week flex-1" style={{ animationDelay: `${0.25 + i * 0.14}s` }}>
              <span className="label block pt-9 text-center text-[0.62rem] text-cream/80">{i + 1}</span>
            </li>
          ))}
        </ol>
      )}

      {chapter.widget === 'horizons' && (
        <>
          <dl className="mt-5 max-w-md">
            {chapter.horizons.map(([span, text], i) => (
              <div key={span} className="horizon grid grid-cols-[6.2rem_1fr] items-baseline gap-3 border-t border-cream/15 py-2.5" style={{ animationDelay: `${0.2 + i * 0.16}s` }}>
                <dt className="font-mono text-lg text-amber">{span}</dt>
                <dd className="text-cream/90 max-lg:text-sm">{text}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-6 flex flex-wrap items-center gap-5">
            <ProductButton size="md" align="left" />
            <a href="#method" className="label text-cream underline decoration-cream/40 underline-offset-4 hover:decoration-amber">
              {chapter.methodLink} ↓
            </a>
          </p>
        </>
      )}
    </>
  )
}
