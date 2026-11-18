// "Čo je nové" (/novinky): the entries of frontend/CHANGELOG.md, written by hand and bundled at
// build time. The browser remembers how many entries it has seen (`news-seen`), and the top bar
// shows a dot while there are more, for two weeks after the newest one.
import changelog from '../../CHANGELOG.md?raw'
import { closePanel, navigate, parseUrl, setSpeed } from './state.svelte'

export interface NewsItem {
  /** The day it shipped, YYYY-MM-DD. */
  date: string
  title: string
  paragraphs: string[]
  /** A button that opens an app URL, such as /oblubene or /?rychlost=bezne. */
  open?: { label: string; href: string }
}

/** The entries of CHANGELOG.md, newest first (the format is described at the top of the file). */
export function parseChangelog(md: string): NewsItem[] {
  const items: NewsItem[] = []
  let date: string | null = null
  let item: NewsItem | null = null
  let para: string[] = []
  const endPara = () => {
    if (item && para.length) item.paragraphs.push(para.join(' '))
    para = []
  }
  for (const raw of md.split('\n')) {
    const line = raw.trim()
    const day = /^## (\d{4}-\d{2}-\d{2})$/.exec(line)
    if (day) {
      endPara()
      date = day[1]
      item = null
      continue
    }
    if (!date) continue // the instructions above the first day
    if (line.startsWith('### ')) {
      endPara()
      item = { date, title: line.slice(4).trim(), paragraphs: [] }
      items.push(item)
      continue
    }
    if (!item) continue
    const link = /^\[([^\]]+)\]\((\/[^)\s]*)\)$/.exec(line)
    if (link) {
      endPara()
      item.open = { label: link[1], href: link[2] }
    } else if (line) para.push(line)
    else endPara()
  }
  endPara()
  return items
}

export const NEWS = parseChangelog(changelog)

const KEY = 'news-seen'
const FRESH_MS = 14 * 24 * 3600_000

function readSeen(): number {
  try {
    return Number(localStorage.getItem(KEY) ?? 0) || 0
  } catch {
    return 0
  }
}

class NewsState {
  /** How many entries this browser has seen. */
  seen = $state.raw(readSeen())
}

export const news = new NewsState()

/** True for an entry the visitor hasn't seen, from the last two weeks. `seen` as it was before opening. */
export function isNew(i: number, seen: number = news.seen): boolean {
  return i < NEWS.length - seen && Date.now() - Date.parse(NEWS[i].date) < FRESH_MS
}

/** The top bar's dot: the newest entry is new. */
export function unread(): boolean {
  return NEWS.length > 0 && isNew(0)
}

export function markSeen(): void {
  news.seen = NEWS.length
  try {
    localStorage.setItem(KEY, String(NEWS.length))
  } catch {
    // Private mode: the dot shows again next time.
  }
}

/** Opens an entry's link: its panel, and the speed overlay when the link turns it on. */
export function openItem(item: NewsItem): void {
  if (!item.open) return
  const { view, speed } = parseUrl(new URL(item.open.href, location.origin))
  if (speed) setSpeed(speed)
  if (view.kind === 'none') closePanel()
  else navigate(view)
}
