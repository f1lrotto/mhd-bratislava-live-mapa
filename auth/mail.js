// Account emails (address verification, password reset), sent with Resend (https://resend.com).
//
// Environment:
//   RESEND_API_KEY  without it no email is sent and the app hides what needs email (forgotten
//                   password)
//   MHD_MAIL=log    dev: act as if email worked and log the links; nothing is sent, even with a key
//   MAIL_FROM       the sender, an address on a domain verified in Resend
//                   (default "MHD naživo <ucet@mhd.filiphupka.com>")

const FROM = process.env.MAIL_FROM || 'MHD naživo <ucet@mhd.filiphupka.com>'

export const mailEnabled = () => !!process.env.RESEND_API_KEY || process.env.MHD_MAIL === 'log'

const escape = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c])

function html(lead, button, url, after) {
  return `<!doctype html><html lang="sk"><body style="margin:0;padding:24px;background:#f1f3f5;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;color:#1d232b">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:28px">
<p style="margin:0 0 18px;font-size:18px"><b>MHD naživo</b></p>
<p style="margin:0 0 20px;font-size:15px;line-height:1.5">${escape(lead)}</p>
<p style="margin:0 0 20px"><a href="${escape(url)}" style="display:inline-block;background:#1d232b;color:#fff;text-decoration:none;font-weight:600;padding:12px 20px;border-radius:12px">${escape(button)}</a></p>
<p style="margin:0;font-size:13px;line-height:1.5;color:#5b6470">${escape(after)}</p>
</div></body></html>`
}

/** Never throws: callers don't wait for it (see sendResetPassword in server.js). */
async function send(to, subject, lead, button, url, after) {
  try {
    await post(to, subject, lead, button, url, after)
  } catch (e) {
    console.error(`[mail] sending failed: ${e}`)
  }
}

// Each address gets at most one email of a kind (verification, reset) per PER_ADDRESS_MS and
// PER_ADDRESS_DAY emails a day, and the server
// sends at most PER_DAY a day: sign-ups and email changes can name any address, so this is what
// keeps the app from mailing someone over and over. Kept in memory: a restart forgets it.
// The last RESERVED of the day are for password resets, so a flood of sign-ups can't stop them.
// Someone can still use up one address's 5 with reset requests; its owner then waits a day.
const PER_ADDRESS_MS = 2 * 60_000
const PER_ADDRESS_DAY = 5
const PER_DAY = 100 // Resend's free plan sends 100 a day
const RESERVED = 20
const RESET = 'Obnovenie hesla'
const DAY_MS = 86_400_000
const sent = new Map() // address -> [time, kind] of the emails sent to it in the last day
let today = []

/** Whether another email to this address is allowed now; records it when it is. */
function allowMail(to, kind, now = Date.now()) {
  const addr = to.toLowerCase()
  const times = (sent.get(addr) ?? []).filter(([t]) => now - t < DAY_MS)
  today = today.filter((t) => now - t < DAY_MS)
  const recent = times.some(([t, k]) => k === kind && now - t < PER_ADDRESS_MS)
  sent.set(addr, times)
  const cap = kind === RESET ? PER_DAY : PER_DAY - RESERVED
  if (recent || times.length >= PER_ADDRESS_DAY || today.length >= cap) return false
  times.push([now, kind])
  today.push(now)
  if (sent.size > 10_000) for (const [k, v] of sent) if (!v.some(([t]) => now - t < DAY_MS)) sent.delete(k)
  return true
}

async function post(to, subject, lead, button, url, after) {
  if (!allowMail(to, subject)) {
    console.warn(`[mail] not sent: too many emails to this address or today`)
    return
  }
  if (process.env.MHD_MAIL === 'log') {
    console.log(`[mail] not sending (MHD_MAIL=log); to ${to}: ${subject}: ${url}`)
    return
  }
  // Without a key the link isn't logged either: a reset link in the logs is a way into the account.
  if (!process.env.RESEND_API_KEY) return
  const r = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${process.env.RESEND_API_KEY}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from: FROM,
      to: [to],
      subject,
      html: html(lead, button, url, after),
      text: `${lead}\n\n${button}: ${url}\n\n${after}`,
    }),
    signal: AbortSignal.timeout(15_000),
  })
  // Logged, not thrown: an outage of Resend must not tell the visitor whether an address has an account.
  if (!r.ok) console.error(`[mail] Resend answered ${r.status}: ${(await r.text()).slice(0, 300)}`)
}

export const sendVerification = (to, url) =>
  send(
    to,
    'Overte svoj e-mail',
    'Potvrďte, že táto adresa patrí vám.',
    'Overiť e-mail',
    url,
    'Odkaz platí hodinu. Ak ste o účet v MHD naživo ani o zmenu e-mailu nežiadali, tento e-mail ignorujte.',
  )

export const sendReset = (to, url) =>
  send(
    to,
    RESET,
    'Niekto (dúfame, že vy) požiadal o nové heslo k vášmu účtu v MHD naživo.',
    'Nastaviť nové heslo',
    url,
    'Odkaz platí hodinu. Ak ste o nové heslo nežiadali, tento e-mail ignorujte; vaše heslo sa nezmení.',
  )
