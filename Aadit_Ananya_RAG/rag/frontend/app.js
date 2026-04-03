/* ══════════════════════════════════════════════════════
   JobMatch AI — Dashboard Logic
   ══════════════════════════════════════════════════════ */

// CONFIG is loaded from config.js

// ─── SESSION ID ───────────────────────────────────────
let currentSessionId = `session_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

// ─── BOOKMARKS (localStorage) ─────────────────────────
let bookmarkedJobsData = [];
try {
  const storedBookmarks = localStorage.getItem('jobmatch_bookmarks') || '[]';
  const parsedBookmarks = JSON.parse(storedBookmarks);
  bookmarkedJobsData = Array.isArray(parsedBookmarks) ? parsedBookmarks : [];
} catch {
  bookmarkedJobsData = [];
}
const bookmarkedJobs = new Set(bookmarkedJobsData);

// ─── DOM ELEMENTS ────────────────────────────────────
const form = document.getElementById('profile-form');
const submitBtn = document.getElementById('submitBtn');
const clearBtn = document.getElementById('clearBtn');
const emailResultsBtn = document.getElementById('emailResultsBtn');
const trackerBtn = document.getElementById('trackerBtn');
const subscribeAlertsBtn = document.getElementById('subscribeAlertsBtn');

const emptyState = document.getElementById('empty-state');
const loadingState = document.getElementById('loading-state');
const errorState = document.getElementById('error-state');
const errorMessage = document.getElementById('error-message');
const resultsContainer = document.getElementById('results-container');
const resultsContent = document.getElementById('results-content');

const experienceSlider = document.getElementById('experience');
const experienceValue = document.getElementById('experienceValue');
const authStatus = document.getElementById('authStatus');
const googleSignInButton = document.getElementById('googleSignInButton');
const saveProfileBtn = document.getElementById('saveProfileBtn');
const signOutBtn = document.getElementById('signOutBtn');

let authenticatedUser = null;

function setAuthStatus(message, tone = 'neutral') {
  if (authStatus) {
    authStatus.textContent = message;
    authStatus.dataset.tone = tone;
  }
}

function setSignedInUser(user) {
  authenticatedUser = user || null;
  if (authenticatedUser?.email) {
    localStorage.setItem('jobmatch_auth_email', authenticatedUser.email);
    localStorage.setItem('jobmatch_auth_name', authenticatedUser.name || '');
    localStorage.setItem('jobmatch_auth_picture', authenticatedUser.picture || '');
    if (signOutBtn) signOutBtn.classList.remove('hidden');
    setAuthStatus(`Signed in as ${authenticatedUser.name || authenticatedUser.email}`, 'success');
  } else {
    localStorage.removeItem('jobmatch_auth_email');
    localStorage.removeItem('jobmatch_auth_name');
    localStorage.removeItem('jobmatch_auth_picture');
    if (signOutBtn) signOutBtn.classList.add('hidden');
    setAuthStatus('Sign in with Google to load and save your profile.', 'neutral');
  }
}

function applyProfileToForm(profile) {
  if (!profile) return;
  const safeProfile = profile || {};
  if (safeProfile.name) document.getElementById('fullName').value = safeProfile.name;
  if (safeProfile.email) document.getElementById('email').value = safeProfile.email;
  if (safeProfile.desiredRole) document.getElementById('desiredRole').value = safeProfile.desiredRole;
  if (typeof safeProfile.experience === 'number') {
    const expVal = Math.min(Math.max(parseInt(safeProfile.experience, 10) || 0, 0), 30);
    experienceSlider.value = expVal;
    experienceValue.textContent = `${expVal} yr${expVal !== 1 ? 's' : ''}`;
  }
  if (safeProfile.education) document.getElementById('education').value = safeProfile.education;
  if (safeProfile.industry) document.getElementById('industry').value = safeProfile.industry;
  if (safeProfile.location) document.getElementById('location').value = safeProfile.location;
  if (safeProfile.workType) document.getElementById('workType').value = safeProfile.workType;
  if (safeProfile.salaryMin !== undefined && safeProfile.salaryMin !== null) document.getElementById('salaryMin').value = safeProfile.salaryMin;
  if (safeProfile.companySize) document.getElementById('companySize').value = safeProfile.companySize;
  if (safeProfile.workAuth) document.getElementById('workAuth').value = safeProfile.workAuth;
  if (safeProfile.additional) document.getElementById('additional').value = safeProfile.additional;

  if (Array.isArray(safeProfile.skills) && safeProfile.skills.length > 0) {
    skillsTagContainer.querySelectorAll('.skill-tag').forEach(tag => tag.remove());
    skillTags.length = 0;
    safeProfile.skills.slice(0, 12).forEach(skill => addSkillTag(skill));
  }

  if (Array.isArray(safeProfile.benefits) && safeProfile.benefits.length > 0) {
    document.querySelectorAll('input[name="benefits"]').forEach(cb => {
      cb.checked = safeProfile.benefits.includes(cb.value);
    });
  }
}

async function loadProfileFromBackend(email) {
  if (!email) return null;
  try {
    const res = await fetch(CONFIG.API_BASE_URL + `/profile/${encodeURIComponent(email)}`, {
      headers: getApiHeaders(false),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function saveProfileToBackend(sendConfirmation = true) {
  const profile = buildCurrentProfile();
  const email = (profile.email || authenticatedUser?.email || '').trim();
  if (!email) {
    setAuthStatus('Add an email address before saving your profile.', 'warning');
    return null;
  }

  const payload = {
    email,
    name: profile.name || authenticatedUser?.name || '',
    google_sub: authenticatedUser?.google_sub || '',
    picture: authenticatedUser?.picture || '',
    profile,
    send_confirmation: sendConfirmation,
  };

  const res = await fetch(CONFIG.API_BASE_URL + '/profile', {
    method: 'POST',
    headers: getApiHeaders(true),
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Could not save profile (${res.status})`);
  }

  const data = await res.json();
  setAuthStatus(sendConfirmation ? 'Profile saved and confirmation email sent if configured.' : 'Profile saved.', 'success');
  return data;
}

