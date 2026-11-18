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
    setLang,
    setTheme,
    setPreferences,
    signIn,
    signOut,
    signOutOthers,
  } from '../lib/profile.svelte'
  import { app, navigate } from '../lib/state.svelte'
  import { track } from '../lib/analytics.svelte'
  import { locale, t } from '../lib/i18n'
  import { prefs } from '../lib/prefs.svelte'
  import Panel from './Panel.svelte'

  // Links in account emails return here: ?token= (set a new password), ?overene=1 (address
  // verified), ?error= (an expired or used link). The URL is cleaned once read.
  const q = new URLSearchParams(location.search)
  let resetToken = $state(q.get('token'))
  let notice = $state<string | null>(
    q.get('error')
      ? t('Odkaz z e-mailu už neplatí. Požiadajte o nový.', 'This email link is no longer valid. Please request a new one.')
      : q.get('overene') === '1'
        ? t('E-mail je overený. Ďakujeme.', 'Your email is verified. Thank you.')
        : null,
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

  /** The message for an error code of the accounts server, in the current language. */
  const message = (code: string): string | undefined => {
    const exists = t('Účet s týmto e-mailom už existuje. Prihláste sa.', 'An account with this email already exists. Please sign in.')
    const unknownKey = t('Tento prístupový kľúč nepoznáme.', "We don't recognise this passkey.")
    return (
      {
        INVALID_EMAIL_OR_PASSWORD: t('Nesprávny e-mail alebo heslo.', 'Incorrect email or password.'),
        INVALID_EMAIL: t('Toto nie je platná e-mailová adresa.', "That isn't a valid email address."),
        INVALID_PASSWORD: t('Nesprávne heslo.', 'Incorrect password.'),
        PASSWORD_TOO_SHORT: t('Heslo musí mať aspoň 8 znakov.', 'The password must be at least 8 characters long.'),
        PASSWORD_TOO_LONG: t('Heslo môže mať najviac 128 znakov.', 'The password can be at most 128 characters long.'),
        USER_ALREADY_EXISTS: exists,
        USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL: exists,
        INVALID_TOKEN: t('Odkaz z e-mailu už neplatí. Požiadajte o nový.', 'This email link is no longer valid. Please request a new one.'),
        TOO_MANY_REQUESTS: t('Priveľa pokusov. Skúste to o chvíľu znova.', 'Too many attempts. Please try again in a moment.'),
        TOO_MANY_PASSKEYS: t('Viac prístupových kľúčov už pridať nemôžete. Najprv niektorý odstráňte.', "You can't add any more passkeys. Remove one first."),
        INVALID_CODE: t('Nesprávny kód.', 'Incorrect code.'),
        INVALID_BACKUP_CODE: t('Nesprávny záložný kód.', 'Incorrect backup code.'),
        INVALID_TWO_FACTOR_COOKIE: t('Overenie vypršalo. Prihláste sa znova.', 'The verification has expired. Please sign in again.'),
        TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE: t('Priveľa nesprávnych kódov. Prihláste sa znova.', 'Too many incorrect codes. Please sign in again.'),
        ACCOUNT_TEMPORARILY_LOCKED: t('Priveľa nesprávnych kódov. Skúste to neskôr.', 'Too many incorrect codes. Please try again later.'),
        PASSKEY_CANCELLED: t('Prístupový kľúč sa nepoužil.', "The passkey wasn't used."),
        PASSKEY_FAILED: t('Prístupový kľúč sa nepodarilo použiť.', "Couldn't use the passkey."),
        PREVIOUSLY_REGISTERED: t('Tento prístupový kľúč už máte pridaný.', "You've already added this passkey."),
        AUTHENTICATION_FAILED: unknownKey,
        PASSKEY_NOT_FOUND: unknownKey,
        SESSION_NOT_FRESH: t('Z bezpečnosti sa odhláste, znova prihláste a skúste to potom.', 'For security, sign out, sign in again and then try once more.'),
      } as Record<string, string>
    )[code]
  }
  const errorText = (e: unknown) => message((e as Error).message) ?? t('Nepodarilo sa to. Skúste to znova.', "That didn't work. Please try again.")

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
        notice = t(
          `Ak k adrese ${to} existuje účet, poslali sme na ňu odkaz na nové heslo.`,
          `If there's an account for ${to}, we've sent it a link to set a new password.`,
        )
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
        notice = profile.mail
          ? t(
              `Účet je vytvorený. Na ${profile.user?.email} sme poslali odkaz na overenie adresy.`,
              `Your account is ready. We've sent a link to ${profile.user?.email} to verify the address.`,
            )
          : t('Účet je vytvorený.', 'Your account is ready.')
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
    else if (error === message('INVALID_TWO_FACTOR_COOKIE') || error === message('TOO_MANY_ATTEMPTS_REQUEST_NEW_CODE')) codeStep = false
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
      notice = t(
        'Dvojstupňové overenie je zapnuté. Pri prihlásení vás požiadame aj o kód z aplikácie.',
        "Two-step verification is on. When you sign in, we'll also ask for a code from the app.",
      )
    }
  }

  async function stopTwoFactor(e: SubmitEvent) {
    e.preventDefault()
    if (await run(() => disableTwoFactor(current))) {
      toggle(null)
      notice = t('Dvojstupňové overenie je vypnuté.', 'Two-step verification is off.')
    }
  }

  async function savePasskey(e: SubmitEvent) {
    e.preventDefault()
    const pw = current
    if (await run(() => addPasskey(pw))) {
      toggle(null)
      notice = t('Prístupový kľúč je pridaný.', 'The passkey has been added.')
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
      notice = t(
        'Heslo je zmenené a všetky zariadenia sme odhlásili. Prihláste sa novým heslom.',
        "Your password has been changed and we've signed out all devices. Sign in with your new password.",
      )
      await signOut().catch(() => {})
    }
  }

  async function savePassword(e: SubmitEvent) {
    e.preventDefault()
    const ok = await run(() => changePassword(current, next))
    if (!ok && error === message('INVALID_PASSWORD')) error = t('Súčasné heslo nie je správne.', 'Your current password is incorrect.')
    if (ok) {
      toggle(null)
      notice = t('Heslo je zmenené. Ostatné zariadenia sme odhlásili.', "Your password has been changed. We've signed out your other devices.")
    }
  }

  async function saveEmail(e: SubmitEvent) {
    e.preventDefault()
    const to = newEmail.trim()
    if (await run(() => changeEmail(to, current))) {
      toggle(null)
      notice = t(
        `Na ${to} sme poslali odkaz. E-mail sa zmení, keď ho otvoríte.`,
        `We've sent a link to ${to}. Your email will change once you open it.`,
      )
    }
  }

  async function remove(e: SubmitEvent) {
    e.preventDefault()
    if (await run(() => deleteAccount(current))) {
      open = null
      current = ''
      notice = t('Účet aj všetky vaše údaje sme zmazali.', "We've deleted your account and all your data.")
    }
  }

  const pendingText = $derived.by(() => {
    const p = profile.pending
    if (!p) return null
    if (p.kind === 'line') return t(`linku ${p.ref}`, `line ${p.ref}`)
    if (p.kind === 'station') return t(`zastávku ${app.stations[p.ref]?.name ?? p.ref}`, `the stop ${app.stations[p.ref]?.name ?? p.ref}`)
    return t('túto trasu', 'this route')
  })
  const title = $derived(
    resetToken
      ? t('Nové heslo', 'New password')
      : profile.user || profile.failed
        ? t('Profil', 'Profile')
        : codeStep
          ? t('Overenie', 'Verification')
          : mode === 'sign-up'
            ? t('Nový účet', 'New account')
            : mode === 'forgot'
              ? t('Zabudnuté heslo', 'Forgotten password')
              : t('Prihlásenie', 'Sign in'),
  )
  const dateFmt = $derived(new Intl.DateTimeFormat(locale(), { timeZone: 'Europe/Bratislava' }))
  const start = $derived(profile.preferences.start ?? 'favorites')
