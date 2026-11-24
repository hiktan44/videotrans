// Product-local analytics preference. The site keeps both the choice and its daily browser ID.
(() => {
  'use strict';
  const config = document.currentScript?.dataset;
  if (/^\/(admin|api|login|signup|auth)(?:\/|$)/.test(location.pathname)) return;
  if (!config || location.origin !== config.siteOrigin || document.getElementById('site-visit-preference')) return;
  const choiceKey = 'site-visits:analytics-choice:v1';
  const loadClient = () => import('/.well-known/site-visits/client.mjs');
  const read = () => { try { return localStorage.getItem(choiceKey); } catch { return null; } };
  const privacySignal = () => navigator.globalPrivacyControl === true || navigator.doNotTrack === '1';
  let withdrawn = false;
  const vetoKey = choiceKey + ':withdrawn';
  const allowed = () => {
    try { return !withdrawn && !sessionStorage.getItem(vetoKey) && read() === 'yes' && !privacySignal(); }
    catch { return false; }
  };
  const labels = document.documentElement.lang?.startsWith('en') ? {
    title: 'Visit measurement', allow: 'Allow this site to count this browser once per day',
    detail: 'The daily identifier stays on this site. Only totals go to the reporting panel. You can change this choice here.',
    blocked: 'Your browser privacy setting disables measurement.'
  } : {
    title: 'Ziyaret ölçümü', allow: 'Bu sitede tarayıcımın günde bir kez sayılmasına izin veriyorum',
    detail: 'Günlük kimlik bu sitede kalır. Rapor paneline yalnızca toplamlar gider. Tercihinizi burada değiştirebilirsiniz.',
    blocked: 'Tarayıcınızın gizlilik tercihi ölçümü kapatıyor.'
  };
  const section = document.createElement('details');
  section.id = 'site-visit-preference';
  const summary = document.createElement('summary');
  summary.textContent = labels.title;
  const label = document.createElement('label');
  const toggle = document.createElement('input');
  toggle.type = 'checkbox';
  label.append(toggle, document.createTextNode(' ' + labels.allow));
  const description = document.createElement('p');
  description.textContent = labels.detail;
  section.append(summary, label, description);
  document.body.append(section);
  let revision = 0;
  let client;
  const syncChoice = () => {
    toggle.checked = allowed();
    toggle.disabled = privacySignal();
    description.textContent = privacySignal() ? labels.blocked : labels.detail;
  };
  function localSessionAbsent() {
    const keys = config.sessionKeys?.split(',').filter(Boolean) || [];
    if (keys.some(key => localStorage.getItem(key) !== null)) return false;
    if (config.supabase === 'true') {
      for (let i = 0; i < localStorage.length; ++i) {
        if (/^sb-.+-auth-token(?:\.\d+)?$/.test(localStorage.key(i) || '')) return false;
      }
    }
    return true;
  }
  async function record() {
    const current = ++revision;
    syncChoice();
    if (!allowed() || document.visibilityState !== 'visible' || navigator.webdriver) return;
    try {
      if (!localSessionAbsent()) return;
      if (config.context === 'server') {
        // This route sees the existing session locally. It returns only a status, never an identity.
        const check = await fetch('/api/site-visit-context', { credentials: 'same-origin', cache: 'no-store',
          redirect: 'error', referrerPolicy: 'no-referrer' });
        if (check.status !== 204) return;
      }
      if (current !== revision || !allowed()) return;
      client = await loadClient();
      await client.recordPageVisit({ hasAnalyticsConsent: () => current === revision && allowed(),
        isOwner: () => !localSessionAbsent() });
    } catch { /* Blocked storage, unknown identity or an unavailable collector leaves the site usable. */ }
  }
  async function revoke() {
    ++revision;
    syncChoice();
    try { (client || await loadClient()).clearVisitIdentifier(); } catch { /* Site measurement may be disabled. */ }
  }
  toggle.addEventListener('change', () => {
    const yes = toggle.checked && !privacySignal();
    withdrawn = !yes;
    if (!yes) {
      try { sessionStorage.setItem(vetoKey, '1'); } catch {}
      try { localStorage.removeItem(choiceKey); } catch {}
      void revoke();
      return;
    }
    try {
      localStorage.setItem(choiceKey, 'yes');
      sessionStorage.removeItem(vetoKey);
    } catch { withdrawn = true; syncChoice(); return; }
    void record();
  });
  window.addEventListener('storage', event => {
    if (event.key !== choiceKey && event.key !== null) {
      if (config.sessionKeys?.split(',').includes(event.key) || (config.supabase === 'true' && event.key.startsWith('sb-'))) void record();
      return;
    }
    if (allowed()) void record(); else void revoke();
  });
  window.addEventListener('pageshow', record);
  window.addEventListener('pagehide', () => { ++revision; });
  document.addEventListener('visibilitychange', record);
  void record();
})();