async function handleGoogleCredentialResponse(response) {
  if (!response?.credential) {
    setAuthStatus('Google sign-in was cancelled or did not return a credential.', 'warning');
    return;
  }

  setAuthStatus('Signing you in with Google...', 'neutral');
  const profile = buildCurrentProfile();

  const res = await fetch(CONFIG.API_BASE_URL + '/auth/google', {
    method: 'POST',
    headers: getApiHeaders(true),
    body: JSON.stringify({ credential: response.credential, profile }),
  });

  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Google sign-in failed (${res.status})`);
  }

  const data = await res.json();
  const user = data.user || {};
  setSignedInUser({
    email: user.email || profile.email || '',
    name: user.name || profile.name || '',
    picture: user.picture || '',
    google_sub: user.google_sub || '',
  });

  const savedProfile = await loadProfileFromBackend(user.email || profile.email || '');
  if (savedProfile?.profile) {
    applyProfileToForm(savedProfile.profile);
  } else {
    applyProfileToForm(profile);
  }

  if (saveProfileBtn) saveProfileBtn.classList.remove('hidden');
}

function initializeGoogleSignIn() {
  if (!CONFIG.GOOGLE_CLIENT_ID) {
    setAuthStatus('Google SSO is not configured. Set GOOGLE_CLIENT_ID to enable sign-in.', 'warning');
    if (googleSignInButton) googleSignInButton.innerHTML = '<div class="auth-note">Google sign-in unavailable until GOOGLE_CLIENT_ID is set.</div>';
    return;
  }

  if (!window.google?.accounts?.id || !googleSignInButton) {
    setAuthStatus('Google sign-in is loading...', 'neutral');
    return;
  }

  window.google.accounts.id.initialize({
    client_id: CONFIG.GOOGLE_CLIENT_ID,
    callback: async (resp) => {
      try {
        await handleGoogleCredentialResponse(resp);
      } catch (err) {
        setAuthStatus(err.message || 'Google sign-in failed.', 'warning');
      }
    },
  });

  window.google.accounts.id.renderButton(googleSignInButton, {
    theme: 'outline',
    size: 'large',
    shape: 'pill',
    text: 'signin_with',
    width: 280,
  });

  const storedEmail = localStorage.getItem('jobmatch_auth_email') || '';
  if (storedEmail) {
    setSignedInUser({
      email: storedEmail,
      name: localStorage.getItem('jobmatch_auth_name') || storedEmail.split('@')[0],
      picture: localStorage.getItem('jobmatch_auth_picture') || '',
    });
    loadProfileFromBackend(storedEmail).then(saved => {
      if (saved?.profile) applyProfileToForm(saved.profile);
    });
  }
}

function signOutProfile() {
  setSignedInUser(null);
  if (googleSignInButton) googleSignInButton.innerHTML = '';
  initializeGoogleSignIn();
}

function scheduleGoogleSignInInit(attempts = 20) {
  if (window.google?.accounts?.id) {
    initializeGoogleSignIn();
    return;
  }
  if (attempts <= 0) {
    setAuthStatus('Google sign-in could not load. Check your network or GOOGLE_CLIENT_ID.', 'warning');
    return;
  }
  setTimeout(() => scheduleGoogleSignInInit(attempts - 1), 250);
}

const trackerModal = document.getElementById('trackerModal');
const trackerContent = document.getElementById('trackerContent');
const closeTrackerModal = document.getElementById('closeTrackerModal');
const closeTrackerModalBtn = document.getElementById('closeTrackerModalBtn');
const refreshTrackerBtn = document.getElementById('refreshTrackerBtn');

let currentProfileSnapshot = null;
let uploadedResumeText = '';
let latestTopMatches = [];
const latestScoreBreakdownMap = new Map();

function normalizeRoleKey(title, company) {
  return `${String(title || '').trim().toLowerCase()}|${String(company || '').trim().toLowerCase()}`;
}

function getApiHeaders(isJson = true) {
  const headers = {};
  if (isJson) headers['Content-Type'] = 'application/json';
  if (CONFIG.API_KEY) headers['X-Api-Key'] = CONFIG.API_KEY;
  return headers;
}

function buildCurrentProfile() {
  commitPendingSkills();
  return {
    name: document.getElementById('fullName').value.trim(),
    email: document.getElementById('email').value.trim(),
    desiredRole: document.getElementById('desiredRole').value.trim(),
    experience: parseInt(experienceSlider.value, 10),
    skills: skillTags.slice(),
    education: document.getElementById('education').value,
    industry: document.getElementById('industry').value.trim(),
    location: document.getElementById('location').value.trim(),
    workType: document.getElementById('workType').value,
    salaryMin: document.getElementById('salaryMin').value ? parseInt(document.getElementById('salaryMin').value, 10) : null,
    companySize: document.getElementById('companySize').value,
    benefits: Array.from(document.querySelectorAll('input[name="benefits"]:checked')).map(cb => cb.value),
    workAuth: document.getElementById('workAuth').value,
    additional: document.getElementById('additional').value.trim(),
  };
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

// Populate skills datalist
const skillsList = document.getElementById('skillsList');
if (skillsList && typeof COMMON_SKILLS !== 'undefined') {
  COMMON_SKILLS.forEach(skill => {
    const option = document.createElement('option');
    option.value = skill;
    skillsList.appendChild(option);
  });
}


// ─── TAG-BASED SKILLS INPUT ─────────────────────────
const skillsTagContainer = document.getElementById('skillsTagContainer');
const skillsInput = document.getElementById('skillsInput');
const skillsHidden = document.getElementById('skills');
const skillTags = [];

// Add a skill tag
function addSkillTag(skillName) {
  const trimmed = skillName.trim();
  if (!trimmed || skillTags.includes(trimmed)) return;

  skillTags.push(trimmed);

  // Create tag element
  const tag = document.createElement('div');
  tag.className = 'skill-tag';
  tag.innerHTML = `
    <span>${trimmed}</span>
    <span class="skill-tag-remove">×</span>
  `;

  // Remove on click
  tag.querySelector('.skill-tag-remove').addEventListener('click', () => {
    const index = skillTags.indexOf(trimmed);
    if (index > -1) {
      skillTags.splice(index, 1);
      tag.remove();
      updateHiddenSkillsField();
    }
  });

  // Insert before the input field
  skillsTagContainer.insertBefore(tag, skillsInput);
  updateHiddenSkillsField();
}

// Update hidden field with comma-separated skills
function updateHiddenSkillsField() {
  skillsHidden.value = skillTags.join(', ');
}

function commitPendingSkills() {
  const value = skillsInput.value.trim();
  if (!value) return;
  const skills = value.split(',').map(s => s.trim()).filter(Boolean);
  skills.forEach(skill => addSkillTag(skill));
  skillsInput.value = '';
}

// Handle input events
skillsInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ',') {
    e.preventDefault();
    const value = skillsInput.value.trim();
    if (value) {
      addSkillTag(value);
      skillsInput.value = '';
    }
  } else if (e.key === 'Backspace' && !skillsInput.value && skillTags.length > 0) {
    // Remove last tag if backspace pressed on empty input
    const lastSkill = skillTags[skillTags.length - 1];
    const tags = skillsTagContainer.querySelectorAll('.skill-tag');
    if (tags.length > 0) {
      tags[tags.length - 1].remove();
      skillTags.pop();
      updateHiddenSkillsField();
    }
  }
});

// Also allow adding on blur (paste support)
skillsInput.addEventListener('blur', () => {
  commitPendingSkills();
});

// Click on container focuses the input
skillsTagContainer.addEventListener('click', () => {
  skillsInput.focus();
});

saveProfileBtn?.addEventListener('click', async () => {
  try {
    saveProfileBtn.disabled = true;
    saveProfileBtn.textContent = 'Saving...';
    const result = await saveProfileToBackend(true);
    if (result?.user?.email) {
      setSignedInUser({
        email: result.user.email,
        name: result.user.name || document.getElementById('fullName').value.trim(),
        picture: result.user.picture || '',
        google_sub: result.user.google_sub || '',
      });
    }
  } catch (err) {
    setAuthStatus(err.message || 'Could not save profile.', 'warning');
  } finally {
    saveProfileBtn.disabled = false;
    saveProfileBtn.textContent = 'Save Profile';
  }
});

signOutBtn?.addEventListener('click', () => {
  signOutProfile();
});


// ─── BENEFITS CHECKBOX LIMIT ─────────────────────────
const benefitsCheckboxes = document.querySelectorAll('input[name="benefits"]');
const MAX_BENEFITS = 3;

benefitsCheckboxes.forEach(checkbox => {
  checkbox.addEventListener('change', () => {
    const checked = document.querySelectorAll('input[name="benefits"]:checked');
    if (checked.length > MAX_BENEFITS) {
      checkbox.checked = false;
    }
  });
});


// ─── EXPERIENCE SLIDER ──────────────────────────────
experienceSlider.addEventListener('input', () => {
  const val = experienceSlider.value;
  experienceValue.textContent = `${val} yr${val !== '1' ? 's' : ''}`;
});


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

  const headers = { 'Content-Type': 'application/json' };
  if (CONFIG.API_KEY) headers['X-Api-Key'] = CONFIG.API_KEY;

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
  if (typeof data === 'string') return { output: data, topMatches: [] };
  if (data.output || data.topMatches || data.sessionId) return data;
  if (data.text) return { output: data.text, topMatches: [] };
  if (data.response) return { output: data.response, topMatches: [] };
  return { output: JSON.stringify(data, null, 2), topMatches: [] };
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


// ─── FORM SUBMISSION ────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const profile = buildCurrentProfile();
  currentProfileSnapshot = profile;

  // Switch UI states
  showState('loading');
  submitBtn.disabled = true;
  if (emailResultsBtn) emailResultsBtn.style.display = 'none';

  try {
    const response = await sendToBackend(profile);
    displayResults(response);
    if (authenticatedUser?.email || profile.email) {
      saveProfileToBackend(false).catch(err => console.warn('Profile save skipped:', err.message));
    }
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
  if (trackerBtn) trackerBtn.style.display = 'none';
  if (subscribeAlertsBtn) subscribeAlertsBtn.style.display = 'none';
});


// ─── EMAIL MY RESULTS ────────────────────────────────
if (emailResultsBtn) {
  emailResultsBtn.addEventListener('click', async () => {
    const emailVal = document.getElementById('email').value.trim();
    const nameVal = document.getElementById('fullName').value.trim();
    if (!emailVal) {
      alert('Please enter your email address in the form before sending results.');
      return;
    }
    const resultsMarkdown = resultsContent.innerText || resultsContent.textContent || '';
    const headers = { 'Content-Type': 'application/json' };
    if (CONFIG.API_KEY) headers['X-Api-Key'] = CONFIG.API_KEY;
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


// ─── RESUME UPLOAD ───────────────────────────────────
const resumeDropzone = document.getElementById('resume-dropzone');
const resumeFileInput = document.getElementById('resumeFile');
const resumeStatus = document.getElementById('resumeStatus');

async function handleResumeUpload(file) {
  if (!file || !file.name.endsWith('.pdf')) {
    resumeStatus.textContent = 'Only PDF files accepted.';
    resumeStatus.className = 'resume-status error';
    return;
  }
  resumeStatus.textContent = 'Parsing resume...';
  resumeStatus.className = 'resume-status loading';

  const formData = new FormData();
  formData.append('file', file);
  const headers = {};
  if (CONFIG.API_KEY) headers['X-Api-Key'] = CONFIG.API_KEY;

  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/parse-resume', {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    uploadedResumeText = data.resume_text || '';

    // Auto-populate form fields
    if (data.name) document.getElementById('fullName').value = data.name;
    if (data.recent_role) document.getElementById('desiredRole').value = data.recent_role;
    if (data.experience_years) {
      const expVal = Math.min(Math.max(parseInt(data.experience_years, 10) || 0, 0), 30);
      experienceSlider.value = expVal;
      experienceValue.textContent = `${expVal} yr${expVal !== 1 ? 's' : ''}`;
    }
    if (data.education) document.getElementById('education').value = data.education;
    if (data.industries && data.industries.length > 0) {
      document.getElementById('industry').value = data.industries[0];
    }
    if (data.skills && data.skills.length > 0) {
      // Clear existing tags
      skillsTagContainer.querySelectorAll('.skill-tag').forEach(t => t.remove());
      skillTags.length = 0;
      data.skills.slice(0, 12).forEach(skill => addSkillTag(skill));
    }

    resumeStatus.textContent = 'Resume parsed! Fields auto-filled.';
    resumeStatus.className = 'resume-status success';
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

scheduleGoogleSignInInit();


// ─── BOOKMARK FUNCTIONALITY ──────────────────────────
async function saveBookmark(jobTitle, company, location, salary, matchScore) {
  const bookmarkKey = jobTitle + '|' + company;
  const headers = { 'Content-Type': 'application/json' };
  if (CONFIG.API_KEY) headers['X-Api-Key'] = CONFIG.API_KEY;
  try {
    await fetch(CONFIG.API_BASE_URL + '/bookmark', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        session_id: currentSessionId,
        job_title: jobTitle,
        company: company,
        location: location,
        salary: salary,
        match_score: matchScore,
        job_data: { title: jobTitle, company, location, salary },
      }),
    });
    bookmarkedJobs.add(bookmarkKey);
    localStorage.setItem('jobmatch_bookmarks', JSON.stringify([...bookmarkedJobs]));
  } catch (err) {
    console.warn('Bookmark save failed:', err.message);
  }
}


// ─── APPLICATION TRACKER ─────────────────────────────
async function addToTracker(jobTitle, company, location, salary) {
  const headers = getApiHeaders(true);
  const res = await fetch(CONFIG.API_BASE_URL + '/applications', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      session_id: currentSessionId,
      job_title: jobTitle,
      company,
      location,
      salary,
      source: 'jobmatch',
      notes: '',
    }),
  });

  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Could not add application (${res.status})`);
  }

  return res.json();
}

