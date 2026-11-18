import { defineConfig, build } from 'vite';
import { resolve } from 'node:path';
import { copyFileSync, mkdirSync, existsSync, readFileSync, writeFileSync, rmSync, cpSync } from 'node:fs';

/**
 * Custom Vite plugin to copy extension manifest and compile standalone IIFE content script.
 */
function extensionManifestPlugin() {
  return {
    name: 'copy-extension-manifest',
    async closeBundle() {
      const srcManifest = resolve(__dirname, 'src/extension/manifest.json');
      const distManifest = resolve(__dirname, 'dist/manifest.json');
      mkdirSync(resolve(__dirname, 'dist'), { recursive: true });
      if (existsSync(srcManifest)) {
        copyFileSync(srcManifest, distManifest);
      }

      const srcFontsDir = resolve(__dirname, 'src/extension/assets/fonts');
      const distFontsDir = resolve(__dirname, 'dist/assets/fonts');
      if (existsSync(srcFontsDir)) {
        mkdirSync(distFontsDir, { recursive: true });
        cpSync(srcFontsDir, distFontsDir, { recursive: true });
      }

      const srcMascotDir = resolve(__dirname, 'src/extension/assets/mascot');
      const distMascotDir = resolve(__dirname, 'dist/assets/mascot');
      if (existsSync(srcMascotDir)) {
        mkdirSync(distMascotDir, { recursive: true });
        cpSync(srcMascotDir, distMascotDir, { recursive: true });
      }

      const nestedPopup = resolve(__dirname, 'dist/src/extension/popup/popup.html');
      const targetPopupDir = resolve(__dirname, 'dist/popup');
      const targetPopup = resolve(targetPopupDir, 'popup.html');
      if (existsSync(nestedPopup)) {
        mkdirSync(targetPopupDir, { recursive: true });
        const html = readFileSync(nestedPopup, 'utf-8');
        writeFileSync(targetPopup, html);
        rmSync(resolve(__dirname, 'dist/src'), { recursive: true, force: true });
      }

      // Build content script as a standalone IIFE bundle (Manifest V3 content scripts require classic non-module JS)
      await build({
        configFile: false,
        build: {
          outDir: resolve(__dirname, 'dist/content'),
          emptyOutDir: false,
          target: 'es2022',
          lib: {
            entry: resolve(__dirname, 'src/extension/content/content_script.ts'),
            name: 'InkShiftContentScript',
            formats: ['iife'],
            fileName: () => 'content_script.js',
          },
        },
      });
    },
  };
}

export default defineConfig({
  plugins: [extensionManifestPlugin()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2022',
    rollupOptions: {
      input: {
        'background/service_worker': resolve(__dirname, 'src/extension/background/service_worker.ts'),
        'popup/popup': resolve(__dirname, 'src/extension/popup/popup.html'),
      },
      output: {
        entryFileNames: '[name].js',
        chunkFileNames: 'chunks/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            return 'popup/[name][extname]';
          }
          return 'assets/[name][extname]';
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'node',
  },
});
