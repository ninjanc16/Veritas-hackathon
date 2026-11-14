import { site } from '../content.js'
import ProductButton from './ProductButton.jsx'

export default function TopBar() {
  return (
    <header className="fixed inset-x-0 top-0 z-40">
      <div className="flex items-center justify-between gap-4 border-b border-cream/10 bg-night/75 px-4 py-3 backdrop-blur-md sm:px-8">
        <a href="#top" className="font-display text-lg tracking-tight text-cream sm:text-xl">
          {site.name}
        </a>
        <nav aria-label="Main" className="flex items-center gap-6">
          {site.nav.slice(1).map(([name, href]) => (
            <a key={href} href={href} className="hidden text-sm text-cream/85 underline-offset-4 hover:underline sm:inline">
              {name}
            </a>
          ))}
          <ProductButton />
        </nav>
      </div>
    </header>
  )
}
