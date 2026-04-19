/* ══════════════════════════════════════════════════════
   JobMatch AI — Dashboard Logic
   ══════════════════════════════════════════════════════ */

// CONFIG is loaded from config.js

// No auth required for localhost
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
    localStorage.setItem(this.USER_KEY, JSON.stringify(user || {}));
  },

  clearSession() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
  },

  decodeJwtPayload(token) {
    const payloadSegment = (token || '').split('.')[1] || '';
    const normalized = payloadSegment.replace(/-/g, '+').replace(/_/g, '/');
    const padding = normalized.length % 4;
    const base64 = normalized + (padding ? '='.repeat(4 - padding) : '');
    return JSON.parse(atob(base64));
  },

  isAuthenticated() {
    const token = this.getToken();
    if (!token) return false;
    try {
      const payload = this.decodeJwtPayload(token);
      return !!payload.exp && payload.exp * 1000 > Date.now();
    } catch {
      return false;
    }
  },

  headers(extra = {}) {
    const h = { 'Content-Type': 'application/json', ...extra };
    const token = this.getToken();
    if (token) h.Authorization = `Bearer ${token}`;
    if (CONFIG.API_KEY) h['X-Api-Key'] = CONFIG.API_KEY;
    return h;
  },
};

function authHeaders(extra = {}) {
  return AUTH.headers(extra);
}

function setAuthStatus(msg) {
  const el = document.getElementById('auth-status');
  if (el) el.textContent = msg || '';
}

function setLandingHidden(isHidden) {
  document.querySelectorAll('[data-landing]').forEach((section) => {
    section.classList.toggle('landing-hidden', !!isHidden);
  });
}

function setAuthGateVisible(isVisible) {
  const gate = document.getElementById('auth-gate');
  if (!gate) return;
  gate.classList.toggle('hidden', !isVisible);
  document.body.classList.toggle('auth-open', !!isVisible);
}

function revealAuthGate({ scroll = true } = {}) {
  setAuthGateVisible(true);
}

function showAppAfterAuth(user) {
  setLandingHidden(true);
  setAuthGateVisible(false);
  document.getElementById('app-shell')?.classList.remove('hidden');
  updateHeaderAccount(user);

  const emailField = document.getElementById('email');
  const nameField = document.getElementById('fullName');
  if (emailField && !emailField.value && user?.email) emailField.value = user.email;
  if (nameField && !nameField.value && user?.name) nameField.value = user.name;
}

function updateHeaderAccount(user) {
  const chip = document.getElementById('accountChip');
  const avatar = document.getElementById('accountAvatar');
  const nameEl = document.getElementById('accountName');
  const emailEl = document.getElementById('accountEmail');

  if (!chip || !avatar || !nameEl || !emailEl) return;

  const name = (user?.name || user?.email || 'Signed in').trim();
  const email = (user?.email || '').trim();
  const initials = (name || 'U')
    .split(/\s+|@/)
    .filter(Boolean)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase() || 'U';

  avatar.textContent = initials;
  nameEl.textContent = name;
  emailEl.textContent = email;
  chip.classList.remove('hidden');
}

function signOut() {
  AUTH.clearSession();
  setLandingHidden(false);
  document.getElementById('app-shell')?.classList.add('hidden');
  setAuthGateVisible(false);
  document.getElementById('accountChip')?.classList.add('hidden');
  AppState.bookmarks = [];
  AppState.applications = [];
  updateApplicationsBadge();
  setAuthStatus('Signed out. Please sign in with Google to continue.');
}

function handleAuthFailure(message = 'Your session expired. Please sign in again.') {
  signOut();
  setAuthStatus(message);
  revealAuthGate({ scroll: false });
}

async function resolveGoogleClientId() {
  if (CONFIG.GOOGLE_CLIENT_ID) return CONFIG.GOOGLE_CLIENT_ID;
  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/auth/config', {
      method: 'GET',
      headers: AUTH.headers(),
    });
    if (!res.ok) return '';
    const data = await res.json();
    return (data.googleClientId || '').trim();
  } catch {
    return '';
  }
}

async function handleGoogleCredential(credentialResponse) {
  setAuthStatus('Signing you in...');
  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/auth/google', {
      method: 'POST',
      headers: AUTH.headers(),
      body: JSON.stringify({ credential: credentialResponse.credential }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Sign-in failed (${res.status})`);
    }

    const data = await res.json();
    AUTH.saveSession(data.access_token, data.user || {});
    showAppAfterAuth(data.user || {});
    await loadUserData();
    setAuthStatus('');
  } catch (err) {
    setAuthStatus(err.message || 'Google sign-in failed');
  }
}

async function initGoogleGate() {
  if (AUTH.isAuthenticated()) {
    showAppAfterAuth(AUTH.getUser());
    await loadUserData();
    return;
  }

  setLandingHidden(false);
  setAuthGateVisible(false);
  document.getElementById('app-shell')?.classList.add('hidden');

  const clientId = await resolveGoogleClientId();
  if (!clientId) {
    setAuthStatus('Google SSO is not configured. Please set GOOGLE_CLIENT_ID.');
    return;
  }

  const renderButton = () => {
    if (!window.google || !window.google.accounts || !window.google.accounts.id) {
      setAuthStatus('Loading Google Sign-In...');
      return;
    }
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: handleGoogleCredential,
      auto_select: false,
      cancel_on_tap_outside: false,
    });
    const host = document.getElementById('google-signin-btn');
    if (host) {
      host.innerHTML = '';
      window.google.accounts.id.renderButton(host, {
        theme: 'outline',
        size: 'large',
        width: 320,
        text: 'signin_with',
        shape: 'rectangular',
      });
      setAuthStatus('');
    }
  };

  renderButton();
  const gsiScript = document.querySelector('script[src*="accounts.google.com/gsi/client"]');
  gsiScript?.addEventListener('load', renderButton, { once: true });
}

document.querySelectorAll('.js-auth-trigger, .landing-nav-cta').forEach((trigger) => {
  trigger.addEventListener('click', (event) => {
    event.preventDefault();
    revealAuthGate();
  });
});

document.getElementById('authCloseBtn')?.addEventListener('click', () => {
  setAuthGateVisible(false);
});

document.getElementById('auth-gate')?.addEventListener('click', (event) => {
  if (event.target && event.target.id === 'auth-gate') {
    setAuthGateVisible(false);
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    setAuthGateVisible(false);
  }
});

document.getElementById('signOutBtn')?.addEventListener('click', signOut);

// ─── SESSION ID ───────────────────────────────────────
const SESSION_ID_KEY = 'jobmatch_session';
let currentSessionId = localStorage.getItem(SESSION_ID_KEY) || localStorage.getItem('jobmatch_session_id');
if (!currentSessionId) {
  currentSessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}
localStorage.setItem(SESSION_ID_KEY, currentSessionId);

// ─── RESUME STATE ─────────────────────────────────────
let lastResumeText = '';
let lastResumeFile = null;
let currentCoverLetterContext = null;

const APP_TABS = ['all', 'saved', 'applied', 'interviewing', 'offered', 'rejected'];
let activeApplicationsTab = 'all';

function normalizeJobField(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

function sameJob(aTitle, aCompany, bTitle, bCompany) {
  return normalizeJobField(aTitle) === normalizeJobField(bTitle)
    && normalizeJobField(aCompany) === normalizeJobField(bCompany);
}

const AppState = {
  bookmarks: [],
  applications: [],
  isBookmarked(jobTitle, company) {
    return this.bookmarks.some((b) => sameJob(b.job_title, b.company, jobTitle, company));
  },
  getApplication(jobTitle, company) {
    return this.applications.find((a) => sameJob(a.job_title, a.company, jobTitle, company));
  },
};

// ─── DOM ELEMENTS ────────────────────────────────────
const form = document.getElementById('profile-form');
const submitBtn = document.getElementById('submitBtn');
const clearBtn = document.getElementById('clearBtn');
const emailResultsBtn = document.getElementById('emailResultsBtn');
const debugRetrievalBtn = document.getElementById('debugRetrievalBtn');

const emptyState = document.getElementById('empty-state');
const loadingState = document.getElementById('loading-state');
const errorState = document.getElementById('error-state');
const errorMessage = document.getElementById('error-message');
const resultsContainer = document.getElementById('results-container');
const resultsContent = document.getElementById('results-content');
const skillsList = document.getElementById('skillsList');
const skillsTagContainer = document.getElementById('skillsTagContainer');
const skillsInput = document.getElementById('skillsInput');
const skillsHidden = document.getElementById('skills');

const applicationStatusByKey = new Map();
let emailServiceReady = null;
let emailServiceIssue = '';

function updateApplicationsBadge() {
  const badge = document.getElementById('applicationsBadge');
  if (!badge) return;
  const savedCount = AppState.applications.filter((a) => (a.status || 'saved') === 'saved').length;
  badge.textContent = String(savedCount);
  badge.classList.toggle('hidden', savedCount === 0);
}

function normalizeStatus(status) {
  const raw = (status || 'saved').toLowerCase().trim();
  if (raw === 'offer') return 'offered';
  if (raw === 'interview') return 'interviewing';
  if (raw === 'oa') return 'applied';
  return raw;
}

async function loadUserData() {
  if (!AUTH.isAuthenticated()) return;
  const headers = authHeaders();

  const [bookmarksRes, applicationsRes] = await Promise.all([
    fetch(`${CONFIG.API_BASE_URL}/bookmarks/me`, { headers }),
    fetch(`${CONFIG.API_BASE_URL}/applications/me`, { headers }),
  ]);

  if (bookmarksRes.status === 401 || applicationsRes.status === 401) {
    handleAuthFailure('Session expired. Please sign in again to view your saved jobs.');
    return;
  }

  const bookmarksPayload = bookmarksRes.ok ? await bookmarksRes.json() : { bookmarks: [] };
  const applicationsPayload = applicationsRes.ok ? await applicationsRes.json() : { applications: [] };

  AppState.bookmarks = Array.isArray(bookmarksPayload.bookmarks) ? bookmarksPayload.bookmarks : [];
  AppState.applications = Array.isArray(applicationsPayload.applications)
    ? applicationsPayload.applications.map((a) => ({ ...a, status: normalizeStatus(a.status) }))
    : [];

  applicationStatusByKey.clear();
  AppState.applications.forEach((a) => {
    applicationStatusByKey.set(appKey(a.job_title, a.company), {
      id: a.id,
      status: normalizeStatus(a.status),
      notes: a.notes || '',
    });
  });

  updateApplicationsBadge();
}

function showToast(message) {
  const host = document.getElementById('toastHost');
  if (!host) return;
  const toast = document.createElement('div');
  toast.className = 'app-toast';
  toast.textContent = message;
  host.appendChild(toast);
  setTimeout(() => toast.classList.add('visible'), 10);
  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 220);
  }, 3000);
}

initGoogleGate();

function looksLikeEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((value || '').trim());
}

function readListTexts(selector, root = document) {
  return Array.from(root.querySelectorAll(selector))
    .map((el) => (el.textContent || '').trim())
    .filter(Boolean);
}

function buildResultsEmailMarkdown() {
  const timestamp = new Date().toLocaleString();
  const lines = [];
  const nameVal = document.getElementById('fullName')?.value?.trim();
  const roleVal = document.getElementById('desiredRole')?.value?.trim();

  lines.push('# JobMatch AI Results');
  lines.push(`Generated: ${timestamp}`);
  if (nameVal) lines.push(`Candidate: ${nameVal}`);
  if (roleVal) lines.push(`Target Role: ${roleVal}`);
  lines.push('');

  const cards = Array.from(document.querySelectorAll('.job-card'));
  if (cards.length > 0) {
    lines.push('## Top Matches');
    lines.push('');
    cards.forEach((card, idx) => {
      const title = card.querySelector('.job-title')?.textContent?.trim() || 'Unknown role';
      const company = card.querySelector('.job-company')?.textContent?.trim() || '';
      const score = card.querySelector('.score-num')?.textContent?.trim() || '';
      const meta = readListTexts('.job-meta .meta-chip', card);
      const reasons = readListTexts('.reasons-section .job-list li', card);
      const gaps = readListTexts('.gaps-section .job-list li', card);
      const actions = readListTexts('.actions-section .action-list li', card);

      lines.push(`### ${idx + 1}. ${title}${company ? ` @ ${company}` : ''}`);
      if (score) lines.push(`- Match Score: ${score}/10`);
      if (meta[0]) lines.push(`- Location: ${meta[0]}`);
      if (meta[1]) lines.push(`- Salary: ${meta[1]}`);
      if (reasons.length) {
        lines.push('');
        lines.push('**Why it matches**');
        reasons.forEach((item) => lines.push(`- ${item}`));
      }
      if (gaps.length) {
        lines.push('');
        lines.push('**Gaps**');
        gaps.forEach((item) => lines.push(`- ${item}`));
      }
      if (actions.length) {
        lines.push('');
        lines.push('**Recommended next steps**');
        actions.forEach((item, actionIdx) => lines.push(`${actionIdx + 1}. ${item}`));
      }
      lines.push('');
    });
  }

  const globalActions = readListTexts('.global-actions-card .global-action-step .step-text');
  if (globalActions.length) {
    lines.push('## Overall Recommended Next Steps');
    globalActions.forEach((item, idx) => lines.push(`${idx + 1}. ${item}`));
    lines.push('');
  }

  const rendered = lines.join('\n').trim();
  return rendered || (resultsContent.innerText || resultsContent.textContent || '').trim();
}

