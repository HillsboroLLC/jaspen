import { createServer } from 'node:http';
import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { dirname, extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import puppeteer from 'puppeteer';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptDir, '..');
const buildDir = join(frontendDir, 'build');
const sitemapPath = join(buildDir, 'sitemap.xml');
const siteOrigin = 'https://jaspen.ai';

const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.ico': 'image/x-icon',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.webmanifest': 'application/manifest+json',
  '.xml': 'application/xml; charset=utf-8',
};

function sitemapRoutes(xml) {
  const locations = [...xml.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1].trim());
  const routes = locations.map((location) => {
    const url = new URL(location);
    if (url.origin !== siteOrigin) {
      throw new Error(`Sitemap URL is outside ${siteOrigin}: ${location}`);
    }
    return url.pathname || '/';
  });

  if (!routes.length) throw new Error('No public routes were found in sitemap.xml.');
  return [...new Set(routes)];
}

async function existingFile(pathname) {
  try {
    const details = await stat(pathname);
    return details.isFile() ? pathname : null;
  } catch {
    return null;
  }
}

async function resolveBuildAsset(requestPath) {
  const decodedPath = decodeURIComponent(requestPath.split('?')[0]);
  const relativePath = normalize(decodedPath).replace(/^[/\\]+/, '');
  const requested = resolve(buildDir, relativePath);
  if (!requested.startsWith(`${buildDir}/`) && requested !== buildDir) return null;

  return (
    (await existingFile(requested)) ||
    (await existingFile(join(requested, 'index.html'))) ||
    join(buildDir, 'index.html')
  );
}

async function startBuildServer() {
  const server = createServer(async (request, response) => {
    try {
      const filePath = await resolveBuildAsset(request.url || '/');
      if (!filePath) {
        response.writeHead(403).end('Forbidden');
        return;
      }
      const body = await readFile(filePath);
      response.writeHead(200, {
        'Cache-Control': 'no-store',
        'Content-Type': mimeTypes[extname(filePath)] || 'application/octet-stream',
      });
      response.end(body);
    } catch (error) {
      response.writeHead(500).end(error.message);
    }
  });

  await new Promise((resolvePromise, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolvePromise);
  });
  const address = server.address();
  return { server, origin: `http://127.0.0.1:${address.port}` };
}

function snapshotPath(route) {
  return route === '/' ? join(buildDir, 'index.html') : join(buildDir, route.slice(1), 'index.html');
}

async function renderRoute(page, origin, route) {
  await page.goto(`${origin}${route}`, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  await page.waitForFunction(
    () => {
      const root = document.getElementById('root');
      return root && root.innerText.replace(/\s+/g, ' ').trim().length >= 80;
    },
    { timeout: 30_000 },
  );
  await new Promise((resolvePromise) => setTimeout(resolvePromise, 700));

  const pageDetails = await page.evaluate(() => {
    const root = document.getElementById('root');
    root.dataset.prerendered = 'true';
    return {
      canonical: document.querySelector('link[rel="canonical"]')?.href || '',
      description: document.querySelector('meta[name="description"]')?.content || '',
      textLength: root.innerText.replace(/\s+/g, ' ').trim().length,
      title: document.title,
    };
  });

  const expectedCanonical = `${siteOrigin}${route}`;
  if (pageDetails.canonical !== expectedCanonical) {
    throw new Error(`${route}: expected canonical ${expectedCanonical}, found ${pageDetails.canonical || 'none'}`);
  }
  if (!pageDetails.title || !pageDetails.description || pageDetails.textLength < 80) {
    throw new Error(`${route}: rendered snapshot is missing title, description, or meaningful page content.`);
  }

  const html = await page.content();
  const outputPath = snapshotPath(route);
  await mkdir(dirname(outputPath), { recursive: true });
  await writeFile(outputPath, html);
  return pageDetails;
}

const sitemap = await readFile(sitemapPath, 'utf8');
const routes = sitemapRoutes(sitemap);
const { server, origin } = await startBuildServer();
const browser = await puppeteer.launch({ headless: true });

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
  await page.setRequestInterception(true);
  page.on('request', (request) => {
    const requestUrl = request.url();
    const resourceType = request.resourceType();
    if (requestUrl.startsWith(origin) && !['fetch', 'xhr', 'websocket'].includes(resourceType)) {
      request.continue();
    } else {
      request.abort();
    }
  });

  for (const route of routes) {
    const details = await renderRoute(page, origin, route);
    console.log(`Prerendered ${route} (${details.textLength.toLocaleString()} characters)`);
  }
} finally {
  await browser.close();
  await new Promise((resolvePromise) => server.close(resolvePromise));
}

console.log(`Prerendered ${routes.length} public routes from sitemap.xml.`);
