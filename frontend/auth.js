/*
   JobMatch AI - Authentication and view flow
*/

const AUTH = {
  TOKEN_KEY: 'jobmatch_jwt',
  USER_KEY: 'jobmatch_user',
  _gsiInitialized: false,

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

    if (token.startsWith('local_')) {
      return !!this.getUser();
    }

    try {
      const payload = this.decodeJwtPayload(token);
      return payload.exp * 1000 > Date.now();
    } catch {
      return false;
    }
  },

  headers(extra = {}) {
    const token = this.getToken();
    const h = { 'Content-Type': 'application/json', ...extra };
    if (token && !token.startsWith('local_')) h.Authorization = `Bearer ${token}`;
    if (CONFIG.API_KEY) h['X-Api-Key'] = CONFIG.API_KEY;
    return h;
  },

  showMarketing() {
    this.showAuthGate();
  },

  showApp() {
    document.getElementById('app-shell')?.classList.remove('hidden');
    document.getElementById('auth-gate')?.classList.add('hidden');
  },

  showAuthGate() {
    document.getElementById('auth-gate')?.classList.remove('hidden');

    const fallback = document.getElementById('fallbackSignIn');
    if (!CONFIG.GOOGLE_CLIENT_ID && fallback) {
      fallback.classList.remove('hidden');
    }

    if (CONFIG.GOOGLE_CLIENT_ID) {
      this.ensureGSIInitialized();
    }
  },

  ensureGSIInitialized() {
    if (!window.google || !google.accounts || !google.accounts.id) return;

    if (!this._gsiInitialized) {
      google.accounts.id.initialize({
        client_id: CONFIG.GOOGLE_CLIENT_ID,
        callback: this.handleGoogleCredential.bind(this),
        auto_select: false,
        cancel_on_tap_outside: false,
      });
      this._gsiInitialized = true;
    }

    const btnHost = document.getElementById('google-signin-btn');
    if (btnHost && !btnHost.hasChildNodes()) {
      google.accounts.id.renderButton(btnHost, {
        theme: 'outline',
        size: 'large',
        width: 320,
        text: 'signin_with',
        shape: 'rectangular',
        logo_alignment: 'left',
      });
    }
  },

  async handleGoogleCredential(response) {
    try {
      const res = await fetch(CONFIG.API_BASE_URL + '/auth/google', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(CONFIG.API_KEY ? { 'X-Api-Key': CONFIG.API_KEY } : {}),
        },
        body: JSON.stringify({ credential: response.credential }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `Auth failed (${res.status})`);
      }

      const data = await res.json();
      const user = data.user || {};
      this.saveSession(data.access_token, user);
      this.onSignIn(user);
    } catch (err) {
      console.error('Google auth error:', err);
      alert('Sign-in failed: ' + err.message);
    }
  },

  handleLocalFallbackSignIn() {
    const name = document.getElementById('fallbackName')?.value.trim() || 'Guest User';
    const email = document.getElementById('fallbackEmail')?.value.trim() || 'guest@example.com';
    const token = `local_${Date.now()}`;
    this.saveSession(token, { name, email, picture: '' });
    this.onSignIn({ name, email, picture: '' });
  },

  onSignIn(user) {
    this.showApp();

    const pic = user.picture || '';
    const name = user.name || user.email || '';
    const headerPic = document.getElementById('headerUserPic');
    const headerName = document.getElementById('auth-header-name');
    const signOutBtn = document.getElementById('signOutHeaderBtn');

    if (headerPic) {
      if (pic) {
        headerPic.src = pic;
        headerPic.style.display = 'block';
      } else {
        headerPic.style.display = 'none';
      }
    }

    if (headerName) {
      if (name) {
        headerName.textContent = name;
        headerName.style.display = 'block';
      } else {
        headerName.style.display = 'none';
      }
    }

    if (signOutBtn) signOutBtn.style.display = 'inline-block';

    const emailField = document.getElementById('email');
    const nameField = document.getElementById('fullName');
    if (emailField && !emailField.value && user.email) emailField.value = user.email;
    if (nameField && !nameField.value && user.name) nameField.value = user.name;
  },

  signOut() {
    this.clearSession();
    if (window.google && google.accounts && google.accounts.id) {
      google.accounts.id.disableAutoSelect();
    }
    this.showMarketing();
  },

  init() {
    document.getElementById('authSignOutBtn')?.addEventListener('click', this.signOut.bind(this));
    document.getElementById('signOutHeaderBtn')?.addEventListener('click', this.signOut.bind(this));
    document.getElementById('fallbackSignInBtn')?.addEventListener('click', this.handleLocalFallbackSignIn.bind(this));

    if (this.isAuthenticated()) {
      const user = this.getUser();
      this.onSignIn(user || {});
    } else {
      this.showMarketing();
    }

    window.startSignInFlow = () => {
      this.showAuthGate();
      if (CONFIG.GOOGLE_CLIENT_ID) {
        if (window.google) {
          this.ensureGSIInitialized();
        } else {
          const script = document.querySelector('script[src*="accounts.google.com/gsi/client"]');
          script?.addEventListener('load', () => this.ensureGSIInitialized(), { once: true });
        }
      }
    };
  },
};

document.addEventListener('DOMContentLoaded', () => AUTH.init());