async function checkEmailServiceStatus() {
  if (!AUTH.isAuthenticated()) {
    emailServiceReady = false;
    emailServiceIssue = 'Sign in to check email service status';
    if (emailResultsBtn) {
      emailResultsBtn.disabled = true;
      emailResultsBtn.title = emailServiceIssue;
    }
    return;
  }

  const headers = AUTH.headers();
  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/email/status', { method: 'GET', headers });
    if (res.status === 401) {
      handleAuthFailure('Session expired. Please sign in again.');
      return;
    }
    if (!res.ok) {
      emailServiceReady = false;
      emailServiceIssue = `Email status check failed (${res.status})`;
      if (emailResultsBtn) {
        emailResultsBtn.disabled = true;
        emailResultsBtn.title = emailServiceIssue;
      }
      return;
    }
    const data = await res.json();
    emailServiceReady = !!data.configured;
    emailServiceIssue = (data.missing || []).join(', ');
    if (emailResultsBtn) {
      emailResultsBtn.disabled = !emailServiceReady;
      emailResultsBtn.title = emailServiceReady ? '' : `Email unavailable: ${emailServiceIssue || 'configuration missing'}`;
    }
  } catch (err) {
    emailServiceReady = false;
    emailServiceIssue = err.message || 'Unknown email service error';
    if (emailResultsBtn) {
      emailResultsBtn.disabled = true;
      emailResultsBtn.title = `Email unavailable: ${emailServiceIssue}`;
    }
  }
}

// ─── DARK MODE TOGGLE ────────────────────────────────
const darkModeToggle = document.getElementById('darkModeToggle');
if (localStorage.getItem('jobmatch_dark') === '1') {
  document.documentElement.setAttribute('data-theme', 'dark');
}
darkModeToggle?.addEventListener('click', () => {
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  document.documentElement.setAttribute('data-theme', isDark ? 'light' : 'dark');
  localStorage.setItem('jobmatch_dark', isDark ? '0' : '1');
});

// ─── INITIALIZE DATALISTS ───────────────────────────
// Populate job titles datalist
const jobTitleList = document.getElementById('jobTitleList');
if (jobTitleList && typeof JOB_TITLES !== 'undefined') {
  JOB_TITLES.forEach(title => {
    const option = document.createElement('option');
    option.value = title;
    jobTitleList.appendChild(option);
  });
}

// skillTags array — populated from resume parse, not from UI
const skillTags = [];

function updateHiddenSkillsField() {
  if (skillsHidden) {
    skillsHidden.value = skillTags.join(', ');
  }
}

function renderSkillTags() {
  if (!skillsTagContainer || !skillsInput) return;
  skillsTagContainer.querySelectorAll('.skill-tag').forEach((el) => el.remove());
  skillTags.forEach((skill, index) => {
    const tag = document.createElement('div');
    tag.className = 'skill-tag';

    const textNode = document.createElement('span');
    textNode.textContent = skill;
    tag.appendChild(textNode);

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'skill-tag-remove';
    removeBtn.textContent = '×';
    removeBtn.setAttribute('aria-label', `Remove ${skill}`);
    removeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      skillTags.splice(index, 1);
      renderSkillTags();
      updateHiddenSkillsField();
    });
    tag.appendChild(removeBtn);

    skillsTagContainer.insertBefore(tag, skillsInput);
  });
}

function addSkillTag(skillName) {
  const trimmed = (skillName || '').trim();
  if (!trimmed) return;
  const exists = skillTags.some((s) => s.toLowerCase() === trimmed.toLowerCase());
  if (exists) return;
  skillTags.push(trimmed);
  renderSkillTags();
  updateHiddenSkillsField();
}

function setSkillTags(skills) {
  skillTags.length = 0;
  (skills || []).forEach((skill) => {
    const trimmed = (skill || '').trim();
    if (!trimmed) return;
    const exists = skillTags.some((s) => s.toLowerCase() === trimmed.toLowerCase());
    if (!exists) skillTags.push(trimmed);
  });
  renderSkillTags();
  updateHiddenSkillsField();
}

if (skillsList && typeof COMMON_SKILLS !== 'undefined') {
  COMMON_SKILLS.forEach((skill) => {
    const option = document.createElement('option');
    option.value = skill;
    skillsList.appendChild(option);
  });
}

if (skillsInput) {
  skillsInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addSkillTag(skillsInput.value);
      skillsInput.value = '';
      return;
    }
    if (e.key === 'Backspace' && !skillsInput.value.trim() && skillTags.length > 0) {
      skillTags.pop();
      renderSkillTags();
      updateHiddenSkillsField();
    }
  });

  skillsInput.addEventListener('blur', () => {
    const val = skillsInput.value.trim();
    if (!val) return;
    val.split(',').forEach((part) => addSkillTag(part));
    skillsInput.value = '';
  });
}

if (skillsTagContainer && skillsInput) {
  skillsTagContainer.addEventListener('click', () => skillsInput.focus());
}


// ─── FETCH WITH RETRY ───────────────────────────────
async function fetchWithRetry(url, options, retries = 2) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fetch(url, options);
    } catch (err) {
      if (attempt === retries) throw err;
      await new Promise(r => setTimeout(r, 1500 * Math.pow(2, attempt)));
    }
  }
}


// ─── SEND TO BACKEND ────────────────────────────────
async function sendToBackend(profile) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60000);

  const headers = AUTH.headers();

  let res;
  try {
    res = await fetchWithRetry(CONFIG.API_BASE_URL + '/webhook', {
      method: 'POST',
      headers,
      body: JSON.stringify({ profile, sessionId: currentSessionId }),
      signal: controller.signal,
    });
  } catch (networkErr) {
    if (networkErr.name === 'AbortError') {
      throw new Error('Request timed out — please try again');
    }
    throw new Error('Cannot reach the backend. Make sure you ran: uvicorn backend:app --port 8000');
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = '';
    try { detail = JSON.parse(text).detail || text; } catch { detail = text; }
    if (res.status === 401) throw new Error('API key invalid or missing');
    if (res.status === 429) throw new Error('Too many requests — please wait a moment and try again');
    if (res.status === 500 && detail.includes('API_KEY')) throw new Error('API key missing or invalid. Check your .env file.');
    throw new Error(`Backend error (${res.status}): ${detail}`);
  }

  const data = await res.json();
  if (typeof data === 'string') return data;
  if (data.output) return data.output;
  if (data.text) return data.text;
  if (data.response) return data.response;
  return JSON.stringify(data, null, 2);
}


// ─── BUILD PROMPT (legacy, kept for compat) ──────────
function buildPrompt(p) {
  let prompt = `I'm looking for job recommendations. Here is my profile:\n\n`;

  prompt += `Name: ${p.name}\n`;

  if (p.desiredRole) prompt += `Desired Role: ${p.desiredRole}\n`;
  if (p.experience) prompt += `Years of Experience: ${p.experience}\n`;
  if (p.skills) prompt += `Key Skills: ${p.skills}\n`;
  if (p.education) prompt += `Education: ${p.education}\n`;
  if (p.industry) prompt += `Preferred Industry: ${p.industry}\n`;
  if (p.location) prompt += `Preferred Location: ${p.location}\n`;
  if (p.workType && p.workType !== 'Any') prompt += `Work Type Preference: ${p.workType}\n`;

  if (p.salaryMin) {
    prompt += `Minimum Salary: $${Number(p.salaryMin).toLocaleString()} per year\n`;
  }

  if (p.companySize && p.companySize !== 'Any') {
    prompt += `Company Size Preference: ${p.companySize}\n`;
  }

  if (p.benefits && p.benefits.length > 0) {
    prompt += `Benefits Priorities: ${p.benefits.join(', ')}\n`;
  }

  if (p.workAuth && p.workAuth !== 'Not Specified') {
    prompt += `Work Authorization Status: ${p.workAuth}\n`;
  }

  if (p.additional) prompt += `\nAdditional Preferences:\n${p.additional}\n`;

  prompt += `\nPlease find the best matching jobs for my profile from the available postings.`;

  return prompt;
}

function getCurrentProfileFromForm() {
  return {
    name: document.getElementById('fullName').value.trim(),
    email: document.getElementById('email').value.trim(),
    desiredRole: document.getElementById('desiredRole').value.trim(),
    experience: parseInt(document.getElementById('experience').value, 10) || 0,
    skills: skillTags.slice(),
    education: document.getElementById('education').value.trim(),
    industry: document.getElementById('industry').value.trim(),
    location: document.getElementById('location').value.trim(),
    workType: document.getElementById('workType').value,
    salaryMin: document.getElementById('salaryMin').value ? parseInt(document.getElementById('salaryMin').value, 10) : null,
    companySize: document.getElementById('companySize').value.trim() || 'Any',
    benefits: [],
    workAuth: document.getElementById('workAuth').value.trim() || 'Not Specified',
    additional: document.getElementById('additional').value.trim(),
  };
}


// ─── FORM SUBMISSION ────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();

  // Collect all form values
  const profile = getCurrentProfileFromForm();

  if (!lastResumeText && profile.skills.length === 0 && !profile.desiredRole) {
    showError('Please upload your resume before searching.');
    return;
  }

  // Switch UI states
  showState('loading');
  submitBtn.disabled = true;
  if (emailResultsBtn) emailResultsBtn.style.display = 'none';
  if (debugRetrievalBtn) debugRetrievalBtn.style.display = 'none';

  try {
    const response = await sendToBackend(profile);
    await displayResults(response);
  } catch (err) {
    showError(err.message || 'An unexpected error occurred.');
  } finally {
    submitBtn.disabled = false;
  }
});


// ─── CLEAR RESULTS ──────────────────────────────────
clearBtn.addEventListener('click', () => {
  showState('empty');
  resultsContent.innerHTML = '';
  if (emailResultsBtn) emailResultsBtn.style.display = 'none';
  if (debugRetrievalBtn) debugRetrievalBtn.style.display = 'none';
});


// ─── EMAIL MY RESULTS ────────────────────────────────
if (emailResultsBtn) {
  emailResultsBtn.addEventListener('click', async () => {
    const emailVal = document.getElementById('email').value.trim();
    const nameVal = document.getElementById('fullName').value.trim();
    if (emailServiceReady === false) {
      alert(`Email service is not ready. Missing: ${emailServiceIssue || 'configuration'}`);
      return;
    }
    if (!emailVal) {
      alert('Please enter your email address in the form before sending results.');
      return;
    }
    if (!looksLikeEmail(emailVal)) {
      alert('Please enter a valid email address.');
      return;
    }
    const resultsMarkdown = buildResultsEmailMarkdown();
    if (!resultsMarkdown.trim()) {
      alert('No results available to send yet.');
      return;
    }
    const headers = AUTH.headers();
    try {
      emailResultsBtn.disabled = true;
      emailResultsBtn.textContent = 'Sending...';
      const res = await fetch(CONFIG.API_BASE_URL + '/send-results', {
        method: 'POST',
        headers,
        body: JSON.stringify({ email: emailVal, name: nameVal || 'there', results_markdown: resultsMarkdown }),
      });
      if (res.ok) {
        emailResultsBtn.textContent = 'Sent!';
        setTimeout(() => { emailResultsBtn.textContent = 'Email My Results'; emailResultsBtn.disabled = false; }, 3000);
      } else {
        const d = await res.json().catch(() => ({}));
        alert('Failed to send email: ' + (d.detail || res.status));
        emailResultsBtn.textContent = 'Email My Results';
        emailResultsBtn.disabled = false;
      }
    } catch (err) {
      alert('Could not reach email service: ' + err.message);
      emailResultsBtn.textContent = 'Email My Results';
      emailResultsBtn.disabled = false;
    }
  });
}

checkEmailServiceStatus();


// ─── RESUME UPLOAD ───────────────────────────────────
const resumeDropzone = document.getElementById('resume-dropzone');
const resumeFileInput = document.getElementById('resumeFile');
const resumeStatus = document.getElementById('resumeStatus');

