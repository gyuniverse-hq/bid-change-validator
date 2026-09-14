// Dedicated local evaluation origin; does not edit project .env or hosting config.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from '../apps/web/node_modules/vite/dist/node/index.js';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../apps/web');
process.chdir(root);
process.env.NEXT_PUBLIC_API_BASE_URL = 'http://127.0.0.1:18123';
process.env.WRANGLER_SEND_METRICS = 'false';
process.env.WRANGLER_WRITE_LOGS = 'false';
process.env.MINIFLARE_REGISTRY_PATH = path.resolve('../../.ci-results/isolated-browser/ui-registry');
const server = await createServer({root, cacheDir:path.resolve('node_modules/.vite-isolated-browser'),
  server:{host:'127.0.0.1', port:5179, strictPort:true}});
await server.listen();
server.printUrls();
