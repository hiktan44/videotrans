import { DatabaseSync } from 'node:sqlite';
import { createHash, randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync, renameSync, chmodSync, unlinkSync } from 'node:fs';
import { join } from 'node:path';

const hourMs = 3600000;
const dayMs = 24 * hourMs;
const bucketMs = 5 * 60000;
const offset = 3 * hourMs;
export const localDay = time => new Date(time + offset).toISOString().slice(0,10);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const iso = time => new Date(time).toISOString();

export function openCounter({ root, appId, origin, clock=Date.now }) {
  const privateDir = join(root,'private'), outDir=join(root,'out');
  mkdirSync(privateDir,{mode:0o700,recursive:true});
  mkdirSync(outDir,{mode:0o750,recursive:true});
  const file=join(privateDir,'visits.sqlite');
  const db=new DatabaseSync(file);
  chmodSync(file,0o600);
  db.exec(`PRAGMA secure_delete=ON;
    PRAGMA busy_timeout=5000;
    CREATE TABLE IF NOT EXISTS site_scope(singleton INTEGER PRIMARY KEY CHECK(singleton=1),app TEXT NOT NULL,origin TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS installation(singleton INTEGER PRIMARY KEY CHECK(singleton=1), started INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS day_seen(day TEXT NOT NULL,digest TEXT NOT NULL,PRIMARY KEY(day,digest)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS counts(day TEXT NOT NULL,bucket INTEGER NOT NULL,n INTEGER NOT NULL,PRIMARY KEY(day,bucket)) WITHOUT ROWID;`);
  db.prepare('INSERT OR IGNORE INTO site_scope VALUES(1,?,?)').run(appId,origin);
  const scope=db.prepare('SELECT app,origin FROM site_scope WHERE singleton=1').get();
  if(scope.app!==appId || scope.origin!==origin){db.close();throw Error('site_volume_scope_mismatch');}
  db.prepare('INSERT OR IGNORE INTO installation VALUES(1,?)').run(clock());
  const installedAt=db.prepare('SELECT started FROM installation WHERE singleton=1').get().started;
  const insert=db.prepare('INSERT OR IGNORE INTO day_seen VALUES(?,?)');
  const add=db.prepare('INSERT INTO counts VALUES(?,?,1) ON CONFLICT(day,bucket) DO UPDATE SET n=n+1');
  const expireSeen=db.prepare('DELETE FROM day_seen WHERE day < ?');
  const expireCounts=db.prepare('DELETE FROM counts WHERE day < ?');
  let lastPrune;
  function prune(now) {
    const day=localDay(now);
    if(lastPrune===day)return;
    expireSeen.run(day);
    expireCounts.run(localDay(now-7*dayMs));
    lastPrune=day;
  }
  function record(day,id,now) {
    if(now<installedAt || day!==localDay(now) || typeof id!=='string' || !uuid.test(id)) return false;
    prune(now);
    const digest=createHash('sha256').update(origin+'|'+day+'|'+id.toLowerCase()).digest('hex');
    db.exec('BEGIN IMMEDIATE');
    try {
      if(insert.run(day,digest).changes) add.run(day,Math.floor((now+offset)/bucketMs)%288);
      db.exec('COMMIT');
    } catch(error) {db.exec('ROLLBACK');throw error;}
    return true;
  }
  function snapshot(now) {
    prune(now);
    const windows=[];
    function window(from,to,value) {
      if(value<=0 || from>=to)return;
      windows.push({period:{start:iso(from),end:iso(to),timezone:'Europe/Istanbul',bounds:'[start,end)'},
        allBrowsers:{identity:'first-party-browser-id',ownerScope:'unresolved',status:'partial',value}});
    }
    // Each browser contributes once to its first observed hour in the local day.
    // A partial window never includes a count from an hour outside that window.
    const days=new Map();
    const cutoff=Math.floor(now/bucketMs)*bucketMs;
    const bucket=Math.floor((cutoff+offset)/bucketMs)%288;
    const groups=db.prepare(`SELECT day, CAST(bucket/12 AS INTEGER) AS hour, SUM(n) AS n FROM counts
      WHERE day < ? OR (day=? AND bucket < ?) GROUP BY day, hour ORDER BY day,hour`).all(localDay(cutoff),localDay(cutoff),bucket);
    for(const row of groups) {
      if(!days.has(row.day))days.set(row.day,new Map());
      days.get(row.day).set(row.hour,row.n);
    }
    for(const [day,counts] of days) {
      const begin=Date.parse(day+'T00:00:00+03:00'), end=Math.min(cutoff,begin+dayMs);
      if(end<=begin)continue;
      const intervals=new Map();
      function put(from,to,n) {
        const actualFrom=Math.max(installedAt,from);
        if(actualFrom<to && n>0)intervals.set(actualFrom+'/'+to,[actualFrom,to,n]);
      }
      let total=0;
      for(let h=0;h<24 && begin+h*hourMs<end;h++){
        const from=begin+h*hourMs,to=Math.min(end,from+hourMs),n=counts.get(h)||0;
        total+=n;
        put(from,to,n);
        put(begin,to,total);
      }
      // Suffixes make late report starts measurable without adding across days.
      let suffix=0;
      for(let h=23;h>=0;h--){
        const from=begin+h*hourMs;
        if(from>=end)continue;
        suffix+=counts.get(h)||0;
        put(from,end,suffix);
      }
      for(const [from,to,n] of intervals.values())window(from,to,n);
    }
    return {schemaVersion:1,appId,method:'first-party-page-view',dedup:'distinct-in-period',botsExcluded:true,windows};
  }
  function exportSnapshot(now) {
    const temp=join(outDir,'.website-visitors-'+randomUUID()+'.tmp');
    try {
      writeFileSync(temp,JSON.stringify(snapshot(now))+'\n',{mode:0o640,flag:'wx'});
      renameSync(temp,join(outDir,'website-visitors.json'));
    } finally {
      try {unlinkSync(temp);} catch(error) {if(error.code!=='ENOENT')throw error;}
    }
  }
  return { record, snapshot, exportSnapshot, close:()=>db.close() };
}