async function handleResumeUpload(file) {
  if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
    resumeStatus.textContent = 'Only PDF files accepted.';
    resumeStatus.className = 'resume-status error';
    return;
  }
  resumeStatus.textContent = 'Parsing resume...';
  resumeStatus.className = 'resume-status loading';

  const formData = new FormData();
  formData.append('file', file);
  const headers = AUTH.headers({ 'Content-Type': undefined });
  delete headers['Content-Type']; // let browser set multipart boundary

  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/parse-resume', {
      method: 'POST',
      headers,
      body: formData,
    });
    if (res.status === 401) {
      handleAuthFailure('Session expired. Please sign in again before uploading your resume.');
      throw new Error('Session expired. Please sign in again.');
    }
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const data = await res.json();

    // Auto-populate hidden fields from parsed resume
    if (data.name) document.getElementById('fullName').value = data.name;
    if (data.email) document.getElementById('email').value = data.email;
    if (data.experience_years) {
      const expVal = Math.min(Math.max(parseInt(data.experience_years, 10) || 0, 0), 30);
      document.getElementById('experience').value = expVal;
    }
    if (data.education) document.getElementById('education').value = data.education;
    if (data.industries && data.industries.length > 0) {
      document.getElementById('industry').value = data.industries[0];
    }
    if (data.skills && data.skills.length > 0) {
      setSkillTags(data.skills.slice(0, 20));
    }
    // Pre-fill desired role only if the user hasn't typed one
    if (data.recent_role && !document.getElementById('desiredRole').value) {
      document.getElementById('desiredRole').value = data.recent_role;
    }

    resumeStatus.textContent = 'Resume parsed! Skills and experience extracted.';
    resumeStatus.className = 'resume-status success';
    // Store file for enhancement feature
    lastResumeFile = file;
    if (data.raw_text || data.resume_text) lastResumeText = data.raw_text || data.resume_text;
    const enhancePanel = document.getElementById('resume-enhance-panel');
    if (enhancePanel) enhancePanel.classList.remove('hidden');
  } catch (err) {
    resumeStatus.textContent = 'Parse failed: ' + err.message;
    resumeStatus.className = 'resume-status error';
  }
}

if (resumeFileInput) {
  resumeFileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      handleResumeUpload(e.target.files[0]);
    }
  });
}

if (resumeDropzone) {
  resumeDropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    resumeDropzone.classList.add('drag-over');
  });
  resumeDropzone.addEventListener('dragleave', () => {
    resumeDropzone.classList.remove('drag-over');
  });
  resumeDropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    resumeDropzone.classList.remove('drag-over');
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) handleResumeUpload(file);
  });
  resumeDropzone.addEventListener('click', (e) => {
    // Don't trigger if clicking the label (it triggers the file input itself)
    if (e.target.tagName === 'LABEL' || e.target.tagName === 'INPUT') return;
    resumeFileInput.click();
  });
}


// ─── BOOKMARK FUNCTIONALITY ──────────────────────────
async function createBookmarkRecord(jobTitle, company, location, salary, matchScore, jobData = {}) {
  const headers = authHeaders();
  const res = await fetch(CONFIG.API_BASE_URL + '/bookmark', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      session_id: currentSessionId,
      job_title: jobTitle,
      company,
      location: location || '',
      salary: salary || '',
      match_score: Number(matchScore || 0),
      job_data: jobData,
    }),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Bookmark save failed (${res.status})`);
  }
}

async function checkApplication(jobTitle, company) {
  const params = new URLSearchParams({
    session_id: currentSessionId,
    job_title: jobTitle,
    company,
  });
  const res = await fetch(`${CONFIG.API_BASE_URL}/applications/check?${params.toString()}`, {
    headers: authHeaders(),
  });
  if (!res.ok) return { exists: false, application: null };
  const data = await res.json();
  if (!data.application) return data;
  return {
    exists: !!data.exists,
    application: { ...data.application, status: normalizeStatus(data.application.status) },
  };
}

async function deleteBookmarkById(bookmarkId) {
  const res = await fetch(`${CONFIG.API_BASE_URL}/bookmarks/${bookmarkId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 404) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Bookmark delete failed (${res.status})`);
  }
}

async function deleteApplicationById(applicationId) {
  const res = await fetch(`${CONFIG.API_BASE_URL}/applications/${applicationId}`, {
    method: 'DELETE',
    headers: authHeaders(),
  });
  if (!res.ok && res.status !== 404) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Application delete failed (${res.status})`);
  }
}

async function removeSavedJob(jobTitle, company) {
  const bookmark = AppState.bookmarks.find((b) => sameJob(b.job_title, b.company, jobTitle, company));
  const application = AppState.getApplication(jobTitle, company);

  if (bookmark?.id) {
    await deleteBookmarkById(bookmark.id);
  }
  if (application?.id) {
    await deleteApplicationById(application.id);
  }

  AppState.bookmarks = AppState.bookmarks.filter((b) => !sameJob(b.job_title, b.company, jobTitle, company));
  AppState.applications = AppState.applications.filter((a) => !sameJob(a.job_title, a.company, jobTitle, company));
  applicationStatusByKey.delete(appKey(jobTitle, company));
  updateApplicationsBadge();
}

async function toggleBookmark(jobInfo) {
  const {
    title,
    company,
    location,
    salary,
    score,
    description,
  } = jobInfo;

  if (!AppState.isBookmarked(title, company)) {
    await createBookmarkRecord(title, company, location, salary, score, {
      title,
      company,
      location,
      salary,
      match_score: score,
      description: description || '',
    });

    const check = await checkApplication(title, company);
    if (!check.exists) {
      await saveApplicationStatus(title, company, 'saved', '');
    } else if (check.application) {
      const existing = check.application;
      applicationStatusByKey.set(appKey(title, company), {
        id: existing.id,
        status: normalizeStatus(existing.status),
        notes: existing.notes || '',
      });
      const hasLocal = AppState.getApplication(title, company);
      if (!hasLocal) {
        AppState.applications.unshift({ ...existing, status: normalizeStatus(existing.status) });
      }
    }

    await loadUserData();
    showToast('Job saved!');
    return true;
  }

  const confirmed = window.confirm('Remove this job from saved jobs?');
  if (!confirmed) return true;

  await removeSavedJob(title, company);
  showToast('Removed from saved jobs');
  return false;
}


// ─── COVER LETTER MODAL ──────────────────────────────
const coverLetterModal = document.getElementById('coverLetterModal');
const coverLetterContent = document.getElementById('coverLetterContent');
const closeCoverLetter = document.getElementById('closeCoverLetter');
const closeCoverLetterBtn = document.getElementById('closeCoverLetterBtn');
const copyCoverLetter = document.getElementById('copyCoverLetter');
const jobDetailsModal = document.getElementById('jobDetailsModal');
const jobDetailsTitle = document.getElementById('jobDetailsTitle');
const jobDetailsRole = document.getElementById('jobDetailsRole');
const jobDetailsLocation = document.getElementById('jobDetailsLocation');
const jobDetailsSalary = document.getElementById('jobDetailsSalary');
const jobDetailsWhy = document.getElementById('jobDetailsWhy');
const jobDetailsDescription = document.getElementById('jobDetailsDescription');
const jobDetailsLink = document.getElementById('jobDetailsLink');
const closeJobDetails = document.getElementById('closeJobDetails');
const closeJobDetailsBtn = document.getElementById('closeJobDetailsBtn');
const openGmailDraftBtn = document.getElementById('openGmailDraftBtn');

function openCoverLetterModal(text, recruiterEmail) {
  if (coverLetterContent) coverLetterContent.textContent = text;
  const emailInput = document.getElementById('recruiterEmailInput');
  if (emailInput) emailInput.value = recruiterEmail || '';
  if (coverLetterModal) coverLetterModal.classList.remove('hidden');
}

function closeCoverLetterModal() {
  if (coverLetterModal) coverLetterModal.classList.add('hidden');
}

closeCoverLetter?.addEventListener('click', closeCoverLetterModal);
closeCoverLetterBtn?.addEventListener('click', closeCoverLetterModal);
coverLetterModal?.addEventListener('click', (e) => {
  if (e.target === coverLetterModal) closeCoverLetterModal();
});

copyCoverLetter?.addEventListener('click', () => {
  const text = coverLetterContent?.textContent || '';
  navigator.clipboard.writeText(text).then(() => {
    copyCoverLetter.textContent = 'Copied!';
    setTimeout(() => { copyCoverLetter.textContent = 'Copy to Clipboard'; }, 2000);
  });
});

function openJobDetailsModal(details) {
  if (jobDetailsTitle) {
    const companySuffix = details.company ? ` @ ${details.company}` : '';
    jobDetailsTitle.textContent = `${details.title || 'Job details'}${companySuffix}`;
  }
  if (jobDetailsRole) jobDetailsRole.textContent = details.role || 'Not specified';
  if (jobDetailsLocation) jobDetailsLocation.textContent = details.location || 'Not specified';
  if (jobDetailsSalary) jobDetailsSalary.textContent = details.salary || 'Not specified';
  if (jobDetailsWhy) {
    const reasons = (details.why || '')
      .split('|')
      .map((s) => s.trim())
      .filter(Boolean)
      .slice(0, 5);
    jobDetailsWhy.innerHTML = reasons.length
      ? `<ul>${reasons.map((r) => `<li>${esc(r)}</li>`).join('')}</ul>`
      : '<p>Not available</p>';
  }
  if (jobDetailsDescription) jobDetailsDescription.textContent = details.description || 'Not available';
  if (jobDetailsLink) {
    if (details.link && /^https?:\/\//i.test(details.link)) {
      jobDetailsLink.href = details.link;
      jobDetailsLink.textContent = details.link;
      jobDetailsLink.classList.remove('hidden');
    } else {
      jobDetailsLink.href = '#';
      jobDetailsLink.textContent = 'Not provided';
      jobDetailsLink.classList.add('hidden');
    }
  }
  jobDetailsModal?.classList.remove('hidden');
}

function closeJobDetailsModal() {
  jobDetailsModal?.classList.add('hidden');
}

closeJobDetails?.addEventListener('click', closeJobDetailsModal);
closeJobDetailsBtn?.addEventListener('click', closeJobDetailsModal);
jobDetailsModal?.addEventListener('click', (e) => {
  if (e.target === jobDetailsModal) closeJobDetailsModal();
});

openGmailDraftBtn?.addEventListener('click', () => {
  const body = (coverLetterContent?.textContent || '').trim();
  if (!body || body.toLowerCase().startsWith('generating cover letter') || body.toLowerCase().startsWith('error:')) {
    alert('Generate a cover letter first.');
    return;
  }

  const fullName = document.getElementById('fullName')?.value?.trim() || 'Candidate';
  const jobTitle = currentCoverLetterContext?.jobTitle || 'the role';
  const recruiterEmail = (document.getElementById('recruiterEmailInput')?.value || '').trim();

  if (recruiterEmail && !looksLikeEmail(recruiterEmail)) {
    alert('That recruiter email address looks invalid. Please correct it or leave it blank.');
    document.getElementById('recruiterEmailInput')?.focus();
    return;
  }

  const subject = `Application for ${jobTitle} - ${fullName}`;
  const params = new URLSearchParams({ view: 'cm', fs: '1', su: subject, body });
  if (recruiterEmail) params.set('to', recruiterEmail);
  const gmailUrl = `https://mail.google.com/mail/?${params.toString()}`;
  window.open(gmailUrl, '_blank', 'noopener,noreferrer');
});

const retrievalDebugModal = document.getElementById('retrievalDebugModal');
const retrievalDebugContent = document.getElementById('retrievalDebugContent');
const closeRetrievalDebug = document.getElementById('closeRetrievalDebug');
const closeRetrievalDebugBtn = document.getElementById('closeRetrievalDebugBtn');
const applicationStatusModal = document.getElementById('applicationStatusModal');
const applicationStatusJob = document.getElementById('applicationStatusJob');
const applicationStatusSelect = document.getElementById('applicationStatusSelect');
const applicationNotesInput = document.getElementById('applicationNotesInput');
const closeApplicationStatus = document.getElementById('closeApplicationStatus');
const cancelApplicationStatusBtn = document.getElementById('cancelApplicationStatusBtn');
const saveApplicationStatusBtn = document.getElementById('saveApplicationStatusBtn');
let pendingApplicationContext = null;

function closeRetrievalDebugModal() {
  retrievalDebugModal?.classList.add('hidden');
}

closeRetrievalDebug?.addEventListener('click', closeRetrievalDebugModal);
closeRetrievalDebugBtn?.addEventListener('click', closeRetrievalDebugModal);
retrievalDebugModal?.addEventListener('click', (e) => {
  if (e.target === retrievalDebugModal) closeRetrievalDebugModal();
});

function closeApplicationStatusModal() {
  applicationStatusModal?.classList.add('hidden');
  pendingApplicationContext = null;
}

function openApplicationStatusModal(jobTitle, company) {
  const key = appKey(jobTitle, company);
  const state = applicationStatusByKey.get(key);
  const currentStatus = state?.status || 'saved';
  const currentNotes = state?.notes || '';
  pendingApplicationContext = { jobTitle, company };
  if (applicationStatusJob) applicationStatusJob.textContent = `${jobTitle} @ ${company}`;
  if (applicationStatusSelect) applicationStatusSelect.value = currentStatus;
  if (applicationNotesInput) applicationNotesInput.value = currentNotes;
  applicationStatusModal?.classList.remove('hidden');
}

