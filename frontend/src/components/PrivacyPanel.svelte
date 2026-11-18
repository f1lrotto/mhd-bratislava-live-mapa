<script lang="ts">
  import { ANALYTICS, consent, OPTED_OUT, setConsent } from '../lib/analytics.svelte'
  import Panel from './Panel.svelte'

  // Keep this text true to what the app does: lib/analytics.svelte.ts, InstallPrompt (install-dismissed),
  // sw.js, the planner ("Moja poloha"), near me (lib/nearby.svelte.ts), the map tiles (Map.svelte) and the hosting (AGENTS.md).
</script>

<Panel tall label="Ochrana súkromia">
  {#snippet header()}
    <strong>Ochrana súkromia a cookies</strong>
  {/snippet}

  <div class="text">
    <h3 class="section">Vaša voľba</h3>
    {#if OPTED_OUT}
      <p>Prehliadač posiela signál Global Privacy Control alebo Do Not Track, preto návštevnosť nemeriame vôbec.</p>
    {:else if !ANALYTICS}
      <p>Na tejto adrese sa návštevnosť nemeria.</p>
    {:else}
      <p>
        {#if consent.choice === 'granted'}
          <b>Súhlas ste udelili.</b> Prehliadač si pamätá náhodný identifikátor pre meranie návštevnosti.
        {:else if consent.choice === 'denied'}
          <b>Súhlas ste odmietli.</b> Návštevnosť meriame len anonymne, bez cookies.
        {:else}
          <b>Zatiaľ ste sa nerozhodli.</b> Návštevnosť meriame len anonymne, bez cookies.
        {/if}
      </p>
      <div class="actions">
        <button class="primary" onclick={() => setConsent('denied')} disabled={consent.choice === 'denied'}
          >{consent.choice === 'granted' ? 'Odvolať súhlas' : 'Odmietnuť'}</button
        >
        <button class="primary" onclick={() => setConsent('granted')} disabled={consent.choice === 'granted'}>Súhlasím</button>
      </div>
    {/if}

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

    <h3 class="section">Čo sa ukladá vždy</h3>
    <p>Bez súhlasu ukladáme do prehliadača len to, čo je nevyhnutné na fungovanie stránky:</p>
    <ul>
      <li>vašu voľbu v tomto okne (<code>analytics-consent</code>, <code>__ph_opt_in_out_…</code>),</li>
      <li>že ste zavreli ponuku pridať aplikáciu na plochu (<code>install-dismissed</code>, 14 dní),</li>
      <li>súbory aplikácie v pamäti prehliadača (service worker), aby sa nainštalovaná aplikácia otvorila aj offline.</li>
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
      Stránka beží u Railway Corp. na serveri v USA. Railway pri každej požiadavke zaznamenáva technické údaje (IP adresu,
      čas a adresu požiadavky, pri hľadaní trasy teda aj jej body) na zabezpečenie prevádzky a tieto záznamy krátko
      uchováva. Prenos do USA je chránený štandardnými zmluvnými doložkami. Mapové podklady načítava prehliadač zo služby
      OpenFreeMap, ktorá pritom vidí vašu IP adresu.
    </p>

    <h3 class="section">Ako dlho</h3>
    <p>Záznamy o návštevách uchovávame v PostHog 24 mesiacov, potom sa automaticky mažú.</p>

    <h3 class="section">Vaše práva</h3>
    <p>
      Máte právo na prístup k údajom, ich opravu, vymazanie, obmedzenie spracúvania, prenosnosť, právo namietať a právo
      kedykoľvek odvolať súhlas. Údaje bez cookies nevieme priradiť ku konkrétnej osobe, preto ich spravidla nevieme
      vyhľadať. Sťažnosť môžete podať Úradu na ochranu osobných údajov SR, Hraničná 12, 820 07 Bratislava,
      <a href="https://dataprotection.gov.sk" target="_blank" rel="noopener">dataprotection.gov.sk</a>.
    </p>
    <p class="muted small">Naposledy aktualizované 17. 11. 2026.</p>
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
