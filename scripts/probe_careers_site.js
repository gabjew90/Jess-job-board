#!/usr/bin/env node
// Find the JSON endpoint behind a JavaScript-rendered careers page.
//
// Loads the page in headless Chromium, lets it render, then prints every
// job-looking link plus every API-shaped response the page fetched (URL,
// status, first bytes of the body, POST payload). The JSON call that carries
// the postings is the endpoint a plain-`requests` fetcher can use — see
// src/sources/career_sites.py for the four vendor platforms found this way.
//
// Usage:  NODE_PATH="$(npm root -g)" node scripts/probe_careers_site.js <url> [url...]
// Needs:  npm i -g playwright && npx playwright install chromium
//         (NODE_PATH lets require() see the global install; a local
//         `npm i playwright` needs no NODE_PATH)
//
// Requests are served through Playwright's Node fetch stack (route.fetch)
// rather than Chromium's own network stack, so the probe also works behind
// TLS-intercepting corporate/CI proxies that Chromium's TLS stack rejects.
const { chromium } = require('playwright');

const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
  + '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36';
const NOISE = /fonts\.|\.css|\.js\b|\.png|\.svg|\.woff|cookie|consent|onetrust|gtm|analytics|doubleclick|linkedin|facebook|hotjar|clarity|nr-data|recaptcha|gstatic|youtube|visualstudio/i;

async function probe(browser, url) {
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined;
  const ctx = await browser.newContext({ userAgent: UA, proxy, locale: 'en-US' });
  const page = await ctx.newPage();
  const hits = [];
  await page.route('**/*', async (route) => {
    const req = route.request();
    try {
      const r = await route.fetch({ maxRedirects: 10 });
      const ct = r.headers()['content-type'] || '';
      if ((ct.includes('json') || /graphql|api|search|jobs|postings|requisition/i.test(r.url()))
          && !NOISE.test(r.url())) {
        let body = '';
        try { body = await r.text(); } catch {}
        hits.push({ method: req.method(), status: r.status(), url: r.url(), len: body.length,
          body: body.slice(0, 200).replace(/\s+/g, ' '), post: (req.postData() || '').slice(0, 300) });
      }
      await route.fulfill({ response: r });
    } catch (e) {
      hits.push({ method: req.method(), status: 'ERR', url: req.url(), err: e.message.split('\n')[0] });
      await route.abort().catch(() => {});
    }
  });
  let status;
  try {
    const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    status = resp ? resp.status() : 'null';
    await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(3000);
  } catch (e) { status = 'ERR ' + e.message.split('\n')[0]; }
  const info = await page.evaluate(() => {
    const links = [...document.querySelectorAll('a[href]')]
      .map(a => ({ href: a.href, text: (a.innerText || '').trim().slice(0, 80) }))
      .filter(l => /job|position|opening|requisition|req/i.test(l.href) && l.text.length > 3);
    return { title: document.title, finalUrl: location.href, links: links.slice(0, 40),
      text: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').slice(0, 300) };
  }).catch(e => ({ err: e.message }));
  console.log(`\n===== ${url}\n  status=${status} final=${info.finalUrl}\n  title=${info.title}\n  text: ${info.text}`);
  console.log(`  job-looking links (${info.links?.length || 0}):`);
  for (const l of info.links || []) console.log(`   - ${l.text} -> ${l.href}`);
  console.log(`  API-shaped responses (${hits.length}):`);
  for (const h of hits) {
    console.log(`   * ${h.method} ${h.status} len=${h.len || 0} ${h.url}`);
    if (h.body) console.log(`       ${h.body}`);
    if (h.post) console.log(`       POST: ${h.post}`);
    if (h.err) console.log(`       ${h.err}`);
  }
  await ctx.close();
}

(async () => {
  const urls = process.argv.slice(2);
  if (!urls.length) { console.error('usage: probe_careers_site.js <url> [url...]'); process.exit(2); }
  const proxy = process.env.HTTPS_PROXY ? { server: process.env.HTTPS_PROXY } : undefined;
  const browser = await chromium.launch({ headless: true, proxy });
  for (const u of urls) await probe(browser, u);
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
