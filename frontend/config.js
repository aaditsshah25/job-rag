// JobMatch AI — Runtime Configuration
// Vercel injects NEXT_PUBLIC_* vars at build time via vercel.json env.
// For local dev, values fall back to localhost defaults.
const CONFIG = {
  API_BASE_URL: (typeof __JOBMATCH_API_URL__ !== 'undefined' && __JOBMATCH_API_URL__ !== '__JOBMATCH_API_URL__')
    ? __JOBMATCH_API_URL__
    : (window.JOBMATCH_API_URL || (window.location.protocol === 'file:' ? 'http://localhost:8000' : window.location.origin)),
  API_KEY: (typeof __JOBMATCH_API_KEY__ !== 'undefined' && __JOBMATCH_API_KEY__ !== '__JOBMATCH_API_KEY__')
    ? __JOBMATCH_API_KEY__
    : (window.JOBMATCH_API_KEY || ''),
  GOOGLE_CLIENT_ID: (typeof __GOOGLE_CLIENT_ID__ !== 'undefined' && __GOOGLE_CLIENT_ID__ !== '__GOOGLE_CLIENT_ID__')
    ? __GOOGLE_CLIENT_ID__
    : (window.GOOGLE_CLIENT_ID || ''),
};
