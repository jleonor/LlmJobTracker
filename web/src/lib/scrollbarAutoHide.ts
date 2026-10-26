import { useEffect } from 'react'

// Reveals a scrolled element's own scrollbar thumb only while it's actively scrolling, hiding it
// again shortly after the last scroll event - not on hover, which plain CSS can do on its own.
// A single document-level, capturing listener: 'scroll' events on a non-window element don't
// bubble, so this is the one place that sees every scrollable region's own scrolling.
const HIDE_AFTER_MS = 800

export function useScrollbarAutoHide() {
  useEffect(() => {
    const timers = new WeakMap<Element, ReturnType<typeof setTimeout>>()

    function onScroll(event: Event) {
      const target = event.target === document ? document.documentElement : event.target
      if (!(target instanceof Element)) return

      target.classList.add('scrolling')
      const existing = timers.get(target)
      if (existing !== undefined) clearTimeout(existing)
      timers.set(
        target,
        setTimeout(() => target.classList.remove('scrolling'), HIDE_AFTER_MS),
      )
    }

    document.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => document.removeEventListener('scroll', onScroll, { capture: true })
  }, [])
}
