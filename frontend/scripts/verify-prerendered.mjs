import { readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const buildDir = resolve(scriptDir, '..', 'build');
const siteOrigin = 'https://jaspen.ai';
const sitemap = await readFile(join(buildDir, 'sitemap.xml'), 'utf8');
const routes = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => new URL(match[1]).pathname || '/');

for (const route of routes) {
  const filePath = route === '/' ? join(buildDir, 'index.html') : join(buildDir, route.slice(1), 'index.html');
  const html = await readFile(filePath, 'utf8');
  const expectedCanonical = `${siteOrigin}${route}`;
  const checks = [
    ['rendered root', /<div id="root"[^>]*data-prerendered="true"[^>]*>[\s\S]+<\/div>/i.test(html)],
    ['page title', /<title>[^<]+<\/title>/i.test(html)],
    ['meta description', /<meta[^>]+name="description"[^>]+content="[^"]+"/i.test(html)],
    ['canonical URL', html.includes(`rel="canonical" href="${expectedCanonical}"`)],
    ['browser reset', html.includes('data-prerender-reset')],
  ];
  const failures = checks.filter(([, passed]) => !passed).map(([label]) => label);
  if (failures.length) throw new Error(`${route}: missing ${failures.join(', ')}`);
}

console.log(`Verified crawler-readable HTML for ${routes.length} public routes.`);
