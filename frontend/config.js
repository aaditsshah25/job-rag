// JobMatch AI - Runtime Configuration
// Vercel injects NEXT_PUBLIC_* vars at build time via vercel.json env.
// For local dev, default to local backend.
const IS_LOCAL_HOST = ['localhost', '127.0.0.1'].includes(window.location.hostname);
const DEFAULT_API_BASE_URL = IS_LOCAL_HOST
  ? 'http://127.0.0.1:8000'
  : 'https://job-rag-production.up.railway.app';

const CONFIG = {
  API_BASE_URL: window.JOBMATCH_API_URL || DEFAULT_API_BASE_URL,
  API_KEY: (typeof __JOBMATCH_API_KEY__ !== 'undefined' && __JOBMATCH_API_KEY__ !== '__JOBMATCH_API_KEY__')
    ? __JOBMATCH_API_KEY__
    : (window.JOBMATCH_API_KEY || ''),
  GOOGLE_CLIENT_ID: (typeof __GOOGLE_CLIENT_ID__ !== 'undefined' && __GOOGLE_CLIENT_ID__ !== '__GOOGLE_CLIENT_ID__')
    ? __GOOGLE_CLIENT_ID__
    : (window.GOOGLE_CLIENT_ID || ''),
};
