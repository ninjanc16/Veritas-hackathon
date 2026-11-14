import { paper } from '../../content.js'
import { HorizonFigure, SplitsFigure, TransferTable } from './Figures.jsx'

function DataTable({ head, rows, mono = [] }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={i} scope="col" className={mono.includes(i) ? 'num' : ''}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]}>
              {row.map((cell, i) =>
                i === 0 ? (
                  <th key={i} scope="row">
                    {cell}
                  </th>
                ) : (
                  <td key={i} className={mono.includes(i) ? 'num' : ''}>
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The method, set like a paper: numbered sections, ruled tables, two figures.
 * Deliberately plain. All of its text and every table is data in content.js.
 */
export default function Paper() {
  return (
    <section id="method" className="paper scroll-mt-14">
      <div className="mx-auto max-w-[76rem] px-5 py-20 sm:px-10 lg:py-28">
        <header className="max-w-3xl">
          <p className="eyebrow">{paper.eyebrow}</p>
          <h2 className="mt-4 font-display text-[clamp(2rem,4.4vw,3.4rem)] font-normal leading-[1.08] tracking-tight">{paper.title}</h2>
          <p className="mt-6 text-lg leading-relaxed text-muted">{paper.abstract}</p>
        </header>

        <div className="mt-16 lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-16">
          <nav aria-label="Method sections" className="toc max-lg:hidden">
            <ol>
              {paper.sections.map((s, i) => (
                <li key={s.id}>
                  <a href={'#' + s.id}>
                    <span>{i + 1}</span>
                    {s.title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>

          <div>
            {paper.sections.map((s, i) => (
              <section key={s.id} id={s.id} className="sec scroll-mt-20" aria-labelledby={s.id + '-h'}>
                <h3 id={s.id + '-h'}>
                  <span>{i + 1}</span>
                  {s.title}
                </h3>
                {s.lead && <p className="lead">{s.lead}</p>}
                {s.facts && (
                  <dl className="facts">
                    {s.facts.map(([k, v]) => (
                      <div key={k}>
                        <dt>{k}</dt>
                        <dd>{v}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {s.figure === 'horizons' && <HorizonFigure captions={s.captions} note={s.figureNote} />}
                {s.figure === 'splits' && <SplitsFigure {...s.splits} />}
                {s.formula && (
                  <p className="formula" aria-label={s.formula.join(' ')}>
                    {s.formula.map((part, n) => (
                      <span key={n}>{part}</span>
                    ))}
                  </p>
                )}
                {s.table && <DataTable {...s.table} />}
                {s.figure === 'transfer' && <TransferTable {...s.transfer} />}
                {s.list && (
                  <ol className="plain">
                    {s.list.map((text) => (
                      <li key={text}>{text}</li>
                    ))}
                  </ol>
                )}
                {s.notes && (
                  <ul className="notes">
                    {s.notes.map((text) => (
                      <li key={text}>{text}</li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
