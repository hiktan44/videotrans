// Invoke from the site's existing analytics-consent handler after a real opt-in.
const key = 'site-sayaci:istanbul-day:v1';
export function clearVisitIdentifier() {
  try { localStorage.removeItem(key); } catch { /* Storage may be unavailable. */ }
}

export async function recordPageVisit({ hasAnalyticsConsent, isOwner = () => null } = {}) {
  function permitted() {
    if (hasAnalyticsConsent?.() !== true || !window.isSecureContext || document.visibilityState !== 'visible' ||
        navigator.webdriver || navigator.globalPrivacyControl === true || navigator.doNotTrack === '1') return false;
    const owner = isOwner();
    return owner === false || owner === null;
  }
  try {
    if (!permitted() || !navigator.locks) return;
    await navigator.locks.request(key, async () => {
      if (!permitted()) return;
      const day = new Intl.DateTimeFormat('sv-SE', { timeZone:'Europe/Istanbul' }).format(new Date());
      const previous = JSON.parse(localStorage.getItem(key) || 'null');
      if (previous?.day === day && previous.sent === true) return;
      const id = previous?.day === day && typeof previous.id === 'string' ? previous.id : crypto.randomUUID();
      localStorage.setItem(key, JSON.stringify({day, id}));
      const response = await fetch('/.well-known/site-visits/page', { method:'POST', mode:'same-origin', credentials:'omit',
        redirect:'error', referrer:'', referrerPolicy:'origin', cache:'no-store', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({ day, id }) });
      if (!permitted()) return;
      if (response.status === 204) localStorage.setItem(key, JSON.stringify({day,sent:true}));
      else if (response.status === 404) clearVisitIdentifier();
    });
  } catch { /* Measurement must not interrupt navigation. */ }
}
