import { useRef, useState } from 'react'

// ---------------------------------------------------------------------------
// Figure 1. What each product looks for, drawn on 52 weeks.
// ---------------------------------------------------------------------------
const WEEKS = 52
const PRODUCTS = [
  { id: 'alert', tab: '4-week alert', weeks: 4, hits: [3] },
  { id: 'season', tab: '6-month outlook', weeks: 26, hits: [10, 11, 12, 13, 14, 15, 16, 17] },
  { id: 'year', tab: '12-month outlook', weeks: 52, hits: [6, 7, 8, 9, 10, 11, 12, 13, 14, 23, 24, 25, 26, 27, 38, 39, 40, 41, 42, 43, 44, 45] },
]

export function HorizonFigure({ captions, note }) {
  const [active, setActive] = useState(1)
  const tabs = useRef([])
  const item = PRODUCTS[active]

  function onKey(e) {
    const step = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!step) return
    e.preventDefault()
    const next = (active + step + PRODUCTS.length) % PRODUCTS.length
    setActive(next)
    tabs.current[next]?.focus()
  }

  return (
    <figure className="fig">
      <div role="tablist" aria-label="Product" className="seg" onKeyDown={onKey}>
        {PRODUCTS.map((p, i) => (
          <button key={p.id} ref={(el) => (tabs.current[i] = el)} role="tab" id={'t-' + p.id} aria-selected={i === active} aria-controls="horizon-panel" tabIndex={i === active ? 0 : -1} onClick={() => setActive(i)}>
            {p.tab}
          </button>
        ))}
      </div>
      <div id="horizon-panel" role="tabpanel" aria-labelledby={'t-' + item.id} className="mt-5">
        <div className="weeks" role="img" aria-label={`${item.tab}: the outcome window covers ${item.weeks} of the 52 weeks shown.`}>
          {Array.from({ length: WEEKS }, (_, w) => (
            <span key={w} className={w >= item.weeks ? 'out' : item.hits.includes(w) ? 'hit' : 'in'} />
          ))}
        </div>
        <div className="axis" aria-hidden="true">
          <span style={{ left: `${(4 / 52) * 100}%` }}>4 wk</span>
          <span style={{ left: '50%' }}>26 wk</span>
          <span style={{ left: '100%' }}>52 wk</span>
        </div>
        <p className="mt-9 text-[0.95rem] text-ink">{captions[item.id]}</p>
      </div>
      <figcaption>
        <b>Figure 1.</b> Outcome windows. <i className="key in" /> inside the window <i className="key hit" /> a week at D2 or worse. {note}
      </figcaption>
    </figure>
  )
}

// ---------------------------------------------------------------------------
// Figure 2. Which years train and which years test.
// ---------------------------------------------------------------------------
const YEARS = Array.from({ length: 27 }, (_, i) => 2000 + i)
const alertKind = (y) => (y <= 2014 ? 'train' : y <= 2018 ? 'val' : 'test')
function outlookKind(y, test) {
  if (y === test) return 'test'
  if (y > test) return 'none'
  if (y <= 2002) return 'warm'
  if (y === test - 1) return 'gap'
  return 'train'
}

function Track({ kindOf, label }) {
  return (
    <div role="img" aria-label={label}>
      <div className="years">
        {YEARS.map((y) => (
          <span key={y} className={kindOf(y)} />
        ))}
      </div>
      <div className="years ticks" aria-hidden="true">
        {YEARS.map((y) => (
          <span key={y}>{y % 5 === 0 ? y : ''}</span>
        ))}
      </div>
    </div>
  )
}

function Legend({ items }) {
  return (
    <ul className="legend">
      {items.map(([kind, text]) => (
        <li key={kind}>
          <i className={'key ' + kind} /> {text}
        </li>
      ))}
    </ul>
  )
}

export function SplitsFigure({ alert, outlook }) {
  const [test, setTest] = useState(2016)
  return (
    <figure className="fig">
      <p className="fig-title">{alert.name}</p>
      <Track kindOf={alertKind} label="2000 to 2014 train; 2015 to 2018 validation; 2019 to 2026 test." />
      <Legend items={alert.legend} />

      <div className="mt-10 flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
        <p className="fig-title !mb-0">{outlook.name}</p>
        <label className="flex items-center gap-3 text-sm text-muted">
          {outlook.sliderLabel}
          <input type="range" min="2008" max="2025" value={test} onChange={(e) => setTest(Number(e.target.value))} className="w-44" />
          <output className="w-10 font-mono text-base tabular-nums text-ink">{test}</output>
        </label>
      </div>
      <div className="mt-4">
        <Track kindOf={(y) => outlookKind(y, test)} label={`Test year ${test}. Training uses 2003 to ${test - 2}; ${test - 1} is excluded because its outcomes were not yet known.`} />
      </div>
      <Legend items={outlook.legend} />
      <figcaption>
        <b>Figure 2.</b> Time splits. Each cell is one calendar year, 2000 to 2026.
      </figcaption>
    </figure>
  )
}

// ---------------------------------------------------------------------------
// Table with bars: rivers in the transfer test.
// ---------------------------------------------------------------------------
export function TransferTable({ head, rows }) {
  const max = Math.max(...rows.map((r) => r[1]))
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i} className={i === 1 || i === 4 ? 'num' : ''}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([river, n, role, rate], i) => (
            <tr key={river} className={i === 0 ? 'focus' : ''}>
              <th scope="row">{river}</th>
              <td className="num">{n}</td>
              <td className="w-[38%] min-w-28">
                <span className="bar" style={{ width: `${(n / max) * 100}%` }} />
              </td>
              <td className="nowrap">{role}</td>
              <td className="num">{rate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
