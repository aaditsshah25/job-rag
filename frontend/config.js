// JobMatch AI - Runtime Configuration
// Backend and frontend are co-deployed on Vercel — use relative URLs.
const DEFAULT_API_BASE_URL = '';

const CONFIG = {
  API_BASE_URL: window.JOBMATCH_API_URL || DEFAULT_API_BASE_URL,
  API_KEY: (typeof __JOBMATCH_API_KEY__ !== 'undefined' && __JOBMATCH_API_KEY__ !== '__JOBMATCH_API_KEY__')
    ? __JOBMATCH_API_KEY__
    : (window.JOBMATCH_API_KEY || 'jobmatch-secret-2024'),
  GOOGLE_CLIENT_ID: (typeof __GOOGLE_CLIENT_ID__ !== 'undefined' && __GOOGLE_CLIENT_ID__ !== '__GOOGLE_CLIENT_ID__')
    ? __GOOGLE_CLIENT_ID__
    : (window.GOOGLE_CLIENT_ID || ''),
};
