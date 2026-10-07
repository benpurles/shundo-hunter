const {test} = require('node:test');
const assert = require('node:assert/strict');
const plan = require('../web/hunt-setup.js');
const ready = () => ({huntState:'idle',huntWorkerAlive:false,phoneConnected:true,
  overnightActive:true,overnightMacAwake:true,overnightState:'setup',overnightSecondsRemaining:40000,
  ipogoPrepared:true,ipogoSpawnRuntimeVerified:true,visionConfigured:true,
  notificationWatcherState:'listening',notificationWatcher:{alertSource:'direct',huntReady:true,unattendedReady:false}});
test('overnight requires every readiness gate, not just a saved API key', () => {
  const cases = [
    [{phoneConnected:false},'connection'],
    [{overnightActive:false,ipogoPrepared:true},'unprepare'],
    [{overnightMacAwake:false},'manage'],
    [{overnightState:'attention'},'manage'],
    [{overnightSecondsRemaining:0},'manage'],
    [{visionConfigured:false},'ai'],
    [{ipogoPrepared:false},'prepare'],
    [{ipogoSpawnRuntimeVerified:false},'prepare'],
    [{notificationWatcher:{alertSource:'mac',unattendedReady:true}},'prepare'],
    [{notificationWatcher:{alertSource:'direct',huntReady:false,unattendedReady:false}},'prepare'],
    [{notificationWatcherState:'error'},'prepare'],
    [{},'start']
  ];
  for (const [patch, action] of cases) assert.equal(plan({...ready(),...patch},'overnight',true,true).action,action);
});
test('device attestation never starts setup by itself', () => {
  const s={...ready(),overnightActive:false,ipogoPrepared:false};
  assert.equal(plan(s,'overnight',false,true).action,null);
  assert.equal(plan(s,'overnight',true,true).action,'setup');
  assert.equal(s.overnightActive,false);
});
test('no queue means no start',()=>assert.equal(plan(ready(),'overnight',true,false).action,'feed'));
test('manual pause, running worker and protected Shundo never offer automated restart',()=>{
  for (const patch of [{huntState:'paused'},{huntState:'running'},{huntWorkerAlive:true},{encounterProtected:true},{huntState:'shundo'}]) {
    assert.ok(['timeline','manage'].includes(plan({...ready(),...patch},'overnight',true,true).action));
  }
});
test('error and offline are explicit, not disabled mystery buttons',()=>{
  assert.equal(plan(null,'overnight',true,true).action,null);
  assert.equal(plan({...ready(),huntState:'error'},'overnight',true,true).action,'unprepare');
});
test('casual selection cannot silently release overnight mode',()=>assert.equal(plan(ready(),'casual',true,true).action,'manage'));
test('casual does not require AI but needs its real alert proof',()=>{
  const s={...ready(),overnightActive:false,visionConfigured:false,notificationWatcher:{alertSource:'mac',unattendedReady:true}};
  assert.equal(plan(s,'casual',false,true).action,'start');
  s.notificationWatcher.unattendedReady=false;
  assert.equal(plan(s,'casual',false,true).action,'proof');
});
test('ending overnight guides user out of the direct source explicitly',()=>{
  const s={...ready(),overnightActive:false};
  assert.equal(plan(s,'casual',false,true).action,'unprepare');
  s.ipogoPrepared=false;
  assert.equal(plan(s,'casual',false,true).action,'source-mac');
});