closeApplicationStatus?.addEventListener('click', closeApplicationStatusModal);
cancelApplicationStatusBtn?.addEventListener('click', closeApplicationStatusModal);
applicationStatusModal?.addEventListener('click', (e) => {
  if (e.target === applicationStatusModal) closeApplicationStatusModal();
});

saveApplicationStatusBtn?.addEventListener('click', async () => {
  if (!pendingApplicationContext) return;
  const { jobTitle, company } = pendingApplicationContext;
  const status = (applicationStatusSelect?.value || 'saved').toLowerCase();
  const notes = applicationNotesInput?.value || '';
  saveApplicationStatusBtn.disabled = true;
  const oldText = saveApplicationStatusBtn.textContent;
  saveApplicationStatusBtn.textContent = 'Saving...';
  try {
    await saveApplicationStatus(jobTitle, company, status, notes);
    applyApplicationStatusesToUI();
    showToast('Status updated');
    closeApplicationStatusModal();
  } catch (err) {
    showToast(err.message || 'Could not save application status');
  } finally {
    saveApplicationStatusBtn.disabled = false;
    saveApplicationStatusBtn.textContent = oldText;
  }
});

async function openRetrievalDebug() {
  const profile = getCurrentProfileFromForm();
  if (!profile.desiredRole && profile.skills.length === 0 && !profile.additional) {
    alert('Fill at least role/skills/preferences before running retrieval debug.');
    return;
  }
  retrievalDebugContent.textContent = 'Loading retrieval debug...';
  retrievalDebugModal?.classList.remove('hidden');
  const headers = AUTH.headers();
  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/debug/retrieval', {
      method: 'POST',
      headers,
      body: JSON.stringify({ profile, topK: 12 }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Debug retrieval failed (${res.status})`);
    }
    const data = await res.json();
    const lines = [];
    lines.push(`Query: ${data.query}`);
    lines.push(`Top K: ${data.top_k} | Returned: ${data.count}`);
    lines.push('');
    (data.candidates || []).forEach((c, i) => {
      lines.push(`${i + 1}. ${c.title || 'Untitled'} @ ${c.company || 'Unknown'}`);
      lines.push(`   score=${c.score} | semantic=${c.semantic_score} | lexical=${c.lexical_score}`);
      lines.push(`   ${c.location || ''}${c.country ? ', ' + c.country : ''} | ${c.work_type || 'n/a'} | ${c.salary || 'n/a'}`);
      if (c.skills && c.skills.length) lines.push(`   skills: ${c.skills.join(', ')}`);
      if (c.source || c.external_url) lines.push(`   source: ${c.source || 'n/a'} ${c.external_url || ''}`);
      lines.push('');
    });
    retrievalDebugContent.textContent = lines.join('\n').trim();
  } catch (err) {
    retrievalDebugContent.textContent = 'Error: ' + (err.message || String(err));
  }
}

function appKey(jobTitle, company) {
  return `${normalizeJobField(jobTitle)}|${normalizeJobField(company)}`;
}

async function loadApplicationsForSession() {
  try {
    await loadUserData();
    applyApplicationStatusesToUI();
  } catch {
    // Keep UI functional even if applications endpoint is unavailable.
  }
}

const STATUS_LABELS = {
  saved: 'saved',
  applied: 'applied',
  interviewing: 'interviewing',
  offered: 'offered',
  rejected: 'rejected',
};

function applyApplicationStatusesToUI() {
  document.querySelectorAll('.card-apply-btn').forEach((btn) => {
    const title = btn.getAttribute('data-app-title') || '';
    const company = btn.getAttribute('data-app-company') || '';
    const state = applicationStatusByKey.get(appKey(title, company));
    const status = state?.status || 'saved';
    btn.setAttribute('data-app-status', status);
    btn.textContent = `Status: ${STATUS_LABELS[status] || status}`;
  });
}

async function saveApplicationStatus(jobTitle, company, status, notes) {
  const normalizedStatus = normalizeStatus(status);
  const headers = authHeaders();
  const res = await fetch(CONFIG.API_BASE_URL + '/applications', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      session_id: currentSessionId,
      job_title: jobTitle,
      company,
      status: normalizedStatus,
      notes: notes || '',
    }),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Application save failed (${res.status})`);
  }
  const data = await res.json();
  applicationStatusByKey.set(appKey(jobTitle, company), {
    id: data.application_id,
    status: normalizedStatus,
    notes: notes || '',
  });

  const existing = AppState.getApplication(jobTitle, company);
  if (existing) {
    existing.status = normalizedStatus;
    existing.notes = notes || '';
  } else {
    AppState.applications.unshift({
      id: data.application_id,
      session_id: currentSessionId,
      job_title: jobTitle,
      company,
      status: normalizedStatus,
      notes: notes || '',
      created_at: new Date().toISOString(),
      applied_at: normalizedStatus === 'applied' ? new Date().toISOString() : null,
    });
  }
  updateApplicationsBadge();
}

debugRetrievalBtn?.addEventListener('click', () => {
  openRetrievalDebug();
});

async function generateCoverLetter(jobTitle, company, jobDescription, recruiterEmail = '') {
  const profile = getCurrentProfileFromForm();

  if (coverLetterContent) coverLetterContent.textContent = 'Generating cover letter...';
  if (coverLetterModal) coverLetterModal.classList.remove('hidden');

  const headers = AUTH.headers();

  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/cover-letter', {
      method: 'POST',
      headers,
      body: JSON.stringify({ profile, jobTitle, company, jobDescription: jobDescription || '', tone: 'professional' }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    const coverLetterText = (data.cover_letter || 'No cover letter generated.').trim();
    currentCoverLetterContext = {
      jobTitle: jobTitle || '',
      company: company || '',
      recruiterEmail: recruiterEmail || '',
      body: coverLetterText,
    };
    openCoverLetterModal(coverLetterText, recruiterEmail);
  } catch (err) {
    currentCoverLetterContext = null;
    if (coverLetterContent) coverLetterContent.textContent = 'Error: ' + err.message;
  }
}


// ─── STRIP EMOJIS (preserves whitespace / newlines) ─
function stripEmojis(text) {
  return text.replace(/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{1F1E0}-\u{1F1FF}\u{2600}-\u{27BF}\u{2700}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{1FA00}-\u{1FA6F}\u{1FA70}-\u{1FAFF}\u{200D}\u{20E3}\u{E0020}-\u{E007F}\u{2300}-\u{23FF}\u{2B50}\u{2B55}\u{2934}\u{2935}\u{25AA}\u{25AB}\u{25B6}\u{25C0}\u{25FB}-\u{25FE}\u{2614}\u{2615}\u{2648}-\u{2653}\u{26A1}\u{26AA}\u{26AB}\u{26BD}\u{26BE}\u{26C4}\u{26C5}\u{26CE}\u{26D4}\u{26EA}\u{26F2}\u{26F3}\u{26F5}\u{26FA}\u{26FD}\u{2702}\u{2705}\u{2708}-\u{270D}\u{270F}]/gu, '');
}

