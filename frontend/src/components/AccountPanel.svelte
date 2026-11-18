<script lang="ts">
  import { onMount } from 'svelte'
  import {
    addPasskey,
    changeEmail,
    confirmTwoFactor,
    disableTwoFactor,
    enableTwoFactor,
    newBackupCodes,
    removePasskey,
    signInWithPasskey,
    verifyCode,
    changePassword,
    deleteAccount,
    loadProfile,
    profile,
    requestPasswordReset,
    resendVerification,
    resetPassword,
    setPreferences,
    signIn,
    signOut,
    signOutOthers,
  } from '../lib/profile.svelte'
  import { app, navigate } from '../lib/state.svelte'
  import { track } from '../lib/analytics.svelte'
  import Panel from './Panel.svelte'

  // Links in account emails return here: ?token= (set a new password), ?overene=1 (address
  // verified), ?error= (an expired or used link). The URL is cleaned once read.
  const q = new URLSearchParams(location.search)
  let resetToken = $state(q.get('token'))
  let notice = $state<string | null>(
    q.get('error') ? 'Odkaz z e-mailu už neplatí. Požiadajte o nový.' : q.get('overene') === '1' ? 'E-mail je overený. Ďakujeme.' : null,
  )
  onMount(() => {
    if (q.get('overene') === '1') track('email_verified')
    else if (q.get('error')) track('email_link_failed', { error: q.get('error') })
    if (location.search) navigate({ kind: 'account' }, { replace: true })
  })

  let mode = $state<'sign-in' | 'sign-up' | 'forgot'>('sign-in')
  let email = $state('')
  let password = $state('')
  let error = $state<string | null>(null)
  let busy = $state(false)
  /** The open form of the signed-in profile. */
  let open = $state<'password' | 'email' | 'delete' | '2fa-on' | '2fa-off' | 'codes' | 'passkey' | null>(null)
  /** Signing in waits for the code from the authenticator app (or a backup code). */
  let codeStep = $state(false)
  let code = $state('')
  let useBackup = $state(false)
  let trustDevice = $state(false)
  /** A star asked to sign in: go back to its panel afterwards. */
  let pinning = false
  /** Turning on two-step sign-in: the app's QR code and secret, and the backup codes. */
  let setup = $state<{ qr: string; secret: string; backupCodes: string[] } | null>(null)
  /** Backup codes just made, shown once. */
  let codes = $state<string[] | null>(null)
  const passkeys = typeof window !== 'undefined' && 'PublicKeyCredential' in window
  let current = $state('')
  let next = $state('')
  let newEmail = $state('')

  const ERRORS: Record<string, string> = {
    INVALID_EMAIL_OR_PASSWORD: 'Nesprávny e-mail alebo heslo.',
    INVALID_EMAIL: 'Toto nie je platná e-mailová adresa.',
    INVALID_PASSWORD: 'Nesprávne heslo.',
    PASSWORD_TOO_SHORT: 'Heslo musí mať aspoň 8 znakov.',
    PASSWORD_TOO_LONG: 'Heslo môže mať najviac 128 znakov.',
    USER_ALREADY_EXISTS: 'Účet s týmto e-mailom už existuje. Prihláste sa.',
    USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL: 'Účet s týmto e-mailom už existuje. Prihláste sa.',
    INVALID_TOKEN: 'Odkaz z e-mailu už neplatí. Požiadajte o nový.',
    TOO_MANY_REQUESTS: 'Priveľa pokusov. Skúste to o chvíľu znova.',
    TOO_MANY_PASSKEYS: 'Viac prístupových kľúčov už pridať nemôžete. Najprv niektorý odstráňte.',
    INVALID_CODE: 'Nesprávny kód.',
    INVALID_BACKUP_CODE: 'Nesprávny záložný kód.',
    INVALID_TWO_FACTOR_COOKIE: 'Overenie vypršalo. Prihláste sa znova.',
    TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE: 'Priveľa nesprávnych kódov. Prihláste sa znova.',
    ACCOUNT_TEMPORARILY_LOCKED: 'Priveľa nesprávnych kódov. Skúste to neskôr.',
    PASSKEY_CANCELLED: 'Prístupový kľúč sa nepoužil.',
    PASSKEY_FAILED: 'Prístupový kľúč sa nepodarilo použiť.',
    PREVIOUSLY_REGISTERED: 'Tento prístupový kľúč už máte pridaný.',
    AUTHENTICATION_FAILED: 'Tento prístupový kľúč nepoznáme.',
    PASSKEY_NOT_FOUND: 'Tento prístupový kľúč nepoznáme.',
    SESSION_NOT_FRESH: 'Z bezpečnosti sa odhláste, znova prihláste a skúste to potom.',
  }
  const errorText = (e: unknown) => ERRORS[(e as Error).message] ?? 'Nepodarilo sa to. Skúste to znova.'

  /** Run an action with the busy state; returns whether it succeeded. */
  async function run(fn: () => Promise<void>, done?: string): Promise<boolean> {
    busy = true
    error = null
    notice = null
    try {
      await fn()
      if (done) notice = done
      return true
    } catch (err) {
      error = errorText(err)
      return false
    } finally {
      busy = false
    }
  }

  function setMode(m: typeof mode) {
    mode = m
    error = null
    notice = null
  }
  function toggle(f: typeof open) {
    open = open === f ? null : f
    current = next = newEmail = code = ''
    setup = codes = null
    error = null
    notice = null
  }

  async function submit(e: SubmitEvent) {
    e.preventDefault()
    if (mode === 'forgot') {
      const to = email.trim()
      if (await run(() => requestPasswordReset(to))) {
        mode = 'sign-in'
        notice = `Ak k adrese ${to} existuje účet, poslali sme na ňu odkaz na nové heslo.`
      }
      return
    }
    pinning = !!profile.pending
    const signingUp = mode === 'sign-up'
    let done = false
    if (await run(async () => void (done = await signIn(mode as 'sign-in' | 'sign-up', email.trim(), password)))) {
      password = ''
      if (!done) {
        codeStep = true
        code = ''
        useBackup = false
      } else if (signingUp)
        // A new account stays here to see what it has.
        notice = profile.mail ? `Účet je vytvorený. Na ${profile.user?.email} sme poslali odkaz na overenie adresy.` : 'Účet je vytvorený.'
      else signedIn()
    }
  }

  /** Back to the panel whose star asked to sign in, or to the favourites. */
  function signedIn() {
    codeStep = false
    if (pinning && app.canBack) history.back()
    else navigate({ kind: 'favorites' }, { replace: true })
  }

  async function submitCode(e: SubmitEvent) {
    e.preventDefault()
    if (await run(() => verifyCode(code.trim(), useBackup, trustDevice))) signedIn()
    // The sign-in expired or used up its tries: start over.
    else if (error === ERRORS.INVALID_TWO_FACTOR_COOKIE || error === ERRORS.TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE) codeStep = false
  }

  async function passkeySignIn() {
    pinning = !!profile.pending
    if (await run(signInWithPasskey)) signedIn()
  }

  async function startTwoFactor(e: SubmitEvent) {
    e.preventDefault()
    await run(async () => {
      const r = await enableTwoFactor(current)
      const { renderSVG } = await import('uqr')
      setup = { qr: renderSVG(r.totpURI), secret: new URL(r.totpURI).searchParams.get('secret') ?? '', backupCodes: r.backupCodes }
      current = ''
    })
  }

  async function finishTwoFactor(e: SubmitEvent) {
    e.preventDefault()
    if (await run(() => confirmTwoFactor(code.trim()))) {
      toggle(null)
      notice = 'Dvojstupňové overenie je zapnuté. Pri prihlásení vás požiadame aj o kód z aplikácie.'
    }
  }

  async function stopTwoFactor(e: SubmitEvent) {
    e.preventDefault()
    if (await run(() => disableTwoFactor(current))) {
      toggle(null)
      notice = 'Dvojstupňové overenie je vypnuté.'
    }
  }

  async function savePasskey(e: SubmitEvent) {
    e.preventDefault()
    const pw = current
    if (await run(() => addPasskey(pw))) {
      toggle(null)
      notice = 'Prístupový kľúč je pridaný.'
    }
  }

  async function makeCodes(e: SubmitEvent) {
    e.preventDefault()
    await run(async () => {
      codes = await newBackupCodes(current)
      current = ''
    })
  }

  async function reset(e: SubmitEvent) {
    e.preventDefault()
    const token = resetToken!
    if (await run(() => resetPassword(token, next))) {
      resetToken = null
      next = ''
      mode = 'sign-in'
      notice = 'Heslo je zmenené a všetky zariadenia sme odhlásili. Prihláste sa novým heslom.'
      await signOut().catch(() => {})
    }
  }

  async function savePassword(e: SubmitEvent) {
    e.preventDefault()
    const ok = await run(() => changePassword(current, next))
    if (!ok && error === ERRORS.INVALID_PASSWORD) error = 'Súčasné heslo nie je správne.'
    if (ok) {
      toggle(null)
      notice = 'Heslo je zmenené. Ostatné zariadenia sme odhlásili.'
    }
  }

  async function saveEmail(e: SubmitEvent) {
    e.preventDefault()
    const to = newEmail.trim()
    if (await run(() => changeEmail(to, current))) {
      toggle(null)
      notice = `Na ${to} sme poslali odkaz. E-mail sa zmení, keď ho otvoríte.`
    }
  }

  async function remove(e: SubmitEvent) {
    e.preventDefault()
    if (await run(() => deleteAccount(current))) {
      open = null
      current = ''
      notice = 'Účet aj všetky vaše údaje sme zmazali.'
    }
  }

  const pendingText = $derived.by(() => {
    const p = profile.pending
    if (!p) return null
    if (p.kind === 'line') return `linku ${p.ref}`
    if (p.kind === 'station') return `zastávku ${app.stations[p.ref]?.name ?? p.ref}`
    return 'túto trasu'
  })
  const title = $derived(
    resetToken ? 'Nové heslo' : profile.user || profile.failed ? 'Profil' : codeStep ? 'Overenie' : mode === 'sign-up' ? 'Nový účet' : mode === 'forgot' ? 'Zabudnuté heslo' : 'Prihlásenie',
  )
  const start = $derived(profile.preferences.start ?? 'favorites')
