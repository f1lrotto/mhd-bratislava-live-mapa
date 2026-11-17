import { mount } from 'svelte'
// IBM Plex Sans, self-hosted (OFL): the weights the UI uses. Browsers fetch only the subsets a page needs.
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-sans/700.css'
import './app.css'
import App from './App.svelte'

export default mount(App, { target: document.getElementById('app')! })

// The service worker (built into dist/sw.js) lets the installed app open offline.
if (import.meta.env.PROD && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js')
