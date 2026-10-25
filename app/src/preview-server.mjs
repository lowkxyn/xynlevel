// Local, offline preview. Stop with Ctrl+C. No desktop bridge is loaded.
import { resolve, dirname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const server = Bun.serve({
  hostname: '127.0.0.1', port: Number(process.argv[2] || 4173),
  async fetch(request) {
    const url = new URL(request.url);
    const path = resolve(root, `.${decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname)}`);
    if (!path.startsWith(root + sep)) return new Response('', { status: 403 });
    const file = Bun.file(path);
    return await file.exists() ? new Response(file) : new Response('', { status: 404 });
  },
});
console.log(`Gravity Well preview: http://127.0.0.1:${server.port}/index.html?mock`);
