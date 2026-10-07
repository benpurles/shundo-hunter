// Isolated browser harness. All browser traffic is fulfilled locally; POSTs
// are recorded as assertions and NEVER forwarded to the live phone/backend.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const root = path.resolve(__dirname,'../web');
  const fixtures = {};
  for (const route of ['/api/status','/api/sightings?limit=250','/api/queue?limit=250','/api/channels','/api/events','/api/stats','/api/preferences']) {
    fixtures[route] = await (await fetch('http://127.0.0.1:8765'+route)).json();
  }
  let status = {...fixtures['/api/status'],instanceToken:'isolated-test-token',huntState:'idle',huntWorkerAlive:false,
    currentTarget:null,ipogoPrepared:false,overnightActive:false,encounterProtected:false,
    visionBusy:false,screenRecoveryBusy:false,phoneConnected:true,visionConfigured:true,
    notificationWatcherState:'stopped',notificationWatcher:{alertSource:'mac',unattendedReady:false}};
  const posts = [], errors = [];
  const browser = await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url()), key = url.pathname+url.search;
      if (route.request().method() !== 'GET') {
        posts.push({path:url.pathname,body:route.request().postDataJSON()});
        return route.fulfill({json:{status}});
      }
      if (key === '/api/status') return route.fulfill({json:status});
      if (key in fixtures) return route.fulfill({json:fixtures[key]});
      const file = path.join(root,url.pathname === '/' ? 'index.html' : url.pathname);
      if (file.startsWith(root+path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) {
        return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
      }
      return route.fulfill({status:404,body:''});
    });
    await page.goto('http://hunter-ui.test/');
    await page.getByRole('button',{name:'☾ Overnight hunt',exact:false}).click();
    await page.waitForFunction(()=>document.querySelector('#night-next-title').textContent.includes('Get your devices ready'));
    assert.equal(posts.length,0,'Choosing mode must not send actions');
    assert.equal(await page.locator('#night-next-button').isDisabled(),true);
    const ids = await page.locator('[id]').evaluateAll(nodes=>nodes.map(n=>n.id));
    assert.equal(ids.length,new Set(ids).size,'No duplicate IDs after moving settings');
    await page.screenshot({path:'build/overnight-ui-setup.png',fullPage:true});
    await page.locator('#overnight-autolock').check();
    assert.match(await page.locator('#night-next-button').textContent(),/Set up overnight/);
    await page.locator('#night-next-button').click();
    assert.equal(posts.at(-1).body.action,'setup');
    assert.equal(posts.at(-1).body.autoLockConfirmed,true);
    const poll = async () => { await page.evaluate(()=>refresh()); await page.waitForTimeout(100); };
    status={...status,overnightActive:true,overnightMacAwake:true,overnightSecondsRemaining:43000,overnightState:'setup',visionConfigured:false};
    await poll();
    await page.locator('#night-next-button').click();
    assert.equal(await page.locator('#overnight-ai-settings').getAttribute('open'),'');
    assert.equal(posts.length,1,'Review AI must not grant consent or send an image');
    status.visionConfigured=true; await poll();
    assert.match(await page.locator('#night-next-button').textContent(),/Prepare phone/);
    await page.locator('#night-next-button').click();
    assert.equal(posts.at(-1).body.action,'prepare');
    status.ipogoPrepared=true;status.ipogoSpawnRuntimeVerified=true;await poll();
    assert.match(await page.locator('#night-next-button').textContent(),/Recheck phone reader/);
    assert.equal(posts.filter(p=>p.body.action==='start').length,0,'No automatic hunt start');
    status.notificationWatcherState='listening';
    status.notificationWatcher={alertSource:'direct',huntReady:true,unattendedReady:false};
    fixtures['/api/sightings?limit=250']={sightings:[{id:123,species:'Bulbasaur',status:'queued',cp:750,level:30,latitude:40,longitude:-111,received_at:new Date().toISOString()}]};
    fixtures['/api/queue?limit=250']={sightings:[]};
    await poll();
    await page.locator('#overnight-ai-settings').evaluate(el=>el.open=false);
    await page.screenshot({path:'build/overnight-ui-ready.png',fullPage:true});
    assert.match(await page.locator('#night-next-button').textContent(),/Start overnight hunt/);
    await page.locator('#night-next-button').click();
    assert.equal(posts.at(-1).body.action,'start');
    status.encounterProtected=true;status.huntState='shundo';await poll();
    assert.match(await page.locator('#night-next-title').textContent(),/Shundo found/);
    assert.equal(await page.locator('#start-button').isDisabled(),true);
    assert.equal(await page.locator('#overnight-real-location').isDisabled(),true);
    await page.locator('#night-back').click();
    await page.locator('#mode-casual').click();
    assert.equal(posts.filter(p=>p.body.action==='release').length,0,'Switching modes cannot release protection');
    await page.setViewportSize({width:900,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth > innerWidth),false,'No horizontal page overflow');
    await page.screenshot({path:'build/overnight-ui-narrow.png',fullPage:true});
    assert.deepEqual(errors,[]);
    console.log('PASS: isolated UI workflow, mode selection, readiness, explicit start, protected encounter, narrow layout. No live POST requests.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