// ─── CLEAN RESPONSE TEXT ────────────────────────────
function cleanResponse(text) {
  let t = text;
  t = t.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  t = stripEmojis(t);
  t = t.replace(/"/g, '');                       // strip all double-quotes
  t = t.replace(/^ +/gm, m => m.length <= 2 ? '' : m);
  t = t.replace(/\n{3,}/g, '\n\n');
  t = t.replace(/^\s+$/gm, '');
  return t;
}

// ─── CLEAN BULLET TEXT ──────────────────────────────
function cleanBulletText(text) {
  let t = text.replace(/^[-*•]\s*/, '').replace(/\*\*/g, '').trim();
  t = t.replace(/^(Most important next step|Skill to highlight or develop|Question to ask recruiters?|Highlight or develop):\s*/i, '');
  return t;
}

function isBulletLine(text) {
  return /^[-*•]\s+/.test((text || '').trim());
}


// ─── DISPLAY RESULTS ────────────────────────────────
async function displayResults(markdown) {
  try {
    await loadUserData();
  } catch {
    // Render results even if bookmark/application refresh fails.
  }

  const cleaned = cleanResponse(markdown);
  try {
    resultsContent.innerHTML = renderJobResults(cleaned);
    wireCardInteractions();
  } catch (e) {
    console.error('Card renderer failed, using fallback:', e);
    resultsContent.innerHTML = renderFallbackMarkdown(cleaned);
  }
  showState('results');
  if (emailResultsBtn) emailResultsBtn.style.display = '';
  if (debugRetrievalBtn) debugRetrievalBtn.style.display = '';
  applyApplicationStatusesToUI();
}


// ═══════════════════════════════════════════════════════
//  STRUCTURED CARD RENDERER
// ═══════════════════════════════════════════════════════
function renderJobResults(text) {
  if (!text) return '<p class="empty-msg">No response received.</p>';

  const sections = [];
  const lines = text.split('\n');
  let current = { title: '', content: '' };

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('## ')) {
      if (current.title || current.content.trim()) sections.push(current);
      current = { title: trimmed.replace(/^##\s*/, '').replace(/\*\*/g, ''), content: '' };
    } else {
      current.content += line + '\n';
    }
  }
  if (current.title || current.content.trim()) sections.push(current);
  if (sections.length === 0) return renderFallbackMarkdown(text);

  let html = '';
  for (const section of sections) {
    const t = section.title.toLowerCase();
    // Skip the top-level title (already in HTML header)
    if (t.includes('your job match') || t.includes('job recommendation')) continue;
    if (t.includes('summary')) html += renderSummaryCard(section);
    else if (t.includes('match') || t.includes('recommendation')) html += renderMatchesSection(section);
    else if (t.includes('action') || t.includes('step') || t.includes('next')) html += renderActionsCard(section);
    else if (section.title) html += `<div class="result-section"><h2 class="section-heading">${esc(section.title)}</h2>${renderBasicContent(section.content)}</div>`;
    else if (section.content.trim()) {
      // Skip untitled sections that just contain a top-level heading
      const stripped = section.content.trim();
      if (/^#\s+(Your Job Match|Job Recommendation)/i.test(stripped)) continue;
      html += renderBasicContent(section.content);
    }
  }
  return html;
}


// ─── SUMMARY CARD ───────────────────────────────────
function renderSummaryCard(section) {
  const lines = section.content.split('\n').filter(l => l.trim());
  const stats = [];

  for (const line of lines) {
    const cleaned = line.replace(/^[-*•]\s*/, '').replace(/\*\*/g, '').trim();
    if (cleaned.includes(':')) {
      const colonIdx = cleaned.indexOf(':');
      const label = cleaned.substring(0, colonIdx).trim();
      const value = cleaned.substring(colonIdx + 1).trim();
      // Skip 'Matches Returned' — redundant with 'Jobs Found'
      if (label.toLowerCase().includes('matches returned')) continue;
      if (label && value) stats.push({ label, value });
    }
  }

  let html = '<div class="summary-card">';
  html += `<div class="summary-card-header">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M9 21V9"/></svg>
    <span>Summary</span>
  </div>`;
  html += '<div class="summary-stats">';
  for (const stat of stats) {
    html += `<div class="stat-item">
      <div class="stat-value">${esc(stat.value)}</div>
      <div class="stat-label">${esc(stat.label)}</div>
    </div>`;
  }
  html += '</div></div>';
  return html;
}


// ─── MATCHES SECTION ────────────────────────────────
function renderMatchesSection(section) {
  const jobs = [];
  const lines = section.content.split('\n');
  let currentJob = null;

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('### ')) {
      if (currentJob) jobs.push(currentJob);
      currentJob = { title: trimmed.replace(/^###\s*/, '').replace(/\*\*/g, ''), content: '' };
    } else if (currentJob) {
      currentJob.content += line + '\n';
    }
  }
  if (currentJob) jobs.push(currentJob);
  const validJobs = jobs.filter(isRenderableJob);

  if (validJobs.length === 0) {
    return `<div class="result-section"><h2 class="section-heading">${esc(section.title)}</h2><p class="empty-msg">No relevant live jobs found for this query. Try a broader role or add more skills.</p></div>`;
  }

  let html = '<div class="matches-section">';
  html += `<div class="matches-header">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4-4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
    <span>Top Matches</span>
    <span class="matches-count">${validJobs.length} found</span>
  </div>`;

  validJobs.forEach((job, idx) => { html += renderJobCard(job, idx + 1); });
  html += '</div>';
  return html;
}

function isRenderableJob(job) {
  if (!job) return false;
  const combined = `${job.title || ''}\n${job.content || ''}`
    .toLowerCase()
    .replace(/\*\*/g, '')
    .trim();
  if (!combined) return false;
  const blockedPatterns = [
    /no\s+job\s+posting/,
    /no\s+jobs?\s+found/,
    /no\s+relevant\s+jobs?/,
    /not\s+available/,
    /\bn\/a\b/,
    /unable\s+to\s+find\s+jobs?/,
  ];
  return !blockedPatterns.some((pattern) => pattern.test(combined));
}


// ─── JOB CARD ───────────────────────────────────────
function renderJobCard(job, rank) {
  let jobTitle = job.title.replace(/\*\*/g, '');
  let company = '';
  if (jobTitle.includes('@')) {
    const parts = jobTitle.split('@');
    jobTitle = parts[0].trim();
    company = parts.slice(1).join('@').trim();
  }

  const lines = job.content.split('\n');
  let matchScore = '', location = '', salary = '', role = '', applyLink = '';
  const reasons = [], gaps = [], actions = [];
  let experience = '';
  let currentList = null;
  let recruiterEmail = '';
  const jobDescriptionParts = [];

  const parseLabeled = (text, label) => {
    const m = text.match(new RegExp(`^[-*]\\s*\\**${label}:\\s*(.+)$`, 'i'));
    return m ? m[1].trim() : '';
  };

  for (const line of lines) {
    const raw = line.trim();
    if (!raw || raw === '---') continue;
    const clean = raw.replace(/\*\*/g, '');

    if ((clean.toLowerCase().includes('match score') || clean.toLowerCase().includes('match:')) && clean.includes('/10')) {
      const scoreM = clean.match(/(\d+(?:\.\d+)?)\/10/); if (scoreM) matchScore = String(Math.round(parseFloat(scoreM[1])));
      const locM = clean.match(/Location:\s*([^|]+)/i); if (locM) location = locM[1].trim();
      const salM = clean.match(/Salary:\s*([^|]+)/i); if (salM) salary = salM[1].trim();
      continue;
    }

    const lineLocation = parseLabeled(clean, 'Location');
    if (lineLocation && !location) { location = lineLocation; continue; }
    const lineSalary = parseLabeled(clean, 'Salary');
    if (lineSalary && !salary) { salary = lineSalary; continue; }
    const lineRole = parseLabeled(clean, 'Role');
    if (lineRole && !role) { role = lineRole; continue; }
    const lineApply = parseLabeled(clean, 'Apply Link');
    if (lineApply && /https?:\/\//i.test(lineApply)) { applyLink = lineApply; continue; }
    const lineDesc = parseLabeled(clean, 'Job Description');
    if (lineDesc) { jobDescriptionParts.push(lineDesc); continue; }

    if (clean.toLowerCase().includes('action step') || clean.toLowerCase().includes('quick action') || clean.toLowerCase().includes('next step') || clean.toLowerCase().includes('recommended next')) {
      currentList = 'actions'; continue;
    }
    if (clean.toLowerCase().includes('why it match')) { currentList = 'reasons'; continue; }
    if (clean.toLowerCase().includes('gap')) {
      if (isBulletLine(raw)) { gaps.push(cleanBulletText(raw)); }
      currentList = 'gaps'; continue;
    }
    if (clean.toLowerCase().startsWith('experience')) {
      experience = clean.replace(/^Experience\s*(Alignment|alignment)?:\s*/i, '').replace(/^Experience\s*/i, '').trim();
      currentList = null; continue;
    }

    if (isBulletLine(raw)) {
      const item = cleanBulletText(raw);
      if (!item) continue;
      if (currentList === 'reasons') reasons.push(item);
      else if (currentList === 'gaps') gaps.push(item);
      else if (currentList === 'actions') actions.push(item);
      continue;
    }

    const numMatch = raw.match(/^\d+[.\)]\s*(.+)/);
    if (numMatch && currentList === 'actions') { actions.push(cleanBulletText(numMatch[1])); continue; }

    if (currentList === 'actions' && clean.includes(':')) {
      const afterColon = clean.substring(clean.indexOf(':') + 1).trim();
      if (afterColon) { actions.push(afterColon); continue; }
    }

    if (currentList === 'reasons' && clean.length > 20) {
      reasons.push(clean);
      continue;
    }

    if (clean.length > 30 && !/^[-*]/.test(clean) && !/^(Why It Matches|Gaps|Recommended Next Steps|Experience Alignment)\b/i.test(clean)) {
      jobDescriptionParts.push(clean);
    }
  }

  const emailMatch = (job.content || '').match(/\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b/i);
  if (emailMatch) recruiterEmail = emailMatch[0];
  if (!applyLink) {
    const linkMatch = (job.content || '').match(/https?:\/\/[^\s)]+/i);
    if (linkMatch) applyLink = linkMatch[0];
  }
  const jobDescription = jobDescriptionParts.join(' ').trim();

  const score = parseInt(matchScore) || 0;
  const scoreClass = score >= 8 ? 'score-high' : score >= 6 ? 'score-mid' : 'score-low';
  const isBookmarked = AppState.isBookmarked(jobTitle, company);

  // Build plain text for copy-to-clipboard
  let copyText = `${jobTitle}`;
  if (company) copyText += ` @ ${company}`;
  if (role) copyText += `\nRole: ${role}`;
  copyText += `\nMatch Score: ${matchScore}/10`;
  if (location) copyText += `\nLocation: ${location}`;
  if (salary) copyText += `\nSalary: ${salary}`;
  if (applyLink) copyText += `\nApply Link: ${applyLink}`;
  if (jobDescription) copyText += `\nJob Description: ${jobDescription}`;
  if (reasons.length) copyText += `\n\nWhy it matches:\n${reasons.map(r => '• ' + r).join('\n')}`;
  if (gaps.length) copyText += `\n\nGaps:\n${gaps.map(g => '• ' + g).join('\n')}`;
  if (experience) copyText += `\n\nExperience: ${experience}`;
  if (actions.length) copyText += `\n\nNext Steps:\n${actions.map((a, i) => (i + 1) + '. ' + a).join('\n')}`;

  let html = `<div class="job-card" data-copy-text="${esc(copyText)}" style="animation-delay:${rank * 0.06}s">`;

  // ── HEADER (clickable to collapse)
  html += '<div class="job-card-header" data-toggle-card>';
  html += '<div class="job-title-group">';
  html += `<div class="job-rank">#${rank}</div>`;
  html += '<div class="job-title-block">';
  html += `<h3 class="job-title">${esc(jobTitle)}</h3>`;
  if (company) html += `<div class="job-company">${esc(company)}</div>`;
  html += '</div></div>';
  html += '<div class="job-header-right">';

  // Score badge with progress bar
  if (matchScore) {
    const scoreBarClass = score >= 8 ? 'score-high' : score >= 6 ? 'score-mid' : 'score-low';
    const scoreWidth = Math.round((score / 10) * 100);
    html += `<div class="score-bar-wrapper">
      <div class="score-bar"><div class="score-bar-fill ${scoreBarClass}" style="width:${scoreWidth}%"></div></div>
      <div class="score-badge ${scoreClass}"><span class="score-num">${matchScore}</span><span class="score-den">/10</span></div>
    </div>`;
  }

  // Cover letter button
  html += `<button class="card-cover-letter-btn" title="Generate cover letter"
    data-cl-title="${esc(jobTitle)}"
    data-cl-company="${esc(company)}"
    data-cl-desc="${esc(jobDescription.trim().slice(0, 1200))}"
    data-cl-email="${esc(recruiterEmail)}">
    Cover Letter
  </button>`;
  html += `<button class="card-details-btn" title="View full job details"
    data-details-title="${esc(jobTitle)}"
    data-details-company="${esc(company)}"
    data-details-role="${esc(role)}"
    data-details-location="${esc(location)}"
    data-details-salary="${esc(salary)}"
    data-details-link="${esc(applyLink)}"
    data-details-desc="${esc(jobDescription.trim().slice(0, 2200))}"
    data-details-why="${esc(reasons.join(' | '))}">
    Details
  </button>`;

  // Tailor Resume button (only shown if resume was uploaded)
  if (lastResumeText) {
    html += `<button class="card-tailor-btn" title="Tailor your resume for this job"
      data-tailor-title="${esc(jobTitle)}"
      data-tailor-company="${esc(company)}"
      data-tailor-desc="${esc(jobDescription.trim().slice(0, 500))}"
      data-tailor-skills="${esc(reasons.slice(0, 8).join('|'))}">
      Tailor Resume
    </button>`;
  }

  // Bookmark button
  html += `<button class="card-bookmark-btn ${isBookmarked ? 'bookmarked' : ''}" title="Bookmark this job"
    data-bookmark-title="${esc(jobTitle)}"
    data-bookmark-company="${esc(company)}"
    data-bookmark-location="${esc(location)}"
    data-bookmark-salary="${esc(salary)}"
    data-bookmark-score="${score}"
    data-bookmark-description="${esc(jobDescription.trim().slice(0, 550))}">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="${isBookmarked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/></svg>
  </button>`;

  // Copy button
  html += `<button class="card-copy-btn" title="Copy job details" data-copy-card>
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
  </button>`;

  html += `<svg class="card-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>`;
  html += '</div></div>';

  // ── COLLAPSIBLE BODY
  html += '<div class="job-card-body">';

  // Meta chips
  if (role || location || salary) {
    html += '<div class="job-meta">';
    if (role) html += `<span class="meta-chip"><svg class="meta-svg" viewBox="0 0 20 20" fill="currentColor"><path d="M3 5a2 2 0 0 1 2-2h3v2h4V3h3a2 2 0 0 1 2 2v2H3V5z"/><path d="M3 9h14v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9z"/></svg>${esc(role)}</span>`;
    if (location) html += `<span class="meta-chip"><svg class="meta-svg" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clip-rule="evenodd"/></svg>${esc(location)}</span>`;
    if (salary) html += `<span class="meta-chip"><svg class="meta-svg" viewBox="0 0 20 20" fill="currentColor"><path d="M8.433 7.418c.155-.103.346-.196.567-.267v1.698a2.305 2.305 0 01-.567-.267C8.07 8.34 8 8.114 8 8c0-.114.07-.34.433-.582zM11 12.849v-1.698c.22.071.412.164.567.267.364.243.433.468.433.582 0 .114-.07.34-.433.582a2.305 2.305 0 01-.567.267z"/><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-13a1 1 0 10-2 0v.092a4.535 4.535 0 00-1.676.662C6.602 6.234 6 7.009 6 8c0 .99.602 1.765 1.324 2.246.48.32 1.054.545 1.676.662v1.941c-.391-.127-.68-.317-.843-.504a1 1 0 10-1.51 1.31c.562.649 1.413 1.076 2.353 1.253V15a1 1 0 102 0v-.092a4.535 4.535 0 001.676-.662C13.398 13.766 14 12.991 14 12c0-.99-.602-1.765-1.324-2.246A4.535 4.535 0 0011 9.092V7.151c.391.127.68.317.843.504a1 1 0 101.511-1.31c-.563-.649-1.413-1.076-2.354-1.253V5z" clip-rule="evenodd"/></svg>${esc(salary)}</span>`;
    html += '</div>';
  }

  if (jobDescription) {
    html += `<div class="job-description-preview">${esc(jobDescription.slice(0, 280))}${jobDescription.length > 280 ? '…' : ''}</div>`;
  }

  if (applyLink) {
    html += `<a class="job-link-inline" href="${esc(applyLink)}" target="_blank" rel="noopener noreferrer">Open Job Posting</a>`;
  }

  // Why it matches
  if (reasons.length > 0) {
    html += '<div class="job-section reasons-section">';
    html += '<div class="job-section-label"><span class="section-dot dot-green"></span>Why It Matches</div>';
    html += '<ul class="job-list">';
    reasons.forEach(r => { html += `<li>${esc(r)}</li>`; });
    html += '</ul></div>';
  }

  // Gaps
  if (gaps.length > 0) {
    html += '<div class="job-section gaps-section">';
    html += '<div class="job-section-label"><span class="section-dot dot-amber"></span>Gaps</div>';
    html += '<ul class="job-list">';
    gaps.forEach(g => { html += `<li>${esc(g)}</li>`; });
    html += '</ul></div>';
  }

  // Experience alignment
  if (experience) {
    html += `<div class="job-experience"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span><strong>Experience:</strong> ${esc(experience)}</span></div>`;
  }

  // Per-job action steps
  if (actions.length > 0) {
    html += '<div class="job-section actions-section">';
    html += '<div class="job-section-label"><span class="section-dot dot-blue"></span>Recommended Next Steps</div>';
    html += '<ol class="action-list">';
    actions.forEach(a => { html += `<li>${esc(a)}</li>`; });
    html += '</ol></div>';
  }

  html += '</div></div>'; // close body + card
  return html;
}


// ─── ACTIONS CARD (global) ──────────────────────────
function renderActionsCard(section) {
  const lines = section.content.split('\n').filter(l => l.trim());
  const steps = [];

  for (const line of lines) {
    const trimmed = line.trim().replace(/\*\*/g, '');
    const match = trimmed.match(/^\d+[.\)]\s*(.+)/);
    if (match) {
      steps.push(cleanBulletText(match[1]));
    } else if (isBulletLine(trimmed)) {
      steps.push(cleanBulletText(trimmed));
    } else if (trimmed.includes(':')) {
      const afterColon = trimmed.substring(trimmed.indexOf(':') + 1).trim();
      if (afterColon) steps.push(afterColon);
    }
  }

  let html = '<div class="global-actions-card">';
  html += `<div class="global-actions-header">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
    <span>Recommended Next Steps</span>
  </div>`;
  html += '<div class="global-action-steps">';
  steps.forEach((step, i) => {
    html += `<div class="global-action-step">
      <div class="step-number">${i + 1}</div>
      <div class="step-text">${esc(step)}</div>
    </div>`;
  });
  html += '</div></div>';
  return html;
}


