// Copies only what the app loads (index.html, its CSS and scripts, the modules they import, assets/)
// into web-dist/, which tauri.conf.json bundles. Tests, mocks and screenshot tools stay out of the build.
// Run by `tauri build` (beforeBuildCommand); also safe to run by hand: bun scripts/stage-frontend.mjs
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const src = join(app, 'src');
const out = join(app, 'web-dist');

const files = new Set(['index.html']);
const html = readFileSync(join(src, 'index.html'), 'utf8');
for (const [, url] of html.matchAll(/\b(?:href|src)="([^"#:]+\.(?:css|js))"/g)) files.add(url);

// Follow static imports so every module main.js needs is shipped. Dynamic imports (the browser-only
// mock) are left out on purpose.
const queue = [...files].filter(file => file.endsWith('.js'));
while (queue.length) {
  const file = queue.pop();
  for (const [, url] of readFileSync(join(src, file), 'utf8').matchAll(/^\s*import\s[^'"]*['"]\.\/([^'"]+)['"]/gm)) {
    if (!files.has(url)) { files.add(url); queue.push(url); }
  }
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
for (const file of files) {
  if (!existsSync(join(src, file))) throw new Error(`index.html or an import names a missing file: ${file}`);
  cpSync(join(src, file), join(out, file));
}
cpSync(join(src, 'assets'), join(out, 'assets'), { recursive: true });
console.log(`Staged ${files.size} files + assets/ into web-dist/`);
