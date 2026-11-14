import { closing, footer, site } from '../content.js'
import ProductButton from './ProductButton.jsx'

/** The canyon comes back once, at the end, behind the way into the tool. */
export default function Closing() {
  return (
    <footer className="bg-umber-950">
      <section className="relative isolate overflow-hidden" aria-labelledby="closing-title">
        <div className="absolute inset-0 -z-10">
          <img src="/images/canyon.jpg" alt="" loading="lazy" width="553" height="715" className="h-full w-full object-cover object-[50%_62%] opacity-70 blur-[2px]" />
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-umber-950/80 via-umber-950/55 to-umber-950" />
        </div>
        <div className="mx-auto max-w-3xl px-5 py-36 text-center sm:py-48">
          <div>
            <h2 id="closing-title" className="font-display text-5xl font-light tracking-tight text-cream sm:text-7xl">
              {closing.title}
            </h2>
            <p className="mx-auto mt-5 max-w-md text-lg leading-relaxed text-cream/90">{closing.body}</p>
            <div className="mt-10">
              <ProductButton size="lg" align="center" />
            </div>
          </div>
        </div>
      </section>

      <div className="mx-auto grid max-w-6xl gap-12 px-5 py-16 sm:px-10 md:grid-cols-[1fr_1.6fr]">
        <div>
          <p className="font-display text-2xl text-cream">{site.fullName}</p>
          <p className="mt-3 text-cream/80">{footer.event}</p>
          <p className="mt-1 text-cream/80">{footer.team}</p>
          <p className="mt-1 text-cream/80">{footer.contact}</p>
        </div>
        <div>
          <h2 className="label text-amber">Sources and credits</h2>
          <dl className="mt-4">
            {footer.credits.map((c) => (
              <div key={c.what} className="grid gap-x-6 border-t border-cream/15 py-3 sm:grid-cols-[13rem_1fr]">
                <dt className="text-cream/70">{c.what}</dt>
                <dd className="text-cream">
                  {c.url ? (
                    <a href={c.url} className="underline decoration-cream/40 underline-offset-4 hover:decoration-amber">
                      {c.who}
                    </a>
                  ) : (
                    c.who
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </footer>
  )
}