// ─── WIRE INTERACTIVE FEATURES ──────────────────────
function wireCardInteractions() {
  // Collapsible cards
  document.querySelectorAll('[data-toggle-card]').forEach(header => {
    header.addEventListener('click', (e) => {
      // Don't collapse if clicking the copy button, bookmark, or cover letter button
      if (e.target.closest('[data-copy-card]')) return;
      if (e.target.closest('.card-bookmark-btn')) return;
      if (e.target.closest('.card-cover-letter-btn')) return;
      if (e.target.closest('.card-tailor-btn')) return;
      if (e.target.closest('.card-details-btn')) return;
      const card = header.closest('.job-card');
      if (card) card.classList.toggle('collapsed');
    });
  });

  // Copy to clipboard
  document.querySelectorAll('[data-copy-card]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const card = btn.closest('.job-card');
      if (!card) return;
      const text = card.getAttribute('data-copy-text') || '';
      navigator.clipboard.writeText(text).then(() => {
        btn.classList.add('copied');
        btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        setTimeout(() => {
          btn.classList.remove('copied');
          btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
        }, 2000);
      });
    });
  });

  // Bookmark buttons
  document.querySelectorAll('.card-bookmark-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const title = btn.getAttribute('data-bookmark-title') || '';
      const company = btn.getAttribute('data-bookmark-company') || '';
      const location = btn.getAttribute('data-bookmark-location') || '';
      const salary = btn.getAttribute('data-bookmark-salary') || '';
      const score = parseFloat(btn.getAttribute('data-bookmark-score') || '0');
      const description = btn.getAttribute('data-bookmark-description') || '';

      try {
        const saved = await toggleBookmark({ title, company, location, salary, score, description });
        const isBookmarked = saved && AppState.isBookmarked(title, company);
        btn.classList.toggle('bookmarked', isBookmarked);
        btn.querySelector('svg')?.setAttribute('fill', isBookmarked ? 'currentColor' : 'none');
      } catch (err) {
        showToast(err.message || 'Could not update bookmark');
      }
    });
  });

  // Cover letter buttons
  document.querySelectorAll('.card-cover-letter-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const title = btn.getAttribute('data-cl-title') || '';
      const company = btn.getAttribute('data-cl-company') || '';
      const desc = btn.getAttribute('data-cl-desc') || '';
      const recruiterEmail = btn.getAttribute('data-cl-email') || '';
      await generateCoverLetter(title, company, desc, recruiterEmail);
    });
  });

  // Job details buttons
  document.querySelectorAll('.card-details-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openJobDetailsModal({
        title: btn.getAttribute('data-details-title') || '',
        company: btn.getAttribute('data-details-company') || '',
        role: btn.getAttribute('data-details-role') || '',
        location: btn.getAttribute('data-details-location') || '',
        salary: btn.getAttribute('data-details-salary') || '',
        link: btn.getAttribute('data-details-link') || '',
        description: btn.getAttribute('data-details-desc') || '',
        why: btn.getAttribute('data-details-why') || '',
      });
    });
  });

  // Tailor Resume buttons
  document.querySelectorAll('.card-tailor-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const title = btn.getAttribute('data-tailor-title') || '';
      const company = btn.getAttribute('data-tailor-company') || '';
      const desc = btn.getAttribute('data-tailor-desc') || '';
      const skillsRaw = btn.getAttribute('data-tailor-skills') || '';
      const skills = skillsRaw ? skillsRaw.split('|').filter(Boolean) : [];
      await tailorResume(title, company, desc, skills);
    });
  });
}


// ─── BASIC CONTENT RENDERER ─────────────────────────
function renderBasicContent(text) {
  if (!text || !text.trim()) return '';
  let html = esc(text);
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  html = html.replace(/^---$/gm, '<hr />');
  html = html.replace(/^[-*•] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^\d+[.\)] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');
  html = html.split(/\n\n+/).map(block => {
    const t = block.trim();
    if (!t) return '';
    if (/^<(h[1-4]|ul|ol|li|blockquote|hr|div|p|table)/.test(t)) return t;
    return `<p>${t.replace(/\n/g, '<br />')}</p>`;
  }).join('\n');
  return html;
}

// ─── FALLBACK MARKDOWN RENDERER ─────────────────────
function renderFallbackMarkdown(text) {
  if (!text) return '<p>No response received.</p>';
  return renderBasicContent(text);
}

// ─── HTML ESCAPING ──────────────────────────────────
function esc(str) { return escapeHtml(str); }
function escapeHtml(str) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(str).replace(/[&<>"']/g, c => map[c]);
}


// ─── UI STATE MANAGEMENT ────────────────────────────
function showState(state) {
  emptyState.classList.add('hidden');
  loadingState.classList.add('hidden');
  errorState.classList.add('hidden');
  resultsContainer.classList.add('hidden');
  switch (state) {
    case 'empty': emptyState.classList.remove('hidden'); break;
    case 'loading': loadingState.classList.remove('hidden'); break;
    case 'error': errorState.classList.remove('hidden'); break;
    case 'results': resultsContainer.classList.remove('hidden'); break;
  }
}

function showError(msg) {
  errorMessage.textContent = msg;
  showState('error');
}


// ─── RESUME ENHANCEMENT ─────────────────────────────
const enhanceResumeBtn = document.getElementById('enhanceResumeBtn');
const resumeEnhanceModal = document.getElementById('resumeEnhanceModal');

if (enhanceResumeBtn) {
  enhanceResumeBtn.addEventListener('click', async () => {
    if (!lastResumeFile) return;
    await callEnhanceResume(lastResumeFile);
  });
}

document.getElementById('closeEnhanceModal')?.addEventListener('click', () => {
  resumeEnhanceModal?.classList.add('hidden');
});
document.getElementById('closeEnhanceModalBtn')?.addEventListener('click', () => {
  resumeEnhanceModal?.classList.add('hidden');
});
resumeEnhanceModal?.addEventListener('click', (e) => {
  if (e.target === resumeEnhanceModal) resumeEnhanceModal.classList.add('hidden');
});

async function callEnhanceResume(file) {
  const statusEl = document.getElementById('enhanceStatus');
  if (statusEl) { statusEl.textContent = 'Analyzing resume...'; statusEl.className = 'enhance-status loading'; }

  const formData = new FormData();
  formData.append('file', file);
  const headers = AUTH.headers({ 'Content-Type': undefined });
  delete headers['Content-Type'];
  headers['X-Session-Id'] = currentSessionId;

  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/enhance-resume', {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    if (data.raw_text || data.resume_text) lastResumeText = data.raw_text || data.resume_text;

    if (statusEl) { statusEl.textContent = ''; statusEl.className = 'enhance-status'; }

    const contentEl = document.getElementById('resumeEnhanceContent');
    if (contentEl) contentEl.innerHTML = renderEnhancementReport(data);
    resumeEnhanceModal?.classList.remove('hidden');
  } catch (err) {
    if (statusEl) { statusEl.textContent = 'Enhancement failed: ' + err.message; statusEl.className = 'enhance-status error'; }
  }
}

function renderEnhancementReport(data) {
  const score = data.overall_score || 0;
  const scoreColor = score >= 85 ? 'var(--success)' : score >= 70 ? 'var(--accent)' : score >= 50 ? 'var(--warning)' : 'var(--danger)';
  const breakdown = data.score_breakdown || {};
  const suggestions = data.suggestions || [];
  const atsTips = data.ats_tips || [];
  const industryTips = data.industry_tips || [];

  let html = `<div class="enhance-report">`;

  // Overall score
  html += `<div class="enhance-score-section">
    <div class="enhance-score-ring" style="--score-color:${scoreColor}">
      <span class="enhance-score-num">${score}</span>
      <span class="enhance-score-label">/100</span>
    </div>
    <div class="enhance-score-meta">
      <h3>Resume Score</h3>
      <p>${score >= 85 ? 'Excellent — minimal changes needed' : score >= 70 ? 'Good — minor polish needed' : score >= 50 ? 'Solid but improvable' : 'Major improvements needed'}</p>
    </div>
  </div>`;

  // Score breakdown
  if (Object.keys(breakdown).length > 0) {
    html += `<div class="enhance-breakdown">`;
    const labels = { action_verbs: 'Action Verbs', quantification: 'Quantification', completeness: 'Completeness', ats_compatibility: 'ATS Compatibility', formatting: 'Formatting' };
    for (const [key, val] of Object.entries(breakdown)) {
      const pct = Math.min(100, Math.max(0, val));
      const barColor = pct >= 70 ? 'var(--success)' : pct >= 50 ? 'var(--warning)' : 'var(--danger)';
      html += `<div class="score-bar-item">
        <span class="score-bar-label">${esc(labels[key] || key)}</span>
        <div class="score-bar-track"><div class="score-bar-fill-enhance" style="width:${pct}%;background:${barColor}"></div></div>
        <span class="score-bar-pct">${pct}</span>
      </div>`;
    }
    html += `</div>`;
  }

  // Suggestions
  if (suggestions.length > 0) {
    html += `<div class="enhance-suggestions"><h4>Improvement Suggestions</h4>`;
    suggestions.forEach(s => {
      const priorityClass = s.priority === 'high' ? 'priority-high' : s.priority === 'medium' ? 'priority-med' : 'priority-low';
      html += `<div class="suggestion-item ${priorityClass}">
        <div class="suggestion-header">
          <span class="suggestion-category">${esc(s.category || '')}</span>
          <span class="suggestion-priority">${esc(s.priority || '')}</span>
        </div>
        <p class="suggestion-issue"><strong>Issue:</strong> ${esc(s.issue || '')}</p>
        <p class="suggestion-fix"><strong>Fix:</strong> ${esc(s.fix || '')}</p>
        ${s.example ? `<p class="suggestion-example">${esc(s.example)}</p>` : ''}
      </div>`;
    });
    html += `</div>`;
  }

  // ATS Tips
  if (atsTips.length > 0) {
    html += `<div class="enhance-tips"><h4>ATS Optimization Tips</h4><ul>`;
    atsTips.forEach(tip => { html += `<li>${esc(tip)}</li>`; });
    html += `</ul></div>`;
  }

  // Industry Tips
  if (industryTips.length > 0) {
    html += `<div class="enhance-tips"><h4>Industry-Specific Tips</h4><ul>`;
    industryTips.forEach(tip => { html += `<li>${esc(tip)}</li>`; });
    html += `</ul></div>`;
  }

  html += `</div>`;
  return html;
}


// ─── TAILOR RESUME ───────────────────────────────────
const tailorResumeModal = document.getElementById('tailorResumeModal');

document.getElementById('closeTailorModal')?.addEventListener('click', () => {
  tailorResumeModal?.classList.add('hidden');
});
document.getElementById('closeTailorModalBtn')?.addEventListener('click', () => {
  tailorResumeModal?.classList.add('hidden');
});
tailorResumeModal?.addEventListener('click', (e) => {
  if (e.target === tailorResumeModal) tailorResumeModal.classList.add('hidden');
});

async function tailorResume(jobTitle, company, jobDesc, jobSkills) {
  if (!lastResumeText) return;

  const titleEl = document.getElementById('tailorModalTitle');
  if (titleEl) titleEl.textContent = `Tailoring Resume for ${jobTitle} @ ${company}`;

  const contentEl = document.getElementById('tailorResumeContent');
  if (contentEl) contentEl.innerHTML = '<div class="tailor-loading">Analyzing job fit...</div>';

  tailorResumeModal?.classList.remove('hidden');

  const headers = AUTH.headers();
  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/tailor-resume', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        resume_text: lastResumeText,
        job_title: jobTitle,
        company: company,
        job_description: jobDesc,
        job_skills: jobSkills,
        session_id: currentSessionId,
      }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    if (contentEl) contentEl.innerHTML = renderTailorReport(data, jobTitle, company);
  } catch (err) {
    if (contentEl) contentEl.innerHTML = `<p class="tailor-error">Tailoring failed: ${esc(err.message)}</p>`;
  }
}