async function fetchApplications() {
  const headers = getApiHeaders(false);
  const res = await fetch(CONFIG.API_BASE_URL + `/applications/${encodeURIComponent(currentSessionId)}`, { headers });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Could not load applications (${res.status})`);
  }
  const data = await res.json();
  return data.applications || [];
}

async function updateApplicationStatus(applicationId, status) {
  const headers = getApiHeaders(true);
  const res = await fetch(CONFIG.API_BASE_URL + `/applications/${applicationId}`, {
    method: 'PATCH',
    headers,
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Could not update status (${res.status})`);
  }
}

function openTrackerModal() {
  trackerModal?.classList.remove('hidden');
}

function closeTracker() {
  trackerModal?.classList.add('hidden');
}

async function renderTracker() {
  if (!trackerContent) return;
  trackerContent.innerHTML = '<p class="tracker-loading">Loading applications...</p>';
  try {
    const apps = await fetchApplications();
    if (apps.length === 0) {
      trackerContent.innerHTML = '<p class="tracker-empty">No applications yet. Add jobs from result cards using "Track".</p>';
      return;
    }

    const rows = apps.map(app => `
      <tr>
        <td>${esc(app.job_title || '')}</td>
        <td>${esc(app.company || '')}</td>
        <td>${esc(app.location || '')}</td>
        <td>
          <select class="tracker-status-select" data-app-id="${app.id}">
            ${['saved', 'applied', 'oa', 'interview', 'offer', 'rejected'].map(s => `<option value="${s}" ${app.status === s ? 'selected' : ''}>${s.toUpperCase()}</option>`).join('')}
          </select>
        </td>
        <td><button class="btn-secondary tracker-prep-btn" data-app-id="${app.id}">Prep</button></td>
      </tr>
    `).join('');

    trackerContent.innerHTML = `
      <div class="table-wrapper tracker-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Role</th>
              <th>Company</th>
              <th>Location</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;

    trackerContent.querySelectorAll('.tracker-status-select').forEach(sel => {
      sel.addEventListener('change', async () => {
        const appId = sel.getAttribute('data-app-id');
        try {
          await updateApplicationStatus(appId, sel.value);
        } catch (err) {
          alert(err.message || 'Failed to update application status');
        }
      });
    });

    trackerContent.querySelectorAll('.tracker-prep-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const appId = btn.getAttribute('data-app-id');
        await generateInterviewPrep(appId);
      });
    });
  } catch (err) {
    trackerContent.innerHTML = `<p class="tracker-empty">${esc(err.message || 'Could not load tracker')}</p>`;
  }
}


// ─── ALERT SUBSCRIPTION ──────────────────────────────
async function subscribeToAlerts() {
  const profile = currentProfileSnapshot || buildCurrentProfile();
  if (!profile.email) {
    alert('Add your email to subscribe for alerts.');
    return;
  }

  const headers = getApiHeaders(true);
  const res = await fetch(CONFIG.API_BASE_URL + '/alerts/subscribe', {
    method: 'POST',
    headers,
    body: JSON.stringify({
      email: profile.email,
      name: profile.name || 'Candidate',
      profile,
      frequency: 'weekly',
    }),
  });

  if (!res.ok) {
    const d = await res.json().catch(() => ({}));
    throw new Error(d.detail || `Could not subscribe (${res.status})`);
  }
}


async function generateResumeTailor(jobTitle, company, jobDescription) {
  const profile = buildCurrentProfile();
  openCoverLetterModal('Generating tailored resume content...', 'Tailored Resume');

  const headers = getApiHeaders(true);
  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/resume-tailor', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        profile,
        jobTitle,
        company,
        jobDescription: jobDescription || '',
        currentResumeText: uploadedResumeText || '',
        focusAreas: ['summary', 'impact bullets', 'ATS keywords'],
      }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    openCoverLetterModal(data.tailored_resume || 'No tailored resume content generated.', 'Tailored Resume');
  } catch (err) {
    openCoverLetterModal('Error: ' + err.message, 'Tailored Resume');
  }
}


async function generateInterviewPrep(applicationId) {
  const profile = currentProfileSnapshot || buildCurrentProfile();
  openCoverLetterModal('Generating stage-based interview prep...', 'Interview Prep');

  const headers = getApiHeaders(true);
  try {
    const res = await fetch(CONFIG.API_BASE_URL + '/interview-prep', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        application_id: Number(applicationId),
        profile,
        focus: 'high-probability interview success',
      }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const data = await res.json();
    openCoverLetterModal(data.prep || 'No interview prep generated.', `Interview Prep (${String(data.stage || '').toUpperCase()})`);
  } catch (err) {
    openCoverLetterModal('Error: ' + err.message, 'Interview Prep');
  }
}


// ─── COVER LETTER MODAL ──────────────────────────────
const coverLetterModal = document.getElementById('coverLetterModal');
const coverLetterContent = document.getElementById('coverLetterContent');
const coverLetterTitle = document.getElementById('coverLetterTitle');
const closeCoverLetter = document.getElementById('closeCoverLetter');
const closeCoverLetterBtn = document.getElementById('closeCoverLetterBtn');
const copyCoverLetter = document.getElementById('copyCoverLetter');

function openCoverLetterModal(text, title = 'Cover Letter') {
  if (coverLetterTitle) coverLetterTitle.textContent = title;
  if (coverLetterContent) coverLetterContent.textContent = text;
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

trackerBtn?.addEventListener('click', async () => {
  openTrackerModal();
  await renderTracker();
});

refreshTrackerBtn?.addEventListener('click', async () => {
  await renderTracker();
});

closeTrackerModal?.addEventListener('click', closeTracker);
closeTrackerModalBtn?.addEventListener('click', closeTracker);
trackerModal?.addEventListener('click', (e) => {
  if (e.target === trackerModal) closeTracker();
});

subscribeAlertsBtn?.addEventListener('click', async () => {
  try {
    subscribeAlertsBtn.disabled = true;
    subscribeAlertsBtn.textContent = 'Subscribing...';
    await subscribeToAlerts();
    subscribeAlertsBtn.textContent = 'Subscribed';
  } catch (err) {
    alert(err.message || 'Could not subscribe to alerts');
    subscribeAlertsBtn.textContent = 'Subscribe Alerts';
  } finally {
    setTimeout(() => {
      subscribeAlertsBtn.disabled = false;
      subscribeAlertsBtn.textContent = 'Subscribe Alerts';
    }, 2500);
  }
});

async function generateCoverLetter(jobTitle, company, jobDescription) {
  const profile = buildCurrentProfile();

  if (coverLetterContent) coverLetterContent.textContent = 'Generating cover letter...';
  if (coverLetterModal) coverLetterModal.classList.remove('hidden');

  const headers = { 'Content-Type': 'application/json' };
  if (CONFIG.API_KEY) headers['X-Api-Key'] = CONFIG.API_KEY;

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
    openCoverLetterModal(data.cover_letter || 'No cover letter generated.');
  } catch (err) {
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
  let t = text.replace(/^[-•]\s*/, '').replace(/\*\*/g, '').trim();
  t = t.replace(/^(Most important next step|Skill to highlight or develop|Question to ask recruiters?|Highlight or develop):\s*/i, '');
  return t;
}

function getBreakdownForJob(title, company) {
  return latestScoreBreakdownMap.get(normalizeRoleKey(title, company)) || null;
}


// ─── DISPLAY RESULTS ────────────────────────────────
function displayResults(payload) {
  const markdown = typeof payload === 'string' ? payload : (payload?.output || '');
  if (payload && typeof payload === 'object') {
    if (payload.sessionId) currentSessionId = payload.sessionId;
    latestTopMatches = Array.isArray(payload.topMatches) ? payload.topMatches : [];
  } else {
    latestTopMatches = [];
  }

  latestScoreBreakdownMap.clear();
  latestTopMatches.forEach(match => {
    if (match?.score_breakdown) {
      latestScoreBreakdownMap.set(
        normalizeRoleKey(match.title, match.company),
        match.score_breakdown,
      );
    }
  });

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
  if (trackerBtn) trackerBtn.style.display = '';
  if (subscribeAlertsBtn) subscribeAlertsBtn.style.display = '';
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

  if (jobs.length === 0) {
    return `<div class="result-section"><h2 class="section-heading">${esc(section.title)}</h2>${renderBasicContent(section.content)}</div>`;
  }

  let html = '<div class="matches-section">';
  html += `<div class="matches-header">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4-4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>
    <span>Top Matches</span>
    <span class="matches-count">${jobs.length} found</span>
  </div>`;

  jobs.forEach((job, idx) => { html += renderJobCard(job, idx + 1); });
  html += '</div>';
  return html;
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
  let matchScore = '', location = '', salary = '';
  const reasons = [], gaps = [], actions = [];
  let experience = '';
  let currentList = null;
  let jobDescription = '';

  for (const line of lines) {
    const raw = line.trim();
    if (!raw || raw === '---') continue;
    const clean = raw.replace(/\*\*/g, '');

    if ((clean.toLowerCase().includes('match score') || clean.toLowerCase().includes('match:')) && clean.includes('/10')) {
      const scoreM = clean.match(/(\d+)\/10/); if (scoreM) matchScore = scoreM[1];
      const locM = clean.match(/Location:\s*([^|]+)/i); if (locM) location = locM[1].trim();
      const salM = clean.match(/Salary:\s*([^|]+)/i); if (salM) salary = salM[1].trim();
      continue;
    }

    if (clean.toLowerCase().includes('action step') || clean.toLowerCase().includes('quick action') || clean.toLowerCase().includes('next step') || clean.toLowerCase().includes('recommended next')) {
      currentList = 'actions'; continue;
    }
    if (clean.toLowerCase().includes('why it match')) { currentList = 'reasons'; continue; }
    if (clean.toLowerCase().includes('gap')) {
      if (raw.startsWith('-') || raw.startsWith('•')) { gaps.push(cleanBulletText(raw)); }
      currentList = 'gaps'; continue;
    }
    if (clean.toLowerCase().startsWith('experience')) {
      experience = clean.replace(/^Experience\s*(Alignment|alignment)?:\s*/i, '').replace(/^Experience\s*/i, '').trim();
      currentList = null; continue;
    }

    if (raw.startsWith('-') || raw.startsWith('•')) {
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

    // Capture description-like content for cover letter context
    if (currentList === 'reasons' && clean.length > 20) {
      jobDescription += clean + ' ';
    }
  }

  const score = parseInt(matchScore) || 0;
  const scoreClass = score >= 8 ? 'score-high' : score >= 6 ? 'score-mid' : 'score-low';
  const bookmarkKey = jobTitle + '|' + company;

  // Build plain text for copy-to-clipboard
  let copyText = `${jobTitle}`;
  if (company) copyText += ` @ ${company}`;
  copyText += `\nMatch Score: ${matchScore}/10`;
  if (location) copyText += `\nLocation: ${location}`;
  if (salary) copyText += `\nSalary: ${salary}`;
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
  html += `<button class="card-resume-tailor-btn" title="Generate tailored resume"
    data-rt-title="${esc(jobTitle)}"
    data-rt-company="${esc(company)}"
    data-rt-desc="${esc(jobDescription.trim().slice(0, 300))}">
    Tailor Resume
  </button>`;

  html += `<button class="card-cover-letter-btn" title="Generate cover letter"
    data-cl-title="${esc(jobTitle)}"
    data-cl-company="${esc(company)}"
    data-cl-desc="${esc(jobDescription.trim().slice(0, 300))}">
    Cover Letter
  </button>`;

  html += `<button class="card-resume-btn" title="Generate tailored resume rewrite"
    data-rs-title="${esc(jobTitle)}"
    data-rs-company="${esc(company)}"
    data-rs-desc="${esc(jobDescription.trim().slice(0, 500))}">
    Resume Rewrite
  </button>`;

  html += `<button class="card-track-btn" title="Add to application tracker"
    data-track-title="${esc(jobTitle)}"
    data-track-company="${esc(company)}"
    data-track-location="${esc(location)}"
    data-track-salary="${esc(salary)}">
    Track
  </button>`;

  // Bookmark button
  html += `<button class="card-bookmark-btn ${bookmarkedJobs.has(bookmarkKey) ? 'bookmarked' : ''}" title="Bookmark this job"
    data-bookmark-title="${esc(jobTitle)}"
    data-bookmark-company="${esc(company)}"
    data-bookmark-location="${esc(location)}"
    data-bookmark-salary="${esc(salary)}"
    data-bookmark-score="${score}">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="${bookmarkedJobs.has(bookmarkKey) ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 012-2h10a2 2 0 012 2z"/></svg>
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
  if (location || salary) {
    html += '<div class="job-meta">';
    if (location) html += `<span class="meta-chip"><svg class="meta-svg" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clip-rule="evenodd"/></svg>${esc(location)}</span>`;
    if (salary) html += `<span class="meta-chip"><svg class="meta-svg" viewBox="0 0 20 20" fill="currentColor"><path d="M8.433 7.418c.155-.103.346-.196.567-.267v1.698a2.305 2.305 0 01-.567-.267C8.07 8.34 8 8.114 8 8c0-.114.07-.34.433-.582zM11 12.849v-1.698c.22.071.412.164.567.267.364.243.433.468.433.582 0 .114-.07.34-.433.582a2.305 2.305 0 01-.567.267z"/><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-13a1 1 0 10-2 0v.092a4.535 4.535 0 00-1.676.662C6.602 6.234 6 7.009 6 8c0 .99.602 1.765 1.324 2.246.48.32 1.054.545 1.676.662v1.941c-.391-.127-.68-.317-.843-.504a1 1 0 10-1.51 1.31c.562.649 1.413 1.076 2.353 1.253V15a1 1 0 102 0v-.092a4.535 4.535 0 001.676-.662C13.398 13.766 14 12.991 14 12c0-.99-.602-1.765-1.324-2.246A4.535 4.535 0 0011 9.092V7.151c.391.127.68.317.843.504a1 1 0 101.511-1.31c-.563-.649-1.413-1.076-2.354-1.253V5z" clip-rule="evenodd"/></svg>${esc(salary)}</span>`;
    html += '</div>';
  }

  const breakdown = getBreakdownForJob(jobTitle, company);
  if (breakdown && breakdown.components) {
    const componentRows = Object.entries(breakdown.components).map(([k, v]) => {
      const pct = Math.max(0, Math.min(100, Math.round((Number(v) / 30) * 100)));
      return `<div class="breakdown-row"><span>${esc(k.replace('_', ' '))}</span><div class="breakdown-track"><div class="breakdown-fill" style="width:${pct}%"></div></div><strong>${Number(v)}</strong></div>`;
    }).join('');

    html += `<div class="score-breakdown-card">
      <div class="score-breakdown-header">
        <span>Match Transparency</span>
        <span class="score-breakdown-confidence ${esc(String(breakdown.confidence || 'low'))}">${esc(String(breakdown.confidence || 'low').toUpperCase())}</span>
      </div>
      <div class="score-breakdown-overall">Overall: ${esc(String(breakdown.overall || 0))}/100</div>
      ${componentRows}
    </div>`;
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
    } else if (trimmed.startsWith('-') || trimmed.startsWith('•')) {
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
      if (e.target.closest('.card-resume-tailor-btn')) return;
      if (e.target.closest('.card-cover-letter-btn')) return;
      if (e.target.closest('.card-resume-btn')) return;
      if (e.target.closest('.card-track-btn')) return;
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
      const bookmarkKey = title + '|' + company;

      if (!bookmarkedJobs.has(bookmarkKey)) {
        await saveBookmark(title, company, location, salary, score);
        btn.classList.add('bookmarked');
        const svgPath = btn.querySelector('path');
        if (svgPath) {
          btn.querySelector('svg').setAttribute('fill', 'currentColor');
        }
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
      await generateCoverLetter(title, company, desc);
    });
  });

  document.querySelectorAll('.card-resume-tailor-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const title = btn.getAttribute('data-rt-title') || '';
      const company = btn.getAttribute('data-rt-company') || '';
      const desc = btn.getAttribute('data-rt-desc') || '';
      await generateResumeTailor(title, company, desc);
    });
  });

  // Resume rewrite buttons
  document.querySelectorAll('.card-resume-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const title = btn.getAttribute('data-rs-title') || '';
      const company = btn.getAttribute('data-rs-company') || '';
      const desc = btn.getAttribute('data-rs-desc') || '';
      await generateResumeTailor(title, company, desc);
    });
  });

  // Track buttons
  document.querySelectorAll('.card-track-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const title = btn.getAttribute('data-track-title') || '';
      const company = btn.getAttribute('data-track-company') || '';
      const location = btn.getAttribute('data-track-location') || '';
      const salary = btn.getAttribute('data-track-salary') || '';
      try {
        await addToTracker(title, company, location, salary);
        btn.textContent = 'Tracked';
        btn.disabled = true;
      } catch (err) {
        alert(err.message || 'Could not add to tracker');
      }
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
  html = html.replace(/^[\-•] (.+)$/gm, '<li>$1</li>');
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
