/* ══════════════════════════════════════════════════════
   JobMatch AI — Google SSO Authentication
   ══════════════════════════════════════════════════════ */

const AUTH = {
  TOKEN_KEY: 'jobmatch_jwt',
  USER_KEY: 'jobmatch_user',

  getToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  getUser() {
    try {
      return JSON.parse(localStorage.getItem(this.USER_KEY) || 'null');
    } catch {
      return null;
    }
  },

  saveSession(token, user) {
    localStorage.setItem(this.TOKEN_KEY, token);
    localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  },

  clearSession() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
  },

  decodeJwtPayload(token) {
    const payloadSegment = token.split('.')[1] || '';
    const normalized = payloadSegment.replace(/-/g, '+').replace(/_/g, '/');
    const padding = normalized.length % 4;
    const base64 = normalized + (padding ? '='.repeat(4 - padding) : '');
    return JSON.parse(atob(base64));
  },

  isAuthenticated() {
    const token = this.getToken();
    if (!token) return false;
    // Check expiry from JWT payload (no signature verification — server does that)
    try {
      const payload = this.decodeJwtPayload(token);
      return payload.exp * 1000 > Date.now();
    } catch {
      return false;
    }
  },

  // Returns headers object with Authorization if token present
  headers(extra = {}) {
    const token = this.getToken();
    const h = { 'Content-Type': 'application/json', ...extra };
    if (token) h['Authorization'] = `Bearer ${token}`;
    if (CONFIG.API_KEY) h['X-Api-Key'] = CONFIG.API_KEY;
    return h;
  },

  // Called by Google Identity Services after user picks account
  async handleGoogleCredential(response) {
    try {
      const res = await fetch(CONFIG.API_BASE_URL + '/auth/google', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(CONFIG.API_KEY ? { 'X-Api-Key': CONFIG.API_KEY } : {}) },
        body: JSON.stringify({ credential: response.credential }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Auth failed (${res.status})`);
      }

      const data = await res.json();
      const user = data.user || {};
      AUTH.saveSession(data.access_token, user);
      AUTH.onSignIn(user);
    } catch (err) {
      console.error('Google auth error:', err);
      alert('Sign-in failed: ' + err.message);
    }
  },

  onSignIn(user) {
    // Hide gate, show app
    document.getElementById('auth-gate').classList.add('hidden');

    // Update header
    const pic = user.picture || '';
    const name = user.name || user.email || '';
    const headerPic = document.getElementById('headerUserPic');
    const headerName = document.getElementById('auth-header-name');
    const signOutBtn = document.getElementById('signOutHeaderBtn');

    if (pic) { headerPic.src = pic; headerPic.style.display = 'block'; }
    if (name) { headerName.textContent = name; headerName.style.display = 'block'; }
    if (signOutBtn) signOutBtn.style.display = 'inline-block';

    // Pre-fill email/name in form if fields are empty
    const emailField = document.getElementById('email');
    const nameField = document.getElementById('fullName');
    if (emailField && !emailField.value && user.email) emailField.value = user.email;
    if (nameField && !nameField.value && user.name) nameField.value = user.name;
  },

  signOut() {
    AUTH.clearSession();
    // Revoke Google session
    if (window.google && google.accounts && google.accounts.id) {
      google.accounts.id.disableAutoSelect();
    }
    location.reload();
  },

  init() {
    // If Google Client ID not configured — skip auth gate entirely
    if (!CONFIG.GOOGLE_CLIENT_ID) {
      document.getElementById('auth-gate').classList.add('hidden');
      return;
    }

    // Already signed in
    if (AUTH.isAuthenticated()) {
      const user = AUTH.getUser();
      if (user) { AUTH.onSignIn(user); return; }
    }

    // Show gate, initialize Google Sign-In
    window.addEventListener('load', () => {
      if (!window.google) {
        // GSI script not yet loaded — wait
        const script = document.querySelector('script[src*="accounts.google.com/gsi/client"]');
        if (script) script.addEventListener('load', AUTH._initGSI.bind(AUTH));
      } else {
        AUTH._initGSI();
      }
    });

    // Sign-out buttons
    document.getElementById('authSignOutBtn')?.addEventListener('click', AUTH.signOut);
    document.getElementById('signOutHeaderBtn')?.addEventListener('click', AUTH.signOut);
  },

  _initGSI() {
    google.accounts.id.initialize({
      client_id: CONFIG.GOOGLE_CLIENT_ID,
      callback: AUTH.handleGoogleCredential.bind(AUTH),
      auto_select: false,
      cancel_on_tap_outside: false,
    });

    google.accounts.id.renderButton(
      document.getElementById('google-signin-btn'),
      {
        theme: 'outline',
        size: 'large',
        width: 320,
        text: 'signin_with',
        shape: 'rectangular',
        logo_alignment: 'left',
      }
    );

    // Also show One Tap prompt
    google.accounts.id.prompt();
  },
};

// Bootstrap auth on DOM ready
document.addEventListener('DOMContentLoaded', () => AUTH.init());
