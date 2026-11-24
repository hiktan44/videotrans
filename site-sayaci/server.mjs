import { createServer } from 'node:http';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { isAbsolute, resolve } from 'node:path';
import { openCounter } from './counter.mjs';

const clientPath='/.well-known/site-visits/client.mjs';
const pagePath='/.well-known/site-visits/page';
const client=readFileSync(new URL('./public/client.mjs',import.meta.url));
const automated=/bot|crawler|spider|headless|health.?check|uptime|monitor|curl|wget|python|postman/i;
const limit=160;

const acceptedHeaders = new Set(['host','origin','sec-fetch-site','sec-gpc','dnt','user-agent','content-type','content-length']);

// Only the isolated listener owns its IncomingMessage. Embedded handlers never
// mutate the host application's request or copy any unrelated header.
export function stripTransportHeaders(req) {
  const headers = Object.create(null), distinct = Object.create(null), raw = [];
  for (const [key,value] of Object.entries(req.headers)) {
    if (!acceptedHeaders.has(key)) continue;
    headers[key] = value;
    distinct[key] = Array.isArray(value) ? value : [value];
    for (const item of distinct[key]) raw.push(key,item);
  }
  req.rawHeaders = raw;
  req.headers = headers;
  req.headersDistinct = distinct;
}

export function createSiteVisitHandler({ appId, origin, root, enabled=false, clock=Date.now }) {
  if(enabled) {
    const url=new URL(origin);
    if(!/^[a-z0-9][a-z0-9-]{0,79}$/.test(appId)||url.protocol!=='https:'||url.origin!==origin||
        typeof root !== 'string' || !isAbsolute(root)) throw Error('invalid_site_configuration');
  }
  const host=enabled?new URL(origin).host:null;
  const counter=enabled?openCounter({root,appId,origin,clock}):null;
  let hits=0,rateMinute=-1;
  const exportNow=()=>counter?.exportSnapshot(clock());
  if(counter)exportNow();
  const timer=counter?setInterval(()=>{try{exportNow();}catch{console.error('site_visit_export_failed');}},60_000):null;
  timer?.unref();
  function done(res,status){res.statusCode=status;res.setHeader('Cache-Control','no-store');res.end();}
  async function handler(req,res,next) {
    if(req.url!==clientPath && req.url!==pagePath) {
      if(next)return next();
      return done(res,404);
    }
    if(!counter || req.headers.host!==host) return done(res,404);
    res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Cross-Origin-Resource-Policy','same-origin');
    if(req.url===clientPath) {
      if(!['GET','HEAD'].includes(req.method))return done(res,405);
      res.setHeader('Content-Type','text/javascript; charset=utf-8');res.setHeader('Cache-Control','no-store');
      res.end(req.method==='HEAD'?undefined:client);return;
    }
    if(req.method!=='POST')return done(res,405);
    if(req.headers.origin!==origin || req.headers['sec-fetch-site']!=='same-origin')return done(res,403);
    const agent=req.headers['user-agent'];
    if(!agent || automated.test(agent) || req.headers['sec-gpc']==='1' || req.headers.dnt==='1')return done(res,204);
    if((req.headers['content-type']||'').split(';')[0].trim().toLowerCase()!=='application/json')return done(res,415);
    const now=clock(),minute=Math.floor(now/60000);
    if(minute!==rateMinute){rateMinute=minute;hits=0;}
    if(++hits>1200)return done(res,429);
    if(Number(req.headers['content-length'])>limit)return done(res,413);
    let body;
    try {
      let raw=req.rawBody;
      if(raw===undefined) {
        if(req.readableEnded)return done(res,400);
        const chunks=[];let size=0;
        for await(const chunk of req) {
          size+=chunk.length;if(size>limit)return done(res,413);
          chunks.push(chunk);
        }
        raw=Buffer.concat(chunks);
      }
      if(!Buffer.isBuffer(raw) || raw.length>limit)return done(res,413);
      body=JSON.parse(raw.toString('utf8'));
    } catch{return done(res,400);}
    if(!body || typeof body!=='object' || Object.keys(body).sort().join(',')!=='day,id')return done(res,400);
    try { return done(res,counter.record(body.day,body.id,now)?204:400); }
    catch { return done(res,503); }
  }
  return {handler,close(){if(timer)clearInterval(timer);if(counter){try{exportNow();}finally{counter.close();}}}};
}

if(process.argv[1] && import.meta.url===pathToFileURL(resolve(process.argv[1])).href) {
  const kit=createSiteVisitHandler({appId:process.env.SITE_ID,origin:process.env.SITE_ORIGIN,
    enabled:process.env.SITE_VISITS_ENABLED==='1',root:process.env.SITE_DATA_DIR||'/var/lib/site-sayaci'});
  const server=createServer((req,res)=>{
    stripTransportHeaders(req);
    if(req.url==='/health' && (req.method==='HEAD'||req.method==='GET')){res.statusCode=200;res.end();return;}
    return kit.handler(req,res);
  });
  server.headersTimeout=10000;server.requestTimeout=15000;
  server.listen(3806,'0.0.0.0');
  const shutdown=()=>{server.close(()=>{kit.close();});};
  process.once('SIGTERM',shutdown);process.once('SIGINT',shutdown);
}
