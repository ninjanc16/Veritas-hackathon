import { useEffect, useId, useRef, useState } from 'react'
import { site } from '../content.js'

/**
 * The one way into the tool. With a URL in content.js it is a plain link.
 * Until then it is a button that says, honestly, that the tool is coming.
 */
export default function ProductButton({ size = 'sm', align = 'right' }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const wrap = useRef(null)
  const { label, url, pending } = site.product

  useEffect(() => {
    if (!open) return
    const close = (e) => {
      if (e.key === 'Escape' || (e.type === 'pointerdown' && !wrap.current?.contains(e.target))) setOpen(false)
    }
    window.addEventListener('keydown', close)
    window.addEventListener('pointerdown', close)
    return () => {
      window.removeEventListener('keydown', close)
      window.removeEventListener('pointerdown', close)
    }
  }, [open])

  const cls =
    'group inline-flex items-center gap-2 rounded-full bg-amber font-medium text-umber-950 transition-[background-color,transform] duration-200 hover:bg-cream active:scale-[0.97] ' +
    (size === 'lg' ? 'px-8 py-4 text-lg' : size === 'md' ? 'px-6 py-3 text-base' : 'px-4 py-2 text-sm')
  const arrow = (
    <span aria-hidden="true" className="transition-transform duration-200 group-hover:translate-x-1">
      →
    </span>
  )

  if (url) {
    return (
      <a className={cls} href={url}>
        {label} {arrow}
      </a>
    )
  }
  return (
    <span ref={wrap} className="relative inline-block">
      <button type="button" className={cls} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
        {label} {arrow}
      </button>
      <span
        id={id}
        role="status"
        hidden={!open}
        className={
          'absolute top-full z-10 mt-3 w-64 border border-hair bg-ink-900 p-3 text-left text-sm leading-snug text-bone shadow-xl ' +
          (align === 'right' ? 'right-0' : align === 'left' ? 'left-0 bottom-full top-auto mb-3 mt-0' : 'left-1/2 -translate-x-1/2')
        }
      >
        {pending}
      </span>
    </span>
  )
}
