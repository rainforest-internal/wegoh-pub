/* Exact catalog-size regression; synthetic same-origin GET/session, no mutation. */
'use strict';
const {chromium}=require('playwright'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const root=path.resolve(__dirname,'../..'),web=path.join(root,'server/web'),origin='https://docs.wegoh.invalid';
const hash=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const inputs=['server/web/api-docs.js','server/web/api-docs-size.test.cjs'];const before=Object.fromEntries(inputs.map(n=>[n,hash(path.join(root,n))]));
const spec={openapi:'3.1.0',info:{title:'Owned catalog',version:'1',description:'x'.repeat(1048576)},paths:{'/v1/auth/session':{get:{summary:'Owned session',responses:{'200':{description:'Owned response'}}}}}};
const catalog=JSON.stringify(spec);assert(catalog.length>1048576&&catalog.length<4194304);
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();let oversized=false;const pageErrors=[];page.on('pageerror',e=>pageErrors.push(e.message));
 await page.route(origin+'/**',async route=>{const u=new URL(route.request().url()),p=u.pathname;
  if(p==='/openapi.json')return route.fulfill({status:200,contentType:'application/json',body:oversized?JSON.stringify({padding:'x'.repeat(4194304)}):catalog});
  if(p==='/v1/auth/session')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({authenticated:true,user:{id:'owned',role:'admin'},csrfToken:'synthetic-only'})});
  if(p==='/ordinary-large')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({padding:'x'.repeat(1048576)})});
  const name=p==='/api-docs'?'api-docs.html':p.slice(1);const file=path.resolve(web,name);if(!file.startsWith(web+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile())return route.fulfill({status:404,body:''});
  const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.ttf':'font/ttf'};return route.fulfill({status:200,contentType:types[path.extname(file)]||'application/octet-stream',body:fs.readFileSync(file)});
 });
 await page.goto(origin+'/api-docs',{waitUntil:'networkidle'});await page.locator('.swagger-ui .info .title').waitFor({timeout:10000});assert.equal(await page.locator('.swagger-ui .opblock').count(),1);assert.equal(await page.locator('#api-status').innerText(),'');
 const ordinary=await page.evaluate(async()=>{try{await raw('/ordinary-large');return false;}catch{return true;}});assert(ordinary);
 const nonGet=await page.evaluate(async()=>{try{await raw('/openapi.json',{method:'POST'});return false;}catch{return true;}});assert(nonGet);
 oversized=true;const catalogLimit=await page.evaluate(async()=>{try{await raw('/openapi.json');return false;}catch{return true;}});assert(catalogLimit);
 assert.deepEqual(pageErrors,[]);assert.deepEqual(Object.fromEntries(inputs.map(n=>[n,hash(path.join(root,n))])),before);
 console.log(JSON.stringify({passed:true,catalogCharacters:catalog.length,swaggerRenderedOperations:1,ordinaryOneMiBRejected:true,nonGetStillOneMiB:true,overFourMiBCatalogRejected:true,syntheticOnly:true,productionRequests:0,inputs:before}));
}finally{await browser.close();}})().catch(e=>{console.error(e.name+': '+e.message);process.exitCode=1;});