function renderTailorReport(data, jobTitle, company) {
  const score = data.tailored_score || 0;
  const scoreColor = score >= 80 ? 'var(--success)' : score >= 60 ? 'var(--accent)' : score >= 40 ? 'var(--warning)' : 'var(--danger)';
  const kwAnalysis = data.keyword_analysis || { present: [], missing: [], nice_to_have: [] };
  const bulletRewrites = data.bullet_rewrites || [];
  const priorityChanges = data.priority_changes || [];
  const skillsToAdd = data.skills_to_add || [];
  const skillsToEmphasize = data.skills_to_emphasize || [];

  let html = `<div class="tailor-report">`;

  // Score ring
  html += `<div class="tailor-score-section">
    <div class="tailor-score-ring" style="--score-color:${scoreColor}">
      <span class="tailor-score-num">${score}</span>
      <span class="tailor-score-label">/100</span>
    </div>
    <div class="tailor-score-meta">
      <h3>Tailored Match Score</h3>
      <p>${esc(data.score_rationale || '')}</p>
    </div>
  </div>`;

  // Keyword gap analysis
  html += `<div class="keyword-gap-section"><h4>Keyword Gap Analysis</h4>
    <div class="keyword-chips-grid">
      <div class="keyword-col">
        <div class="keyword-col-header kw-present-header">Present</div>
        ${kwAnalysis.present.map(k => `<span class="keyword-chip keyword-chip-present">${esc(k)}</span>`).join('') || '<span class="kw-empty">None detected</span>'}
      </div>
      <div class="keyword-col">
        <div class="keyword-col-header kw-missing-header">Missing</div>
        ${kwAnalysis.missing.map(k => `<span class="keyword-chip keyword-chip-missing">${esc(k)}</span>`).join('') || '<span class="kw-empty">None missing</span>'}
      </div>
      <div class="keyword-col">
        <div class="keyword-col-header kw-nice-header">Nice to Have</div>
        ${(kwAnalysis.nice_to_have || []).map(k => `<span class="keyword-chip keyword-chip-nice">${esc(k)}</span>`).join('') || '<span class="kw-empty">None</span>'}
      </div>
    </div>
  </div>`;

  // Skills to add / emphasize
  if (skillsToAdd.length > 0 || skillsToEmphasize.length > 0) {
    html += `<div class="tailor-skills-section">`;
    if (skillsToAdd.length > 0) {
      html += `<div class="tailor-skill-group"><h5>Skills to Add</h5><div class="skill-chip-row">`;
      skillsToAdd.forEach(s => { html += `<span class="tailor-skill-chip chip-add">${esc(s)}</span>`; });
      html += `</div></div>`;
    }
    if (skillsToEmphasize.length > 0) {
      html += `<div class="tailor-skill-group"><h5>Skills to Emphasize</h5><div class="skill-chip-row">`;
      skillsToEmphasize.forEach(s => { html += `<span class="tailor-skill-chip chip-emphasize">${esc(s)}</span>`; });
      html += `</div></div>`;
    }
    html += `</div>`;
  }

  // Bullet rewrites
  if (bulletRewrites.length > 0) {
    html += `<div class="bullet-rewrites-section"><h4>Resume Bullet Rewrites</h4>`;
    bulletRewrites.forEach(b => {
      html += `<div class="bullet-rewrite-item">
        <div class="bullet-row bullet-original"><span class="bullet-label">Before</span><span class="bullet-text">${esc(b.original || '')}</span></div>
        <div class="bullet-row bullet-new"><span class="bullet-label">After</span><span class="bullet-text">${esc(b.rewritten || '')}</span></div>
        ${b.reason ? `<div class="bullet-reason">${esc(b.reason)}</div>` : ''}
      </div>`;
    });
    html += `</div>`;
  }

  // Priority changes
  if (priorityChanges.length > 0) {
    html += `<div class="priority-changes-section"><h4>Priority Changes</h4>`;
    priorityChanges.forEach(p => {
      const impactClass = p.impact === 'high' ? 'impact-high' : p.impact === 'medium' ? 'impact-med' : 'impact-low';
      html += `<div class="priority-change-item">
        <span class="priority-rank">${p.rank}</span>
        <div class="priority-change-body">
          <span class="priority-change-text">${esc(p.change || '')}</span>
          <span class="impact-badge ${impactClass}">${esc(p.impact || '')} impact</span>
          ${p.section ? `<span class="priority-section">${esc(p.section)}</span>` : ''}
        </div>
      </div>`;
    });
    html += `</div>`;
  }

  html += `</div>`;
  return html;
}


// ─── MY APPLICATIONS VIEW ───────────────────────────
const appMain = document.getElementById('app-main');
const profilePanel = document.getElementById('profile-panel');
const resultsPanel = document.getElementById('results-panel');
const myApplicationsPanel = document.getElementById('myApplicationsPanel');
const myApplicationsBtn = document.getElementById('myApplicationsBtn');
const backToSearchBtn = document.getElementById('backToSearchBtn');
const findJobsBtn = document.getElementById('findJobsBtn');
const homeBtn = document.getElementById('homeBtn');

