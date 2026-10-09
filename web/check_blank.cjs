const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('console', msg => errors.push({type: msg.type(), text: msg.text()}));
  page.on('pageerror', err => errors.push({type: 'pageerror', text: err.message}));
  
  await page.goto('http://localhost:3000', { waitUntil: 'networkidle', timeout: 15000 });
  await page.waitForTimeout(4000);
  
  const info = await page.evaluate(() => {
    const app = document.getElementById('app');
    const loading = document.getElementById('app-loading');
    return {
      appHTML: app ? app.innerHTML.substring(0, 300) : 'no #app',
      appChildren: app ? app.childElementCount : -1,
      loadingExists: !!loading,
      bodyHTML: document.body.innerHTML.substring(0, 300)
    };
  });
  
  console.log(JSON.stringify({errors, info}, null, 2));
  await browser.close();
})().catch(e => console.error('ERROR:', e.message));
