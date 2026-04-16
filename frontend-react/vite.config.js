import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';
import fs from 'fs';

// Plugin to copy the static HTML app into dist/app after build
function copyHtmlApp() {
  return {
    name: 'copy-html-app',
    closeBundle() {
      const src = resolve(__dirname, '../Aadit_Ananya_RAG/rag/frontend');
      const dest = resolve(__dirname, 'dist/app');
      copyDir(src, dest);
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