function goHomeToResumeUpload() {
  closeBrowseJobsView();
  closeMyApplicationsView();
  profilePanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function hashCode(str) {
  let h = 0;
  for (let i = 0; i < str.length; i += 1) {
    h = ((h << 5) - h) + str.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

function companyAvatarStyle(company) {
  const hue = hashCode(company || 'company') % 360;
  return `background: linear-gradient(135deg, hsl(${hue} 70% 52%), hsl(${(hue + 34) % 360} 72% 45%));`;
}

function statusBadgeClass(status) {
  const s = normalizeStatus(status);
  if (s === 'applied') return 'status-badge status-applied';
  if (s === 'interviewing') return 'status-badge status-interviewing';
  if (s === 'offered') return 'status-badge status-offered';
  if (s === 'rejected') return 'status-badge status-rejected';
  return 'status-badge status-saved';
}

function openMyApplicationsView() {
  if (!appMain || !myApplicationsPanel || !profilePanel || !resultsPanel) return;
  appMain.classList.add('myapps-open');
  profilePanel.classList.add('hidden');
  resultsPanel.classList.add('hidden');
  myApplicationsPanel.classList.remove('hidden');
  renderMyApplicationsPage();
}

function closeMyApplicationsView() {
  if (!appMain || !myApplicationsPanel || !profilePanel || !resultsPanel) return;
  appMain.classList.remove('myapps-open');
  myApplicationsPanel.classList.add('hidden');
  profilePanel.classList.remove('hidden');
  resultsPanel.classList.remove('hidden');
}

function getFilteredApplications() {
  if (activeApplicationsTab === 'all') return AppState.applications;
  return AppState.applications.filter((a) => normalizeStatus(a.status) === activeApplicationsTab);
}

function formatDateTime(value) {
  if (!value) return 'N/A';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'N/A';
  return parsed.toLocaleDateString();
}

async function patchApplicationRecord(applicationId, payload) {
  const res = await fetch(`${CONFIG.API_BASE_URL}/applications/${applicationId}`, {
    method: 'PATCH',
    headers: authHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Update failed (${res.status})`);
  }
}

function renderMyApplicationsPage() {
  const statsHost = document.getElementById('myAppsStats');
  const tabsHost = document.getElementById('myAppsTabs');
  const listHost = document.getElementById('myApplicationsList');
  if (!statsHost || !tabsHost || !listHost) return;

  const counts = {
    total: AppState.applications.length,
    saved: AppState.applications.filter((a) => normalizeStatus(a.status) === 'saved').length,
    applied: AppState.applications.filter((a) => normalizeStatus(a.status) === 'applied').length,
    interviewing: AppState.applications.filter((a) => normalizeStatus(a.status) === 'interviewing').length,
    offered: AppState.applications.filter((a) => normalizeStatus(a.status) === 'offered').length,
  };

  statsHost.innerHTML = `
    <div class="myapps-stat"><span>${counts.total}</span><label>Total Saved</label></div>
    <div class="myapps-stat"><span>${counts.applied}</span><label>Applied</label></div>
    <div class="myapps-stat"><span>${counts.interviewing}</span><label>Interviewing</label></div>
    <div class="myapps-stat"><span>${counts.offered}</span><label>Offered</label></div>
  `;

  tabsHost.innerHTML = APP_TABS.map((tab) => `
    <button class="myapps-tab ${activeApplicationsTab === tab ? 'active' : ''}" data-tab="${tab}">
      ${tab.charAt(0).toUpperCase() + tab.slice(1)}
    </button>
  `).join('');

  tabsHost.querySelectorAll('.myapps-tab').forEach((btn) => {
    btn.addEventListener('click', () => {
      activeApplicationsTab = btn.getAttribute('data-tab') || 'all';
      renderMyApplicationsPage();
    });
  });

  const filtered = getFilteredApplications()
    .slice()
    .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));

  if (filtered.length === 0) {
    listHost.innerHTML = `
      <div class="myapps-empty">
        <div class="myapps-empty-icon">&#128188;</div>
        <h3>No saved jobs yet</h3>
        <p>Find jobs and bookmark them to track applications here.</p>
        <button class="btn-primary" id="myAppsFindJobsBtn">Find Jobs</button>
      </div>
    `;
    document.getElementById('myAppsFindJobsBtn')?.addEventListener('click', closeMyApplicationsView);
    return;
  }

  listHost.innerHTML = filtered.map((app, idx) => renderApplicationCard(app, idx)).join('');

  listHost.querySelectorAll('.myapps-status-select').forEach((selectEl) => {
    selectEl.addEventListener('change', async (event) => {
      const selectNode = event.target;
      const appId = Number(selectNode.getAttribute('data-app-id'));
      const status = normalizeStatus(selectNode.value);
      try {
        await patchApplicationRecord(appId, { status });
        const local = AppState.applications.find((a) => a.id === appId);
        if (local) {
          local.status = status;
          if (status === 'applied' && !local.applied_at) {
            local.applied_at = new Date().toISOString();
          }
        }
        const key = appKey(local?.job_title || '', local?.company || '');
        if (applicationStatusByKey.has(key)) {
          applicationStatusByKey.get(key).status = status;
        }
        updateApplicationsBadge();
        showToast('Status updated');
        renderMyApplicationsPage();
        applyApplicationStatusesToUI();
      } catch (err) {
        showToast(err.message || 'Could not update status');
      }
    });
  });

  listHost.querySelectorAll('.myapps-notes').forEach((notesEl) => {
    notesEl.addEventListener('blur', async (event) => {
      const notesNode = event.target;
      const appId = Number(notesNode.getAttribute('data-app-id'));
      const notes = notesNode.value || '';
      try {
        await patchApplicationRecord(appId, { notes });
        const local = AppState.applications.find((a) => a.id === appId);
        if (local) local.notes = notes;
        showToast('Notes saved');
      } catch (err) {
        showToast(err.message || 'Could not save notes');
      }
    });
  });

  listHost.querySelectorAll('.myapps-remove-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const card = btn.closest('.myapps-card');
      const title = btn.getAttribute('data-job-title') || '';
      const company = btn.getAttribute('data-company') || '';
      if (!window.confirm('Remove this job from your saved applications?')) return;

      card?.classList.add('is-removing');
      setTimeout(async () => {
        try {
          await removeSavedJob(title, company);
          showToast('Removed from saved jobs');
          renderMyApplicationsPage();
          applyApplicationStatusesToUI();
        } catch (err) {
          card?.classList.remove('is-removing');
          showToast(err.message || 'Could not remove job');
        }
      }, 220);
    });
  });

  listHost.querySelectorAll('.myapps-cover-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const title = btn.getAttribute('data-job-title') || '';
      const company = btn.getAttribute('data-company') || '';
      const desc = btn.getAttribute('data-job-desc') || '';
      await generateCoverLetter(title, company, desc, '');
    });
  });

  listHost.querySelectorAll('.myapps-tailor-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const title = btn.getAttribute('data-job-title') || '';
      const company = btn.getAttribute('data-company') || '';
      const desc = btn.getAttribute('data-job-desc') || '';
      await tailorResume(title, company, desc, []);
    });
  });
}

function renderApplicationCard(application, idx) {
  const status = normalizeStatus(application.status || 'saved');
  const bookmark = AppState.bookmarks.find((b) => sameJob(b.job_title, b.company, application.job_title, application.company));
  const jobData = bookmark?.job_data || {};
  const location = jobData.location || bookmark?.location || 'Not specified';
  const salary = jobData.salary || bookmark?.salary || 'Not specified';
  const score = Number(jobData.match_score || bookmark?.match_score || 0);
  const scoreClass = score >= 7 ? 'score-high' : (score >= 4 ? 'score-mid' : 'score-low');
  const companyName = application.company || 'Company';
  const avatarInitial = companyName.charAt(0).toUpperCase() || 'C';

  return `
    <article class="myapps-card" style="animation-delay:${idx * 0.06}s">
      <div class="myapps-card-top">
        <div class="myapps-avatar" style="${companyAvatarStyle(companyName)}">${esc(avatarInitial)}</div>
        <div class="myapps-title-wrap">
          <h3>${esc(application.job_title || 'Untitled role')}</h3>
          <p>${esc(companyName)}</p>
        </div>
        <span class="match-pill ${scoreClass}">${Math.round(score * 10) / 10}/10</span>
      </div>

      <div class="myapps-meta">
        <span>&#128205; ${esc(location)}</span>
        <span>&#128176; ${esc(salary)}</span>
      </div>

      <div class="myapps-status-row">
        <span class="${statusBadgeClass(status)}">${esc(status)}</span>
        <select class="myapps-status-select" data-app-id="${application.id}">
          <option value="saved" ${status === 'saved' ? 'selected' : ''}>saved</option>
          <option value="applied" ${status === 'applied' ? 'selected' : ''}>applied</option>
          <option value="interviewing" ${status === 'interviewing' ? 'selected' : ''}>interviewing</option>
          <option value="offered" ${status === 'offered' ? 'selected' : ''}>offered</option>
          <option value="rejected" ${status === 'rejected' ? 'selected' : ''}>rejected</option>
        </select>
      </div>

      <details class="myapps-notes-wrap">
        <summary>Notes</summary>
        <textarea class="myapps-notes" data-app-id="${application.id}" placeholder="Add notes for this role...">${esc(application.notes || '')}</textarea>
      </details>

      <div class="myapps-footer">
        <span class="myapps-date">Added ${esc(formatDateTime(application.created_at))}</span>
        <div class="myapps-actions">
          <button class="btn-secondary myapps-cover-btn" data-job-title="${esc(application.job_title || '')}" data-company="${esc(companyName)}" data-job-desc="${esc(jobData.description || '')}">Cover Letter</button>
          <button class="btn-secondary myapps-tailor-btn" data-job-title="${esc(application.job_title || '')}" data-company="${esc(companyName)}" data-job-desc="${esc(jobData.description || '')}">Tailor Resume</button>
          <button class="btn-secondary myapps-remove-btn" data-job-title="${esc(application.job_title || '')}" data-company="${esc(companyName)}" title="Remove">&#128465;</button>
        </div>
      </div>
    </article>
  `;
}

myApplicationsBtn?.addEventListener('click', async () => {
  try {
    await loadUserData();
  } catch {
    // Continue with any available cached state.
  }
  openMyApplicationsView();
});

backToSearchBtn?.addEventListener('click', closeMyApplicationsView);
findJobsBtn?.addEventListener('click', closeMyApplicationsView);
homeBtn?.addEventListener('click', goHomeToResumeUpload);

// ─── BROWSE JOBS VIEW ────────────────────────────────
const browseJobsPanel = document.getElementById('browseJobsPanel');
const browseJobsBtn   = document.getElementById('browseJobsBtn');
const backFromBrowseBtn = document.getElementById('backFromBrowseBtn');

let browseState = { page: 0, q: '', location: '', industry: '', loading: false };

function openBrowseJobsView() {
  if (!appMain || !browseJobsPanel || !profilePanel || !resultsPanel) return;
  myApplicationsPanel?.classList.add('hidden');
  appMain.classList.add('myapps-open'); // reuse full-width layout class
  profilePanel.classList.add('hidden');
  resultsPanel.classList.add('hidden');
  browseJobsPanel.classList.remove('hidden');
}

function closeBrowseJobsView() {
  if (!appMain || !browseJobsPanel || !profilePanel || !resultsPanel) return;
  appMain.classList.remove('myapps-open');
  browseJobsPanel.classList.add('hidden');
  profilePanel.classList.remove('hidden');
  resultsPanel.classList.remove('hidden');
}

function workTypeChipClass(wt) {
  const v = (wt || '').toLowerCase();
  if (v.includes('remote')) return 'bjc-chip bjc-chip-worktype bjc-chip-remote';
  if (v.includes('hybrid')) return 'bjc-chip bjc-chip-worktype bjc-chip-hybrid';
  if (v.includes('on-site') || v.includes('onsite')) return 'bjc-chip bjc-chip-worktype bjc-chip-onsite';
  return 'bjc-chip bjc-chip-worktype bjc-chip-other';
}

function renderBrowseJobCard(job, idx) {
  const isBookmarked = AppState.isBookmarked(job.title, job.company);
  const skills = Array.isArray(job.skills) ? job.skills.slice(0, 6) : [];
  const locationDisplay = [job.location, job.country].filter(Boolean).join(', ');
  const delay = (idx % 20) * 0.04;

  let html = `<article class="browse-job-card" style="animation-delay:${delay}s">`;

  // Top: title + company + bookmark
  html += `<div class="bjc-top">
    <div class="bjc-title-block">
      <h3 class="bjc-title" title="${esc(job.title)}">${esc(job.title)}</h3>
      ${job.company ? `<div class="bjc-company">${esc(job.company)}</div>` : ''}
    </div>
    <button class="bjc-bookmark-btn ${isBookmarked ? 'bookmarked' : ''}"
      data-bjc-bookmark
      data-title="${esc(job.title)}"
      data-company="${esc(job.company)}"
      data-location="${esc(locationDisplay)}"
      data-salary="${esc(job.salary || '')}"
      data-description="${esc((job.description || '').slice(0, 300))}"
      title="${isBookmarked ? 'Remove bookmark' : 'Bookmark this job'}">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="${isBookmarked ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/></svg>
    </button>
  </div>`;

  // Meta chips
  html += `<div class="bjc-meta">`;
  if (locationDisplay) html += `<span class="bjc-chip bjc-chip-location"><svg width="11" height="11" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clip-rule="evenodd"/></svg>${esc(locationDisplay)}</span>`;
  if (job.work_type) html += `<span class="${workTypeChipClass(job.work_type)}">${esc(job.work_type)}</span>`;
  if (job.salary) html += `<span class="bjc-chip bjc-chip-salary">💰 ${esc(job.salary)}</span>`;
  html += `</div>`;

  // Description snippet
  if (job.description) {
    html += `<p class="bjc-desc">${esc(job.description)}</p>`;
  }

  // Skills
  if (skills.length > 0) {
    html += `<div class="bjc-skills">` + skills.map(s => `<span class="bjc-skill-tag">${esc(s)}</span>`).join('') + `</div>`;
  }

  // Actions
  html += `<div class="bjc-actions">`;
  if (job.external_url) {
    html += `<a class="bjc-apply-btn" href="${esc(job.external_url)}" target="_blank" rel="noopener noreferrer">
      Apply
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
    </a>`;
  }
  if (job.source && job.source !== 'pinecone' && job.source !== 'local_csv') {
    html += `<span class="bjc-source-badge">${esc(job.source)}</span>`;
  }
  html += `</div>`;

  html += `</article>`;
  return html;
}

async function fetchAndRenderBrowseJobs() {
  if (browseState.loading) return;
  browseState.loading = true;

  const stateEl   = document.getElementById('browseJobsState');
  const loadingEl = document.getElementById('browseJobsLoading');
  const gridEl    = document.getElementById('browseJobsGrid');
  const paginEl   = document.getElementById('browsePagination');
  const pageInfo  = document.getElementById('browsePageInfo');
  const prevBtn   = document.getElementById('browsePrevBtn');
  const nextBtn   = document.getElementById('browseNextBtn');
  const countEl   = document.getElementById('browseResultsCount');

  stateEl?.classList.add('hidden');
  gridEl?.classList.add('hidden');
  paginEl?.classList.add('hidden');
  if (countEl) countEl.classList.add('hidden');
  loadingEl?.classList.remove('hidden');

  const params = new URLSearchParams({
    page: browseState.page,
    page_size: 18,
  });
  if (browseState.q) params.set('q', browseState.q);
  if (browseState.location) params.set('location', browseState.location);
  if (browseState.industry) params.set('industry', browseState.industry);

  try {
    const token = AUTH.getToken();
    const getHeaders = {};
    if (token) getHeaders['Authorization'] = `Bearer ${token}`;
    if (CONFIG.API_KEY) getHeaders['X-Api-Key'] = CONFIG.API_KEY;
    const res = await fetch(`${CONFIG.API_BASE_URL}/jobs/browse?${params}`, {
      headers: getHeaders,
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();

    loadingEl?.classList.add('hidden');

    if (!data.jobs || data.jobs.length === 0) {
      if (stateEl) {
        stateEl.innerHTML = `<div class="state-icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></div><h3>No results found</h3><p>Try a different keyword or clear the filters.</p>`;
        stateEl.classList.remove('hidden');
      }
    } else {
      if (countEl) {
        countEl.textContent = `${data.total.toLocaleString()} job${data.total !== 1 ? 's' : ''} found`;
        countEl.classList.remove('hidden');
      }
      if (gridEl) {
        gridEl.innerHTML = data.jobs.map((job, i) => renderBrowseJobCard(job, i)).join('');
        gridEl.classList.remove('hidden');
      }

      // Pagination
      const totalPages = Math.max(1, Math.ceil(data.total / 18));
      const currentPage = data.page + 1;
      if (paginEl && pageInfo && prevBtn && nextBtn) {
        pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
        prevBtn.disabled = browseState.page === 0;
        nextBtn.disabled = !data.has_more;
        paginEl.classList.remove('hidden');
      }
    }
  } catch (err) {
    loadingEl?.classList.add('hidden');
    if (stateEl) {
      stateEl.innerHTML = `<div class="state-icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg></div><h3>Failed to load jobs</h3><p>${esc(err.message)}</p>`;
      stateEl.classList.remove('hidden');
    }
  } finally {
    browseState.loading = false;
  }
}

// Wire up browse panel events
browseJobsBtn?.addEventListener('click', () => {
  openBrowseJobsView();
  // Auto-load on first open
  if (!document.getElementById('browseJobsGrid')?.innerHTML) {
    fetchAndRenderBrowseJobs();
  }
});

backFromBrowseBtn?.addEventListener('click', closeBrowseJobsView);

function readBrowseFilters() {
  browseState.q        = document.getElementById('browseSearchInput')?.value.trim() || '';
  browseState.location = document.getElementById('browseLocationFilter')?.value.trim() || '';
  browseState.industry = document.getElementById('browseIndustryFilter')?.value || '';
  browseState.page     = 0;
}

document.getElementById('browseSearchBtn')?.addEventListener('click', () => {
  readBrowseFilters();
  fetchAndRenderBrowseJobs();
});

document.getElementById('browseClearBtn')?.addEventListener('click', () => {
  ['browseSearchInput', 'browseLocationFilter'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  const ind = document.getElementById('browseIndustryFilter');
  if (ind) ind.value = '';
  browseState = { page: 0, q: '', location: '', industry: '', loading: false };
  fetchAndRenderBrowseJobs();
});

document.getElementById('browseSearchInput')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('browseSearchBtn')?.click();
});

document.getElementById('browsePrevBtn')?.addEventListener('click', () => {
  if (browseState.page > 0) { browseState.page--; fetchAndRenderBrowseJobs(); }
});

document.getElementById('browseNextBtn')?.addEventListener('click', () => {
  browseState.page++;
  fetchAndRenderBrowseJobs();
});

// Bookmark delegation inside browse grid
document.getElementById('browseJobsGrid')?.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-bjc-bookmark]');
  if (!btn) return;

  const title       = btn.dataset.title || '';
  const company     = btn.dataset.company || '';
  const location    = btn.dataset.location || '';
  const salary      = btn.dataset.salary || '';
  const description = btn.dataset.description || '';

  const isBookmarked = AppState.isBookmarked(title, company);

  if (isBookmarked) {
    const existing = AppState.bookmarks.find(b => sameJob(b.job_title, b.company, title, company));
    if (existing?.bookmark_id) {
      try {
        await fetch(`${CONFIG.API_BASE_URL}/bookmarks/${existing.bookmark_id}`, {
          method: 'DELETE',
          headers: authHeaders(),
        });
        AppState.bookmarks = AppState.bookmarks.filter(b => b.bookmark_id !== existing.bookmark_id);
        showToast('Bookmark removed');
      } catch { showToast('Failed to remove bookmark'); }
    }
  } else {
    try {
      const res = await fetch(`${CONFIG.API_BASE_URL}/bookmark`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          session_id: currentSessionId,
          job_title: title,
          company,
          location,
          salary,
          score: 0,
          description,
        }),
      });
      const data = await res.json();
      AppState.bookmarks.push({
        bookmark_id: data.bookmark_id,
        job_title: title,
        company,
        location,
        salary,
        score: 0,
      });
      showToast('Job bookmarked!');
    } catch { showToast('Failed to bookmark job'); }
  }

  // Update button icon without re-fetching
  const nowBookmarked = AppState.isBookmarked(title, company);
  const svg = btn.querySelector('svg');
  if (svg) svg.setAttribute('fill', nowBookmarked ? 'currentColor' : 'none');
  btn.classList.toggle('bookmarked', nowBookmarked);
  btn.title = nowBookmarked ? 'Remove bookmark' : 'Bookmark this job';
});
