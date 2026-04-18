import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';
import fs from 'fs';

function sanitizeEnv(value, fallback = '') {
  return String(value ?? fallback).trim();
}

function escapeJsString(value) {
  return value.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
}

function writeLegacyRuntimeConfig(dest) {
  const apiUrl = sanitizeEnv(process.env.JOBMATCH_API_URL, process.env.VITE_API_BASE_URL || 'https://job-rag-production.up.railway.app');
  const apiKey = sanitizeEnv(process.env.JOBMATCH_API_KEY, '');
  const googleClientId = sanitizeEnv(process.env.GOOGLE_CLIENT_ID, '');

  const configContent = `// JobMatch AI - Runtime Configuration (generated at build time)\nconst CONFIG = {\n  API_BASE_URL: '${escapeJsString(apiUrl)}',\n  API_KEY: '${escapeJsString(apiKey)}',\n  GOOGLE_CLIENT_ID: '${escapeJsString(googleClientId)}',\n};\n`;

  fs.writeFileSync(resolve(dest, 'config.js'), configContent, 'utf8');
}

// Plugin to copy the static HTML app into dist/app after build
function copyHtmlApp() {
  return {
    name: 'copy-html-app',
    closeBundle() {
      const src = resolve(__dirname, '../frontend');
      const dest = resolve(__dirname, 'dist/app');
      copyDir(src, dest);
      writeLegacyRuntimeConfig(dest);
    },
  };
}

function copyDir(src, dest) {
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src)) {
    // skip vercel.json, build.sh, node_modules
    if (['vercel.json', 'build.sh', 'node_modules', '.vercel'].includes(entry)) continue;
    const srcPath = resolve(src, entry);
    const destPath = resolve(dest, entry);
    if (fs.statSync(srcPath).isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

export default defineConfig({
  plugins: [react(), copyHtmlApp()],
  server: {
    port: 5173,
    host: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