</script>

<!-- On phones the sheet is full height for the forms, so the keyboard doesn't hide the fields. -->
<Panel tall label={title} expand={!profile.user || !!resetToken || open != null}>
  {#snippet header()}
    <svg class="head-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></svg>
    <strong>{title}</strong>
  {/snippet}

  {#if notice}<p class="note ok" role="status">{notice}</p>{/if}

  {#if !profile.loaded}
    <p class="note">Načítavam…</p>
  {:else if resetToken}
    <form onsubmit={reset}>
      <label>
        <span>Nové heslo</span>
        <input type="password" bind:value={next} required minlength="8" maxlength="128" autocomplete="new-password" />
      </label>
      <p class="muted small hint">Aspoň 8 znakov. Po zmene odhlásime všetky zariadenia.</p>
      {#if error}<p class="note error" role="alert">{error}</p>{/if}
      <button class="primary" type="submit" disabled={busy}>Nastaviť heslo</button>
    </form>
  {:else if !profile.user && codeStep}
    <form onsubmit={submitCode}>
      <label>
        <span>{useBackup ? 'Záložný kód' : 'Kód z overovacej aplikácie'}</span>
        <input
          bind:value={code}
          required
          autocomplete="one-time-code"
          inputmode={useBackup ? 'text' : 'numeric'}
          spellcheck="false"
          maxlength="32"
        />
      </label>
      <label class="check"><input type="checkbox" bind:checked={trustDevice} /> Na tomto zariadení sa 30 dní nepýtať</label>
      {#if error}<p class="note error" role="alert">{error}</p>{/if}
      <button class="primary" type="submit" disabled={busy}>Overiť</button>
    </form>
    <button class="link forgot" onclick={() => ((useBackup = !useBackup), (code = ''), (error = null))}
      >{useBackup ? 'Použiť kód z aplikácie' : 'Nemáte aplikáciu po ruke? Použite záložný kód'}</button
    >
    <button class="link forgot" onclick={() => ((codeStep = false), (error = null))}>Späť na prihlásenie</button>
  {:else if !profile.user && profile.failed}
    <!-- Offline or a deploy: the user may well be signed in, so don't ask them to sign in. -->
    <p class="note error">Účet sa teraz nedá načítať. Skontrolujte pripojenie a skúste to znova.</p>
    <button class="secondary" disabled={busy} onclick={() => run(() => loadProfile(0))}>Skúsiť znova</button>
  {:else if !profile.user}
    {#if mode !== 'forgot'}
      <div class="tabs" role="group" aria-label="Prihlásenie alebo nový účet">
        <button class:active={mode === 'sign-in'} aria-pressed={mode === 'sign-in'} onclick={() => setMode('sign-in')}>Prihlásiť sa</button>
        <button class:active={mode === 'sign-up'} aria-pressed={mode === 'sign-up'} onclick={() => setMode('sign-up')}>Vytvoriť účet</button>
      </div>
      {#if pendingText}
        <p class="note">{mode === 'sign-in' ? 'Po prihlásení' : 'Po vytvorení účtu'} si pripnete {pendingText}.</p>
      {:else if !notice}
        <p class="note">Účet uchová vaše obľúbené zastávky, linky a trasy a vaše nastavenia, aby ste ich mali na každom zariadení.</p>
      {/if}
    {:else}
      <p class="note">Zadajte e-mail svojho účtu. Pošleme naň odkaz, ktorým si nastavíte nové heslo.</p>
    {/if}
    <form onsubmit={submit}>
      <label>
        <span>E-mail</span>
        <input type="email" bind:value={email} required autocomplete="email" inputmode="email" spellcheck="false" />
      </label>
      {#if mode !== 'forgot'}
        <label>
          <span>Heslo</span>
          <input
            type="password"
            bind:value={password}
            required
            minlength={mode === 'sign-up' ? 8 : undefined}
            maxlength="128"
            autocomplete={mode === 'sign-up' ? 'new-password' : 'current-password'}
          />
        </label>
      {/if}
      {#if mode === 'sign-up'}
        <p class="muted small hint">
          Aspoň 8 znakov.{#if profile.mail}
            Na e-mail vám pošleme odkaz na overenie adresy.{:else}
            Zabudnuté heslo zatiaľ nevieme obnoviť e-mailom, uložte si ho preto do správcu hesiel.{/if}
        </p>
      {/if}
      {#if error}<p class="note error" role="alert">{error}</p>{/if}
      <button class="primary" type="submit" disabled={busy}
        >{mode === 'sign-in' ? 'Prihlásiť sa' : mode === 'sign-up' ? 'Vytvoriť účet' : 'Poslať odkaz'}</button
      >
    </form>
    {#if mode === 'sign-in' && passkeys}
      <button class="secondary passkey" disabled={busy} onclick={passkeySignIn}>Prihlásiť sa prístupovým kľúčom</button>
    {/if}
    {#if mode === 'sign-in' && profile.mail}
      <button class="link forgot" onclick={() => setMode('forgot')}>Zabudli ste heslo?</button>
    {:else if mode === 'forgot'}
      <button class="link forgot" onclick={() => setMode('sign-in')}>Späť na prihlásenie</button>
    {/if}
    <p class="muted small foot">
      Čo s účtom ukladáme, popisuje <button class="link" onclick={() => navigate({ kind: 'privacy' })}>ochrana súkromia</button>.
    </p>
  {:else}
    {@const user = profile.user}
    <div class="who">
      <span class="avatar" aria-hidden="true">{user.email[0].toUpperCase()}</span>
      <div>
        <b>{user.email}</b><br />
        <span class="muted small">
          {#if user.emailVerified}Overený e-mail{:else}Neoverený e-mail{/if} · účet od
          {new Date(user.createdAt).toLocaleDateString('sk', { timeZone: 'Europe/Bratislava' })}
        </span>
      </div>
    </div>
    {#if !user.emailVerified && profile.mail}
      <p class="note warn">
        Overte svoj e-mail, aby sme vedeli, že adresa patrí vám.
        <button class="link" disabled={busy} onclick={() => run(resendVerification, `Odkaz posielame na ${user.email}, najviac jeden za 2 minúty. Ak nepríde, pozrite aj do spamu.`)}
          >Poslať odkaz znova</button
        >
      </p>
    {/if}
    <button class="secondary" onclick={() => navigate({ kind: 'favorites' })}>Moje obľúbené ({profile.favorites.length})</button>

    <h3 class="section">Nastavenia</h3>
    <!-- Each preference is a key of Preferences (lib/profile.svelte.ts, auth/profile.js). -->
    <div class="pref">
      <span id="pref-start">Nainštalovaná aplikácia sa otvorí na</span>
      <div class="tabs" role="group" aria-labelledby="pref-start">
        <button class:active={start === 'favorites'} aria-pressed={start === 'favorites'} onclick={() => run(() => setPreferences({ start: null }))}
          >Obľúbených</button
        >
        <button class:active={start === 'map'} aria-pressed={start === 'map'} onclick={() => run(() => setPreferences({ start: 'map' }))}
          >Mape</button
        >
      </div>
    </div>

    <h3 class="section">Prihlásenie</h3>
    <button class="secondary" aria-expanded={open === 'password'} onclick={() => toggle('password')}>Zmeniť heslo</button>
    {#if open === 'password'}
      <form class="sub" onsubmit={savePassword}>
        <label>
          <span>Súčasné heslo</span>
          <input type="password" bind:value={current} required autocomplete="current-password" />
        </label>
        <label>
          <span>Nové heslo</span>
          <input type="password" bind:value={next} required minlength="8" maxlength="128" autocomplete="new-password" />
        </label>
        <p class="muted small hint">Aspoň 8 znakov. Ostatné zariadenia odhlásime.</p>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>Uložiť heslo</button>
      </form>
    {/if}
    <!-- The new address must confirm with a link, so changing it needs email. -->
    {#if profile.mail}
    <button class="secondary" aria-expanded={open === 'email'} onclick={() => toggle('email')}>Zmeniť e-mail</button>
    {/if}
    {#if open === 'email'}
      <form class="sub" onsubmit={saveEmail}>
        <label>
          <span>Nový e-mail</span>
          <input type="email" bind:value={newEmail} required autocomplete="email" inputmode="email" spellcheck="false" />
        </label>
        <label>
          <span>Súčasné heslo</span>
          <input type="password" bind:value={current} required autocomplete="current-password" />
        </label>
        <p class="muted small hint">Na novú adresu pošleme odkaz; e-mail sa zmení, keď ho otvoríte.</p>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>Zmeniť e-mail</button>
      </form>
    {/if}

    <h3 class="section">Zabezpečenie</h3>
    <p class="muted small">
      Dvojstupňové overenie: <b>{user.twoFactorEnabled ? 'zapnuté' : 'vypnuté'}</b>. Pri prihlásení heslom si potom
      vypýtame aj kód z overovacej aplikácie v telefóne.
    </p>
    {#if !user.twoFactorEnabled}
      <button class="secondary" aria-expanded={open === '2fa-on'} onclick={() => toggle('2fa-on')}>Zapnúť dvojstupňové overenie</button>
    {:else}
      <button class="secondary" aria-expanded={open === 'codes'} onclick={() => toggle('codes')}>Nové záložné kódy</button>
      <button class="secondary" aria-expanded={open === '2fa-off'} onclick={() => toggle('2fa-off')}>Vypnúť dvojstupňové overenie</button>
    {/if}
    {#if open === '2fa-on' && !setup}
      <form class="sub" onsubmit={startTwoFactor}>
        <label>
          <span>Súčasné heslo</span>
          <input type="password" bind:value={current} required autocomplete="current-password" />
        </label>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>Pokračovať</button>
      </form>
    {:else if open === '2fa-on' && setup}
      <form class="sub" onsubmit={finishTwoFactor}>
        <p class="note">
          1. V overovacej aplikácii (napríklad Google Authenticator, Microsoft Authenticator alebo 1Password) naskenujte
          tento kód, alebo v nej zadajte kľúč.
        </p>
        <div class="qr" aria-label="QR kód pre overovaciu aplikáciu" role="img">{@html setup.qr}</div>
        <p class="secret"><code>{setup.secret}</code></p>
        <p class="note">2. Uložte si záložné kódy. Každý platí raz a prihlásite sa ním, keď telefón nebudete mať po ruke.</p>
        <ul class="codes">{#each setup.backupCodes as c (c)}<li><code>{c}</code></li>{/each}</ul>
        <label>
          <span>3. Kód z aplikácie</span>
          <input bind:value={code} required autocomplete="one-time-code" inputmode="numeric" maxlength="6" />
        </label>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>Zapnúť</button>
      </form>
    {/if}
    {#if open === '2fa-off'}
      <form class="sub" onsubmit={stopTwoFactor}>
        <label>
          <span>Súčasné heslo</span>
          <input type="password" bind:value={current} required autocomplete="current-password" />
        </label>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>Vypnúť</button>
      </form>
    {/if}
    {#if open === 'codes'}
      {#if codes}
        <div class="sub">
          <p class="note">Nové záložné kódy; staré už neplatia. Každý platí raz.</p>
          <ul class="codes">{#each codes as c (c)}<li><code>{c}</code></li>{/each}</ul>
        </div>
      {:else}
        <form class="sub" onsubmit={makeCodes}>
          <label>
            <span>Súčasné heslo</span>
            <input type="password" bind:value={current} required autocomplete="current-password" />
          </label>
          {#if error}<p class="note error" role="alert">{error}</p>{/if}
          <button class="primary" type="submit" disabled={busy}>Vytvoriť nové kódy</button>
        </form>
      {/if}
    {/if}

    {#if passkeys || profile.passkeys.length}
      <p class="muted small">Prístupovým kľúčom (passkey) sa prihlásite odtlačkom prsta, tvárou alebo kódom zariadenia, bez hesla.</p>
      {#each profile.passkeys as k (k.id)}
        <div class="key">
          <span
            >{k.name || 'Prístupový kľúč'}<br /><span class="muted small"
              >{k.deviceType === 'multiDevice' ? 'synchronizovaný' : 'na jednom zariadení'} · pridaný
              {new Date(k.createdAt).toLocaleDateString('sk', { timeZone: 'Europe/Bratislava' })}</span
            ></span
          >
          <button class="link danger" disabled={busy} onclick={() => run(() => removePasskey(k.id), 'Prístupový kľúč sme odstránili.')}
            >Odstrániť</button
          >
        </div>
      {/each}
      {#if passkeys}
        <button class="secondary" aria-expanded={open === 'passkey'} onclick={() => toggle('passkey')}>Pridať prístupový kľúč</button>
      {/if}
      {#if open === 'passkey'}
        <form class="sub" onsubmit={savePasskey}>
          <label>
            <span>Súčasné heslo</span>
            <input type="password" bind:value={current} required autocomplete="current-password" />
          </label>
          {#if error}<p class="note error" role="alert">{error}</p>{/if}
          <button class="primary" type="submit" disabled={busy}>Pridať</button>
        </form>
      {/if}
    {/if}

    <h3 class="section">Zariadenia</h3>
    <button class="secondary" disabled={busy} onclick={() => run(signOutOthers, 'Ostatné zariadenia sme odhlásili.')}
      >Odhlásiť ostatné zariadenia</button
    >
    <button class="secondary" disabled={busy} onclick={() => run(signOut)}>Odhlásiť sa</button>

    <h3 class="section">Vaše údaje</h3>
    <a class="secondary" href="/api/auth/profile" download="mhd-nazivo-ucet.json" onclick={() => track('data_downloaded')}
      >Stiahnuť moje údaje</a
    >
    <button class="secondary danger" aria-expanded={open === 'delete'} onclick={() => toggle('delete')}>Zrušiť účet…</button>
    {#if open === 'delete'}
      <form class="sub" onsubmit={remove}>
        <p class="note">Natrvalo zmažeme váš e-mail, heslo, nastavenia aj všetky obľúbené. Vrátiť sa to nedá.</p>
        <label>
          <span>Na potvrdenie zadajte heslo</span>
          <input type="password" bind:value={current} required autocomplete="current-password" />
        </label>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary danger-fill" type="submit" disabled={busy}>Natrvalo zrušiť účet</button>
      </form>
    {/if}
    {#if error && !open}<p class="note error" role="alert">{error}</p>{/if}
    <p class="muted small foot">
      Čo s účtom ukladáme, popisuje <button class="link" onclick={() => navigate({ kind: 'privacy' })}>ochrana súkromia</button>.
    </p>
  {/if}
</Panel>

<style>
  .head-icon {
    width: 22px;
    height: 22px;
    fill: none;
    stroke: currentColor;
    stroke-width: 2;
    stroke-linecap: round;
  }
  .tabs {
    display: flex;
    background: var(--chip);
    border-radius: 10px;
    padding: 3px;
    gap: 3px;
  }
  .tabs button {
    flex: 1;
    min-height: 40px;
    border-radius: 8px;
    font-weight: 600;
    color: var(--muted);
  }
  .tabs button.active {
    background: var(--surface);
    color: var(--text);
    box-shadow: var(--shadow-sm);
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 12px;
    font-weight: 600;
    font-size: 0.9rem;
  }
  input {
    height: 46px;
    border-radius: 10px;
    border: 1.5px solid #d4d8dd;
    padding: 0 12px;
    font: inherit;
    font-size: 16px;
    font-weight: 400;
  }
  input:focus {
    outline: none;
    border-color: var(--accent);
  }
  .hint {
    margin: 6px 0 0;
  }
  button:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .foot {
    margin-top: 18px;
  }
  .link {
    color: var(--accent);
    font-weight: 600;
  }
  .forgot {
    margin-top: 12px;
    font-size: 0.9rem;
  }
  .note.ok {
    color: #0f6b38;
    background: #e3f5ea;
    padding: 8px 10px;
    border-radius: 10px;
  }
  .who {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 4px 0 4px;
    word-break: break-all;
  }
  .avatar {
    flex: none;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    background: var(--text);
    color: #fff;
    display: grid;
    place-items: center;
    font-weight: 700;
    font-size: 1.1rem;
  }
  .pref span {
    display: block;
    font-size: 0.9rem;
    margin-bottom: 6px;
  }
  .sub {
    padding: 0 2px 6px;
  }
  .danger {
    color: var(--bad-text);
  }
  .danger-fill {
    background: var(--bad);
  }
  .check {
    flex-direction: row;
    align-items: center;
    gap: 8px;
    font-weight: 400;
  }
  .check input {
    width: 18px;
    height: 18px;
  }
  .passkey {
    margin-top: 10px;
  }
  .qr {
    width: 180px;
    margin: 10px auto 4px;
  }
  .qr :global(svg) {
    display: block;
    width: 100%;
    height: auto;
  }
  .secret {
    text-align: center;
    word-break: break-all;
    margin: 0 0 8px;
  }
  .codes {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 4px 12px;
    padding: 0;
    margin: 8px 0;
    list-style: none;
    font-size: 0.95rem;
  }
  .key {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 0;
    border-bottom: 1px solid var(--line, #e6e8eb);
  }
  .danger-fill:hover {
    background: var(--bad-text);
  }
</style>
