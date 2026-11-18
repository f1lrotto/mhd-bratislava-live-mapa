<script lang="ts">
  import { ANALYTICS, consent, OPTED_OUT, setConsent } from '../lib/analytics.svelte'
  import { t } from '../lib/i18n'
  import { prefs } from '../lib/prefs.svelte'
  import Panel from './Panel.svelte'

  // Keep this text true to what the app does: lib/analytics.svelte.ts, InstallPrompt (install-dismissed), lib/news.svelte.ts (news-seen),
  // lib/prefs.svelte.ts (prefs), sw.js, the planner ("Moja poloha"), near me (lib/nearby.svelte.ts), the map tiles (Map.svelte), the hosting
  // (AGENTS.md) and the accounts (auth/server.js, auth/profile.js, auth/mail.js, lib/profile.svelte.ts).
  // The English and the Slovak text must say the same: change both together.
</script>

<Panel tall label={t('Ochrana súkromia', 'Privacy')}>
  {#snippet header()}
    <strong>{t('Ochrana súkromia a cookies', 'Privacy and cookies')}</strong>
  {/snippet}

  <div class="text">
    <h3 class="section">{t('Vaša voľba', 'Your choice')}</h3>
    {#if OPTED_OUT}
      <p>
        {t(
          'Prehliadač posiela signál Global Privacy Control alebo Do Not Track, preto návštevnosť nemeriame vôbec.',
          'Your browser sends a Global Privacy Control or Do Not Track signal, so we do not measure traffic at all.',
        )}
      </p>
    {:else if !ANALYTICS}
      <p>{t('Na tejto adrese sa návštevnosť nemeria.', 'Traffic is not measured at this address.')}</p>
    {:else}
      <p>
        {#if consent.choice === 'granted'}
          <b>{t('Súhlas ste udelili.', 'You have given your consent.')}</b>
          {t('Prehliadač si pamätá náhodný identifikátor pre meranie návštevnosti.', 'Your browser remembers a random identifier for measuring traffic.')}
        {:else if consent.choice === 'denied'}
          <b>{t('Súhlas ste odmietli.', 'You have declined consent.')}</b>
          {t('Návštevnosť meriame len anonymne, bez cookies.', 'We measure traffic only anonymously, without cookies.')}
        {:else}
          <b>{t('Zatiaľ ste sa nerozhodli.', 'You have not decided yet.')}</b>
          {t('Návštevnosť meriame len anonymne, bez cookies.', 'We measure traffic only anonymously, without cookies.')}
        {/if}
      </p>
      <div class="actions">
        <button class="primary" onclick={() => setConsent('denied')} disabled={consent.choice === 'denied'}
          >{consent.choice === 'granted' ? t('Odvolať súhlas', 'Withdraw consent') : t('Odmietnuť', 'Decline')}</button
        >
        <button class="primary" onclick={() => setConsent('granted')} disabled={consent.choice === 'granted'}
          >{t('Súhlasím', 'I agree')}</button
        >
      </div>
    {/if}

    {#if prefs.lang === 'en'}
      <h3 class="section">Who processes the data</h3>
      <p>
        The operator and data controller of the website mhd.filiphupka.com is Filip Hupka. Send questions and requests to
        exercise your rights to <a href="mailto:filip.hupka@gmail.com">filip.hupka@gmail.com</a>.
      </p>

      <h3 class="section">Cookieless analytics</h3>
      <p>
        To know how many people use the site and which features are useful, we send PostHog (PostHog Inc., data stored in
        the EU, in Frankfurt) a record of the pages viewed and the features used: the page address without parameters,
        where you came from, the browser, operating system, device type, approximate country and city derived from the IP
        address, and whether you opened the site as an installed app. When planning a route or a reach map, we send only
        whether you entered a stop, your location or a point on the map (for the reach map, also the chosen number of
        minutes), never the place itself. For favourites, we send only whether you pinned or removed a stop, line or route,
        and for the account only which feature you used (creating it, signing in and how, signing out, changing the
        password or email, verifying the email, two-step verification, passkeys, changing a setting and its value,
        downloading your data, deleting the account), and, when something fails, the error code. PostHog never receives
        your email, password, codes or favourites, and we do not link visits to the account.
      </p>
      <p>
        In this mode, nothing is stored in your browser. PostHog tells visitors apart by a fingerprint of the IP address and
        browser made with a secret key that is changed and deleted every day, so the same person looks like a new visitor
        the next day. PostHog does not store the IP address. The legal basis is our legitimate interest in improving the
        service (Art. 6(1)(f) GDPR). If you do not agree with this, turn on Global Privacy Control or Do Not Track in your
        browser, or write to us.
      </p>

      <h3 class="section">With consent</h3>
      <p>
        If you consent, PostHog stores in your browser (cookies and localStorage <code>ph_…</code>) a random identifier
        and a session number, so that repeat visits are counted as one visitor. They are kept for 365 days or until you
        withdraw your consent. The legal basis is your consent (Art. 6(1)(a) GDPR and § 109(8) of Act No. 452/2021 Coll. on
        electronic communications). Withdrawing consent does not affect the lawfulness of processing before the withdrawal.
      </p>

      <h3 class="section">Account and favourites</h3>
      <p>
        An account is optional and you only need it for favourites. If you create one, we store on our server your email,
        your password in an irreversibly encrypted form (scrypt), when you created the account, your favourites with the
        date they were pinned (stops, lines and routes; for a route, its start and destination: a stop or a point on the
        map with its coordinates and name) and your app settings, such as the language. If you pin a route from or to “My
        location”, we store only that your location at the time of opening should be used, never coordinates. We also store
        whether you have verified your email. If you turn on two-step verification, we store the encrypted secret key for
        the authenticator app, the encrypted backup codes and the number of incorrect codes (after too many attempts, we
        block signing in for a while); if you choose not to be asked again on a device, also a record of that (30 days). If
        you add a passkey, we store its public part, its identifier, the authenticator model reported by the device, a
        usage counter, the way it connects (for example USB or built into the device), whether it syncs between your
        devices and the date it was added; the private part, your fingerprint and your face never leave your device.
      </p>
      <p>
        We email you only messages about your account: a link to verify your address (after you create the account and
        after you change your email), a link to set a new password when you ask for one, and, if your address is verified,
        a notice when the password, the email (sent to the previous address), two-step verification or the passkeys of the
        account change. No newsletters or advertising. They are sent by Resend (Resend, Inc., USA), which receives your
        address and the text of the message and keeps them for 30 days; the transfer to the USA is protected by standard
        contractual clauses. Links are valid for one hour. As a rule, we send at most five links to one address per day.
      </p>
      <p>
        After you sign in, your browser stores the cookie <code>__Secure-better-auth.session_token</code> with a random
        session key (90 days from your last visit or until you sign out). On the server we store the same key with its
        expiry date, but not your IP address or browser, and, for a new-password link, a fingerprint (hash) of its one-time
        key. We use your IP address only in the server's memory to limit the number of sign-in attempts, and we do not
        store it ourselves or write it to the application's logs (Railway's technical logs are described in the Server and
        map section). The legal basis is the performance of a contract, that is, providing the account you asked for (Art.
        6(1)(b) GDPR).
      </p>

      <h3 class="section">What is always stored</h3>
      <p>Without consent, we store in your browser only what is strictly necessary for the site to work:</p>
      <ul>
        <li>your choice in this window (<code>analytics-consent</code>, <code>__ph_opt_in_out_…</code>),</li>
        <li>the language you chose (<code>prefs</code>),</li>
        <li>that you closed the offer to add the app to your home screen (<code>install-dismissed</code>, 14 days),</li>
        <li>
          how many entries in the What's new window you have already seen (<code>news-seen</code>), so that we only point
          out new ones,
        </li>
        <li>the app's files in the browser's storage (service worker), so that the installed app opens even offline,</li>
        <li>if you are signed in, the session cookie (<code>__Secure-better-auth.session_token</code>), so that you stay signed in.</li>
        <li>
          when signing in with two-step verification, <code>__Secure-better-auth.two_factor</code> (10 minutes), and if you
          choose not to be asked again on the device, <code>__Secure-better-auth.trust_device</code> (30 days); with a
          passkey, <code>__Secure-better-auth.better-auth-passkey</code> (5 minutes).
        </li>
      </ul>

      <h3 class="section">Your location</h3>
      <p>
        We determine your location only after you tap “My location” or the location button on the map, and with your
        browser's permission. When planning a route or a reach map, the browser sends it to our server, which uses it to
        calculate connections; we do not store it and do not send it to PostHog. It is, however, part of the page address,
        so be careful whom you send a link to a route or reach map.
      </p>
      <p>
        Nearby departures are calculated by the browser directly on your device: it picks the nearest stops itself and
        estimates the walk to them. It sends the server only the codes of these stops to get their departures, so at most
        the server's logs can reveal which stops you were near. We track your location only while the page is open on the
        screen, and we do not store it anywhere; “Hide my location” turns tracking off. The address <code>/blizko</code>
        does not contain your location.
      </p>

      <h3 class="section">Server and map</h3>
      <p>
        Both the site and the account database run at Railway Corp. on a server in the USA. For every request, Railway
        records technical data (the IP address, the time and the address of the request, so when planning a route also its
        points) to ensure the operation of the service, and keeps these logs for a short time. The transfer to the USA is
        protected by standard contractual clauses. The browser loads the map tiles from the OpenFreeMap service, which
        sees your IP address when it does so.
      </p>

      <h3 class="section">How long</h3>
      <p>
        We keep visit records in PostHog for 24 months, after which they are deleted automatically. We keep the account,
        favourites and settings until you delete the account; we then delete them immediately. Favourites you remove are
        deleted immediately.
      </p>

      <h3 class="section">Your rights</h3>
      <p>
        You have the right of access to your data, to rectification, erasure, restriction of processing and data
        portability, the right to object and the right to withdraw your consent at any time. We cannot link cookieless data
        to a specific person, so as a rule we cannot look it up. In the Profile window you can download your account data
        (portability), correct your email and password, and delete the account yourself (erasure). You can lodge a
        complaint with the Office for Personal Data Protection of the Slovak Republic, Hraničná 12, 820 07 Bratislava,
        <a href="https://dataprotection.gov.sk" target="_blank" rel="noopener">dataprotection.gov.sk</a>.
      </p>
    {:else}
      <h3 class="section">Kto spracúva údaje</h3>
      <p>
        Prevádzkovateľom stránky mhd.filiphupka.com je Filip Hupka. S otázkami a žiadosťami o uplatnenie práv píšte na
        <a href="mailto:filip.hupka@gmail.com">filip.hupka@gmail.com</a>.
      </p>

      <h3 class="section">Meranie návštevnosti bez cookies</h3>
      <p>
        Aby sme vedeli, koľko ľudí stránku používa a ktoré funkcie sú užitočné, posielame službe PostHog (PostHog Inc., údaje
        uložené v EÚ vo Frankfurte) záznam o zobrazených stránkach a použitých funkciách: adresu stránky bez parametrov,
        odkiaľ ste prišli, prehliadač, operačný systém, typ zariadenia, približnú krajinu a mesto odvodené z IP adresy a to,
        či ste stránku otvorili ako nainštalovanú aplikáciu. Pri hľadaní trasy a mapy dosahu posielame len to, či ste
        zadali zastávku, svoju polohu alebo bod na mape (pri dosahu aj zvolený počet minút), nikdy samotné miesto.
        Pri obľúbených posielame len to, či ste pripli alebo odobrali zastávku, linku alebo trasu, a pri účte len to, ktorú funkciu ste použili
        (vytvorenie, prihlásenie a jeho spôsob, odhlásenie, zmenu hesla alebo e-mailu, overenie e-mailu, dvojstupňové
        overenie, prístupové kľúče, zmenu nastavenia a jeho hodnotu, stiahnutie údajov, zrušenie účtu), a keď sa niečo
        nepodarí, kód chyby. Váš e-mail, heslo, kódy ani obľúbené PostHog nedostane a návštevy s účtom nespájame.
      </p>
      <p>
        V tomto režime sa do prehliadača nič neukladá. PostHog rozlišuje návštevníkov podľa odtlačku z IP adresy a
        prehliadača s tajným kľúčom, ktorý sa každý deň mení a maže, takže ten istý človek na druhý deň vyzerá ako nový. IP
        adresu PostHog neukladá. Právnym základom je náš oprávnený záujem na zlepšovaní služby (čl. 6 ods. 1 písm. f) GDPR).
        Ak s tým nesúhlasíte, zapnite v prehliadači Global Privacy Control alebo Do Not Track, alebo nám napíšte.
      </p>

      <h3 class="section">So súhlasom</h3>
      <p>
        Ak súhlasíte, PostHog si v prehliadači uloží (cookies a localStorage <code>ph_…</code>) náhodný identifikátor
        a číslo relácie, aby sa opakované návštevy počítali ako jeden návštevník. Uloženie platí 365 dní alebo kým súhlas
        neodvoláte. Právnym základom je váš súhlas (čl. 6 ods. 1 písm. a) GDPR a § 109 ods. 8 zákona č. 452/2021 Z. z. o
        elektronických komunikáciách). Odvolanie súhlasu neovplyvní zákonnosť spracúvania pred ním.
      </p>

      <h3 class="section">Účet a obľúbené</h3>
      <p>
        Účet je dobrovoľný a potrebujete ho len na obľúbené. Ak si ho vytvoríte, na našom serveri uložíme váš e-mail, heslo
        v nevratne zašifrovanej podobe (scrypt), kedy ste účet vytvorili, vaše obľúbené s dátumom pripnutia (zastávky, linky a trasy; pri trase
        jej začiatok a cieľ: zastávku alebo bod na mape s jeho súradnicami a názvom) a nastavenia aplikácie, napríklad jazyk.
        Ak pripnete trasu z alebo do „Moja poloha“, uložíme len to, že sa má použiť poloha v čase otvorenia, nikdy
        súradnice. Ukladáme aj to, či ste e-mail overili. Ak si zapnete dvojstupňové overenie, uložíme zašifrovaný tajný
        kľúč pre overovaciu aplikáciu, zašifrované záložné kódy a počet nesprávnych kódov (po priveľa pokusoch
        prihlásenie na chvíľu zablokujeme); ak zvolíte, že sa na zariadení netreba pýtať, aj záznam o tom (30 dní). Ak si
        pridáte prístupový kľúč (passkey), uložíme jeho verejnú časť, identifikátor, model overovača, ktorý zariadenie
        uvedie, počítadlo použití, spôsob pripojenia (napríklad USB alebo v zariadení), či sa synchronizuje medzi vašimi
        zariadeniami a dátum pridania; súkromná časť, odtlačok prsta ani tvár vaše zariadenie neopustia.
      </p>
      <p>
        Na e-mail vám posielame len správy k účtu: odkaz na overenie adresy (po vytvorení účtu a zmene e-mailu), odkaz na
        nové heslo, keď oň požiadate, a ak je adresa overená, upozornenie, keď sa na účte zmení heslo, e-mail (na pôvodnú
        adresu), dvojstupňové overenie alebo prístupové kľúče. Žiadne novinky ani reklamu. Posiela ich služba Resend (Resend, Inc., USA), ktorá
        dostane vašu adresu a text správy a uchováva ich 30 dní; prenos do USA je chránený štandardnými zmluvnými
        doložkami. Odkazy platia hodinu. Jednej adrese pošleme spravidla najviac päť odkazov za deň.
      </p>
      <p>
        Po prihlásení si prehliadač uloží cookie <code>__Secure-better-auth.session_token</code> s náhodným kľúčom relácie
        (90 dní od poslednej návštevy alebo do odhlásenia). Na serveri k nej ukladáme ten istý kľúč a dátum platnosti, nie
        však IP adresu ani prehliadač, a pri odkaze na nové heslo odtlačok (hash) jeho jednorazového kľúča. IP adresu používame len v pamäti
        servera na obmedzenie počtu pokusov o prihlásenie a sami ju neukladáme ani nezapisujeme do záznamov aplikácie
        (technické záznamy Railway popisuje časť Server a mapa). Právnym základom je
        plnenie zmluvy, teda poskytnutie účtu, o ktorý ste požiadali (čl. 6 ods. 1 písm. b) GDPR).
      </p>

      <h3 class="section">Čo sa ukladá vždy</h3>
      <p>Bez súhlasu ukladáme do prehliadača len to, čo je nevyhnutné na fungovanie stránky:</p>
      <ul>
        <li>vašu voľbu v tomto okne (<code>analytics-consent</code>, <code>__ph_opt_in_out_…</code>),</li>
        <li>jazyk, ktorý ste si vybrali (<code>prefs</code>),</li>
        <li>že ste zavreli ponuku pridať aplikáciu na plochu (<code>install-dismissed</code>, 14 dní),</li>
        <li>koľko noviniek v okne Čo je nové ste už videli (<code>news-seen</code>), aby sme vás upozornili len na nové,</li>
        <li>súbory aplikácie v pamäti prehliadača (service worker), aby sa nainštalovaná aplikácia otvorila aj offline,</li>
        <li>ak ste prihlásení, cookie relácie (<code>__Secure-better-auth.session_token</code>), aby ste zostali prihlásení.</li>
        <li>
          pri prihlasovaní s dvojstupňovým overením <code>__Secure-better-auth.two_factor</code> (10 minút), a ak zvolíte, že sa
          na zariadení netreba pýtať, <code>__Secure-better-auth.trust_device</code> (30 dní); pri prístupovom kľúči
          <code>__Secure-better-auth.better-auth-passkey</code> (5 minút).
        </li>
      </ul>

      <h3 class="section">Vaša poloha</h3>
      <p>
        Polohu zisťujeme len po ťuknutí na „Moja poloha“ alebo na tlačidlo polohy na mape a s povolením prehliadača. Pri
        hľadaní trasy alebo mapy dosahu ju prehliadač pošle nášmu serveru, ktorý z nej vypočíta spojenia; neukladáme ju a
        neposielame ju službe PostHog. Je však súčasťou adresy stránky, preto si dajte pozor, komu odkaz na trasu alebo
        dosah pošlete.
      </p>
      <p>
        Odchody v okolí počíta prehliadač priamo vo vašom zariadení: sám vyberie najbližšie zastávky a odhadne cestu k nim
        pešo. Serveru posiela len kódy týchto zastávok, aby dostal ich odchody, takže z jeho záznamov sa dá vyčítať najviac
        to, pri ktorých zastávkach ste boli. Polohu sledujeme, len kým je stránka otvorená na obrazovke, a nikam ju
        neukladáme; „Skryť moju polohu“ sledovanie vypne. Adresa <code>/blizko</code> polohu neobsahuje.
      </p>

      <h3 class="section">Server a mapa</h3>
      <p>
        Stránka aj databáza účtov bežia u Railway Corp. na serveri v USA. Railway pri každej požiadavke zaznamenáva technické údaje (IP adresu,
        čas a adresu požiadavky, pri hľadaní trasy teda aj jej body) na zabezpečenie prevádzky a tieto záznamy krátko
        uchováva. Prenos do USA je chránený štandardnými zmluvnými doložkami. Mapové podklady načítava prehliadač zo služby
        OpenFreeMap, ktorá pritom vidí vašu IP adresu.
      </p>

      <h3 class="section">Ako dlho</h3>
      <p>
        Záznamy o návštevách uchovávame v PostHog 24 mesiacov, potom sa automaticky mažú. Účet, obľúbené a nastavenia
        uchovávame, kým účet nezrušíte; vtedy ich hneď zmažeme. Odobraté obľúbené mažeme hneď.
      </p>

      <h3 class="section">Vaše práva</h3>
      <p>
        Máte právo na prístup k údajom, ich opravu, vymazanie, obmedzenie spracúvania, prenosnosť, právo namietať a právo
        kedykoľvek odvolať súhlas. Údaje bez cookies nevieme priradiť ku konkrétnej osobe, preto ich spravidla nevieme
        vyhľadať. V okne Profil si údaje účtu stiahnete (prenosnosť), opravíte
        e-mail aj heslo a účet sami zrušíte (vymazanie). Sťažnosť môžete podať Úradu na ochranu osobných údajov SR, Hraničná 12, 820 07 Bratislava,
        <a href="https://dataprotection.gov.sk" target="_blank" rel="noopener">dataprotection.gov.sk</a>.
      </p>
    {/if}
    <p class="muted small">{t('Naposledy aktualizované 18. 11. 2026.', 'Last updated 18 November 2026.')}</p>
  </div>
</Panel>

<style>
  .text p,
  .text li {
    font-size: 0.92rem;
    line-height: 1.5;
  }
  .text p {
    margin: 0 0 8px;
  }
  .text ul {
    margin: 0 0 8px;
    padding-left: 20px;
  }
  .text a {
    color: var(--accent);
  }
  code {
    font-size: 0.82rem;
    background: var(--chip);
    border-radius: 4px;
    padding: 0 3px;
  }
  .actions {
    display: flex;
    gap: 8px;
    margin-bottom: 8px;
  }
  .actions button {
    flex: 1;
  }
  .actions button:disabled {
    opacity: 0.35;
    cursor: default;
  }
</style>