</script>

{#snippet currentPassword()}
  <label>
    <span>{t('Súčasné heslo', 'Current password')}</span>
    <input type="password" bind:value={current} required autocomplete="current-password" />
  </label>
{/snippet}

{#snippet privacyFoot()}
  <p class="muted small foot">
    {#if prefs.lang === 'en'}
      What we store with an account is described under <button class="link" onclick={() => navigate({ kind: 'privacy' })}>Privacy</button>.
    {:else}
      Čo s účtom ukladáme, popisuje <button class="link" onclick={() => navigate({ kind: 'privacy' })}>ochrana súkromia</button>.
    {/if}
  </p>
{/snippet}

<!-- On phones the sheet is full height for the forms, so the keyboard doesn't hide the fields. -->
<Panel tall label={title} expand={!profile.user || !!resetToken || open != null}>
  {#snippet header()}
    <svg class="head-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></svg>
    <strong>{title}</strong>
  {/snippet}

  {#if notice}<p class="note ok" role="status">{notice}</p>{/if}

  {#if !profile.loaded}
    <p class="note">{t('Načítavam…', 'Loading…')}</p>
  {:else if resetToken}
    <form onsubmit={reset}>
      <label>
        <span>{t('Nové heslo', 'New password')}</span>
        <input type="password" bind:value={next} required minlength="8" maxlength="128" autocomplete="new-password" />
      </label>
      <p class="muted small hint">{t('Aspoň 8 znakov. Po zmene odhlásime všetky zariadenia.', "At least 8 characters. Once it's changed, we'll sign out all devices.")}</p>
      {#if error}<p class="note error" role="alert">{error}</p>{/if}
      <button class="primary" type="submit" disabled={busy}>{t('Nastaviť heslo', 'Set password')}</button>
    </form>
  {:else if !profile.user && codeStep}
    <form onsubmit={submitCode}>
      <label>
        <span>{useBackup ? t('Záložný kód', 'Backup code') : t('Kód z overovacej aplikácie', 'Code from your authenticator app')}</span>
        <input
          bind:value={code}
          required
          autocomplete="one-time-code"
          inputmode={useBackup ? 'text' : 'numeric'}
          spellcheck="false"
          maxlength="32"
        />
      </label>
      <label class="check"><input type="checkbox" bind:checked={trustDevice} /> {t('Na tomto zariadení sa 30 dní nepýtať', "Don't ask again on this device for 30 days")}</label>
      {#if error}<p class="note error" role="alert">{error}</p>{/if}
      <button class="primary" type="submit" disabled={busy}>{t('Overiť', 'Verify')}</button>
    </form>
    <button class="link forgot" onclick={() => ((useBackup = !useBackup), (code = ''), (error = null))}
      >{useBackup
        ? t('Použiť kód z aplikácie', 'Use a code from the app')
        : t('Nemáte aplikáciu po ruke? Použite záložný kód', "Don't have the app to hand? Use a backup code")}</button
    >
    <button class="link forgot" onclick={() => ((codeStep = false), (error = null))}>{t('Späť na prihlásenie', 'Back to sign-in')}</button>
  {:else if !profile.user && profile.failed}
    <!-- Offline or a deploy: the user may well be signed in, so don't ask them to sign in. -->
    <p class="note error">{t('Účet sa teraz nedá načítať. Skontrolujte pripojenie a skúste to znova.', "Your account can't be loaded right now. Check your connection and try again.")}</p>
    <button class="secondary" disabled={busy} onclick={() => run(() => loadProfile(0))}>{t('Skúsiť znova', 'Try again')}</button>
  {:else if !profile.user}
    {#if mode !== 'forgot'}
      <div class="tabs" role="group" aria-label={t('Prihlásenie alebo nový účet', 'Sign in or create an account')}>
        <button class:active={mode === 'sign-in'} aria-pressed={mode === 'sign-in'} onclick={() => setMode('sign-in')}>{t('Prihlásiť sa', 'Sign in')}</button>
        <button class:active={mode === 'sign-up'} aria-pressed={mode === 'sign-up'} onclick={() => setMode('sign-up')}>{t('Vytvoriť účet', 'Create account')}</button>
      </div>
      {#if pendingText}
        <p class="note">
          {mode === 'sign-in'
            ? t(`Po prihlásení si pripnete ${pendingText}.`, `Once you've signed in, ${pendingText} will be pinned.`)
            : t(`Po vytvorení účtu si pripnete ${pendingText}.`, `Once you've created your account, ${pendingText} will be pinned.`)}
        </p>
      {:else if !notice}
        <p class="note">
          {t(
            'Účet uchová vaše obľúbené zastávky, linky a trasy a vaše nastavenia, aby ste ich mali na každom zariadení.',
            'An account keeps your favourite stops, lines and routes and your settings, so you have them on every device.',
          )}
        </p>
      {/if}
    {:else}
      <p class="note">{t('Zadajte e-mail svojho účtu. Pošleme naň odkaz, ktorým si nastavíte nové heslo.', "Enter your account's email. We'll send it a link to set a new password.")}</p>
    {/if}
    <form onsubmit={submit}>
      <label>
        <span>{t('E-mail', 'Email')}</span>
        <input type="email" bind:value={email} required autocomplete="email" inputmode="email" spellcheck="false" />
      </label>
      {#if mode !== 'forgot'}
        <label>
          <span>{t('Heslo', 'Password')}</span>
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
          {t('Aspoň 8 znakov.', 'At least 8 characters.')}
          {#if profile.mail}
            {t('Na e-mail vám pošleme odkaz na overenie adresy.', "We'll email you a link to verify your address.")}
          {:else}
            {t(
              'Zabudnuté heslo zatiaľ nevieme obnoviť e-mailom, uložte si ho preto do správcu hesiel.',
              "We can't yet reset a forgotten password by email, so keep it in a password manager.",
            )}
          {/if}
        </p>
      {/if}
      {#if error}<p class="note error" role="alert">{error}</p>{/if}
      <button class="primary" type="submit" disabled={busy}
        >{mode === 'sign-in' ? t('Prihlásiť sa', 'Sign in') : mode === 'sign-up' ? t('Vytvoriť účet', 'Create account') : t('Poslať odkaz', 'Send link')}</button
      >
    </form>
    {#if mode === 'sign-in' && passkeys}
      <button class="secondary passkey" disabled={busy} onclick={passkeySignIn}>{t('Prihlásiť sa prístupovým kľúčom', 'Sign in with a passkey')}</button>
    {/if}
    {#if mode === 'sign-in' && profile.mail}
      <button class="link forgot" onclick={() => setMode('forgot')}>{t('Zabudli ste heslo?', 'Forgotten your password?')}</button>
    {:else if mode === 'forgot'}
      <button class="link forgot" onclick={() => setMode('sign-in')}>{t('Späť na prihlásenie', 'Back to sign-in')}</button>
    {/if}
    {@render privacyFoot()}
  {:else}
    {@const user = profile.user}
    <div class="who">
      <span class="avatar" aria-hidden="true">{user.email[0].toUpperCase()}</span>
      <div>
        <b>{user.email}</b><br />
        <span class="muted small">
          {user.emailVerified ? t('Overený e-mail', 'Verified email') : t('Neoverený e-mail', 'Unverified email')} · {t('účet od', 'account since')}
          {dateFmt.format(new Date(user.createdAt))}
        </span>
      </div>
    </div>
    {#if !user.emailVerified && profile.mail}
      <p class="note warn">
        {t('Overte svoj e-mail, aby sme vedeli, že adresa patrí vám.', 'Please verify your email so we know the address is yours.')}
        <button
          class="link"
          disabled={busy}
          onclick={() =>
            run(
              resendVerification,
              t(
                `Odkaz posielame na ${user.email}, najviac jeden za 2 minúty. Ak nepríde, pozrite aj do spamu.`,
                `We're sending a link to ${user.email}, at most one every 2 minutes. If it doesn't arrive, check your spam folder too.`,
              ),
            )}>{t('Poslať odkaz znova', 'Resend link')}</button
        >
      </p>
    {/if}
    <button class="secondary" onclick={() => navigate({ kind: 'favorites' })}>{t('Moje obľúbené', 'My favourites')} ({profile.favorites.length})</button>

    <h3 class="section">{t('Nastavenia', 'Settings')}</h3>
    <!-- Each preference is a key of Preferences (lib/profile.svelte.ts, auth/profile.js). -->
    <div class="pref">
      <span id="pref-lang">{t('Jazyk', 'Language')}</span>
      <div class="tabs" role="group" aria-labelledby="pref-lang">
        <button lang="sk" class:active={prefs.lang === 'sk'} aria-pressed={prefs.lang === 'sk'} onclick={() => run(() => setLang('sk'))}
          >Slovenčina</button
        >
        <button lang="en" class:active={prefs.lang === 'en'} aria-pressed={prefs.lang === 'en'} onclick={() => run(() => setLang('en'))}
          >English</button
        >
      </div>
    </div>
    <div class="pref">
      <span id="pref-start">{t('Nainštalovaná aplikácia sa otvorí na', 'The installed app opens on')}</span>
      <div class="tabs" role="group" aria-labelledby="pref-start">
        <button class:active={start === 'favorites'} aria-pressed={start === 'favorites'} onclick={() => run(() => setPreferences({ start: null }))}
          >{t('Obľúbených', 'Favourites')}</button
        >
        <button class:active={start === 'map'} aria-pressed={start === 'map'} onclick={() => run(() => setPreferences({ start: 'map' }))}
          >{t('Mape', 'Map')}</button
        >
      </div>
    </div>
    <div class="pref">
      <span id="pref-theme">{t('Vzhľad', 'Appearance')}</span>
      <div class="tabs" role="group" aria-labelledby="pref-theme">
        {#each [[null, t('Automaticky', 'Automatic')], ['light', t('Svetlý', 'Light')], ['dark', t('Tmavý', 'Dark')]] as const as [value, label] (value)}
          <button class:active={prefs.theme === value} aria-pressed={prefs.theme === value} onclick={() => run(() => setTheme(value))}>{label}</button>
        {/each}
      </div>
    </div>

    <h3 class="section">{t('Prihlásenie', 'Sign-in')}</h3>
    <button class="secondary" aria-expanded={open === 'password'} onclick={() => toggle('password')}>{t('Zmeniť heslo', 'Change password')}</button>
    {#if open === 'password'}
      <form class="sub" onsubmit={savePassword}>
        {@render currentPassword()}
        <label>
          <span>{t('Nové heslo', 'New password')}</span>
          <input type="password" bind:value={next} required minlength="8" maxlength="128" autocomplete="new-password" />
        </label>
        <p class="muted small hint">{t('Aspoň 8 znakov. Ostatné zariadenia odhlásime.', "At least 8 characters. We'll sign out your other devices.")}</p>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>{t('Uložiť heslo', 'Save password')}</button>
      </form>
    {/if}
    <!-- The new address must confirm with a link, so changing it needs email. -->
    {#if profile.mail}
    <button class="secondary" aria-expanded={open === 'email'} onclick={() => toggle('email')}>{t('Zmeniť e-mail', 'Change email')}</button>
    {/if}
    {#if open === 'email'}
      <form class="sub" onsubmit={saveEmail}>
        <label>
          <span>{t('Nový e-mail', 'New email')}</span>
          <input type="email" bind:value={newEmail} required autocomplete="email" inputmode="email" spellcheck="false" />
        </label>
        {@render currentPassword()}
        <p class="muted small hint">{t('Na novú adresu pošleme odkaz; e-mail sa zmení, keď ho otvoríte.', "We'll send a link to the new address; your email changes once you open it.")}</p>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>{t('Zmeniť e-mail', 'Change email')}</button>
      </form>
    {/if}

    <h3 class="section">{t('Zabezpečenie', 'Security')}</h3>
    <p class="muted small">
      {#if prefs.lang === 'en'}
        Two-step verification: <b>{user.twoFactorEnabled ? 'on' : 'off'}</b>. When you sign in with your password, we'll then
        also ask for a code from the authenticator app on your phone.
      {:else}
        Dvojstupňové overenie: <b>{user.twoFactorEnabled ? 'zapnuté' : 'vypnuté'}</b>. Pri prihlásení heslom si potom
        vypýtame aj kód z overovacej aplikácie v telefóne.
      {/if}
    </p>
    {#if !user.twoFactorEnabled}
      <button class="secondary" aria-expanded={open === '2fa-on'} onclick={() => toggle('2fa-on')}>{t('Zapnúť dvojstupňové overenie', 'Turn on two-step verification')}</button>
    {:else}
      <button class="secondary" aria-expanded={open === 'codes'} onclick={() => toggle('codes')}>{t('Nové záložné kódy', 'New backup codes')}</button>
      <button class="secondary" aria-expanded={open === '2fa-off'} onclick={() => toggle('2fa-off')}>{t('Vypnúť dvojstupňové overenie', 'Turn off two-step verification')}</button>
    {/if}
    {#if open === '2fa-on' && !setup}
      <form class="sub" onsubmit={startTwoFactor}>
        {@render currentPassword()}
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>{t('Pokračovať', 'Continue')}</button>
      </form>
    {:else if open === '2fa-on' && setup}
      <form class="sub" onsubmit={finishTwoFactor}>
        <p class="note">
          {#if prefs.lang === 'en'}
            1. In your authenticator app (for example Google Authenticator, Microsoft Authenticator or 1Password), scan this
            code or enter the key.
          {:else}
            1. V overovacej aplikácii (napríklad Google Authenticator, Microsoft Authenticator alebo 1Password) naskenujte
            tento kód, alebo v nej zadajte kľúč.
          {/if}
        </p>
        <div class="qr" aria-label={t('QR kód pre overovaciu aplikáciu', 'QR code for the authenticator app')} role="img">{@html setup.qr}</div>
        <p class="secret"><code>{setup.secret}</code></p>
        <p class="note">
          {t(
            '2. Uložte si záložné kódy. Každý platí raz a prihlásite sa ním, keď telefón nebudete mať po ruke.',
            "2. Save the backup codes. Each works once and lets you sign in when you don't have your phone to hand.",
          )}
        </p>
        <ul class="codes">{#each setup.backupCodes as c (c)}<li><code>{c}</code></li>{/each}</ul>
        <label>
          <span>{t('3. Kód z aplikácie', '3. Code from the app')}</span>
          <input bind:value={code} required autocomplete="one-time-code" inputmode="numeric" maxlength="6" />
        </label>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>{t('Zapnúť', 'Turn on')}</button>
      </form>
    {/if}
    {#if open === '2fa-off'}
      <form class="sub" onsubmit={stopTwoFactor}>
        {@render currentPassword()}
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy}>{t('Vypnúť', 'Turn off')}</button>
      </form>
    {/if}
    {#if open === 'codes'}
      {#if codes}
        <div class="sub">
          <p class="note">{t('Nové záložné kódy; staré už neplatia. Každý platí raz.', 'New backup codes; the old ones no longer work. Each works once.')}</p>
          <ul class="codes">{#each codes as c (c)}<li><code>{c}</code></li>{/each}</ul>
        </div>
      {:else}
        <form class="sub" onsubmit={makeCodes}>
          {@render currentPassword()}
          {#if error}<p class="note error" role="alert">{error}</p>{/if}
          <button class="primary" type="submit" disabled={busy}>{t('Vytvoriť nové kódy', 'Create new codes')}</button>
        </form>
      {/if}
    {/if}

    {#if passkeys || profile.passkeys.length}
      <p class="muted small">
        {t(
          'Prístupovým kľúčom (passkey) sa prihlásite odtlačkom prsta, tvárou alebo kódom zariadenia, bez hesla.',
          "With a passkey you sign in with your fingerprint, face or device PIN, without a password.",
        )}
      </p>
      {#each profile.passkeys as k (k.id)}
        <div class="key">
          <span
            >{k.name || t('Prístupový kľúč', 'Passkey')}<br /><span class="muted small"
              >{k.deviceType === 'multiDevice' ? t('synchronizovaný', 'synced') : t('na jednom zariadení', 'on one device')} · {t('pridaný', 'added')}
              {dateFmt.format(new Date(k.createdAt))}</span
            ></span
          >
          <button class="link danger" disabled={busy} onclick={() => run(() => removePasskey(k.id), t('Prístupový kľúč sme odstránili.', "We've removed the passkey."))}
            >{t('Odstrániť', 'Remove')}</button
          >
        </div>
      {/each}
      {#if passkeys}
        <button class="secondary" aria-expanded={open === 'passkey'} onclick={() => toggle('passkey')}>{t('Pridať prístupový kľúč', 'Add a passkey')}</button>
      {/if}
      {#if open === 'passkey'}
        <form class="sub" onsubmit={savePasskey}>
          {@render currentPassword()}
          {#if error}<p class="note error" role="alert">{error}</p>{/if}
          <button class="primary" type="submit" disabled={busy}>{t('Pridať', 'Add')}</button>
        </form>
      {/if}
    {/if}

    <h3 class="section">{t('Zariadenia', 'Devices')}</h3>
    <button class="secondary" disabled={busy} onclick={() => run(signOutOthers, t('Ostatné zariadenia sme odhlásili.', "We've signed out your other devices."))}
      >{t('Odhlásiť ostatné zariadenia', 'Sign out other devices')}</button
    >
    <button class="secondary" disabled={busy} onclick={() => run(signOut)}>{t('Odhlásiť sa', 'Sign out')}</button>

    <h3 class="section">{t('Vaše údaje', 'Your data')}</h3>
    <a class="secondary" href="/api/auth/profile" download="mhd-nazivo-ucet.json" onclick={() => track('data_downloaded')}
      >{t('Stiahnuť moje údaje', 'Download my data')}</a
    >
    <button class="secondary danger" aria-expanded={open === 'delete'} onclick={() => toggle('delete')}>{t('Zrušiť účet…', 'Delete account…')}</button>
    {#if open === 'delete'}
      <form class="sub" onsubmit={remove}>
        <p class="note">
          {t(
            'Natrvalo zmažeme váš e-mail, heslo, nastavenia aj všetky obľúbené. Vrátiť sa to nedá.',
            "We'll permanently delete your email, password, settings and all your favourites. This can't be undone.",
          )}
        </p>
        <label>
          <span>{t('Na potvrdenie zadajte heslo', 'Enter your password to confirm')}</span>
          <input type="password" bind:value={current} required autocomplete="current-password" />
        </label>
        {#if error}<p class="note error" role="alert">{error}</p>{/if}
        <button class="primary danger-fill" type="submit" disabled={busy}>{t('Natrvalo zrušiť účet', 'Permanently delete account')}</button>
      </form>
    {/if}
    {#if error && !open}<p class="note error" role="alert">{error}</p>{/if}
    {@render privacyFoot()}
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
    border: 1.5px solid var(--border);
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
    color: var(--ok-text);
    background: var(--ok-bg);
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
    color: var(--on-text);
    display: grid;
    place-items: center;
    font-weight: 700;
    font-size: 1.1rem;
  }
  .pref + .pref {
    margin-top: 14px;
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
    border-bottom: 1px solid var(--line);
  }
  .danger-fill:hover {
    background: var(--bad-text);
  }
</style>
