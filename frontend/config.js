// JobMatch AI - Runtime Configuration
// The frontend is deployed on Vercel and points to the hosted backend by default.
const DEFAULT_API_BASE_URL = 'https://job-rag-production.up.railway.app';

const CONFIG = {
  API_BASE_URL: window.JOBMATCH_API_URL || DEFAULT_API_BASE_URL,
  API_KEY: (typeof __JOBMATCH_API_KEY__ !== 'undefined' && __JOBMATCH_API_KEY__ !== '__JOBMATCH_API_KEY__')
    ? __JOBMATCH_API_KEY__
    : (window.JOBMATCH_API_KEY || ''),
  GOOGLE_CLIENT_ID: (typeof __GOOGLE_CLIENT_ID__ !== 'undefined' && __GOOGLE_CLIENT_ID__ !== '__GOOGLE_CLIENT_ID__')
    ? __GOOGLE_CLIENT_ID__
    : (window.GOOGLE_CLIENT_ID || ''),
};
