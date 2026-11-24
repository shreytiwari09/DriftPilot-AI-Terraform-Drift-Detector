// Copies the production build (dist/) into the Python package, so users never need Node:
// driftpilot/report/dashboard/app/. `driftpilot report --html` and the dashboard publisher read it.
import { cpSync, existsSync, rmSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const dist = resolve(here, '../dist');
const target = resolve(here, '../../driftpilot/report/dashboard/app');
if (!existsSync(resolve(dist, 'index.html'))) throw new Error('dist/index.html is missing: run `npm run build` first');
rmSync(target, { recursive: true, force: true });
cpSync(dist, target, { recursive: true });
console.log(`copied ${dist} -> ${target}`);
