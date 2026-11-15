/* Official Swagger UI, own-origin cookies, fresh CSRF, no credential persistence. */
'use strict';
const $=id=>document.getElementById(id);
let schema=null,ui=null,actor=null,role=null,authenticated=false,generation=0,loadSequence=0,visible=true,confirmation=null,swaggerFlight=null;
const controllers=new Set();
const status=text=>{$('api-status').textContent=text;};
const sensitive=new Set(['csrftoken','accesstoken','refreshtoken','devicecode','authorization','password','secret']);
function redact(value){if(Array.isArray(value))return value.map(redact);if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,sensitive.has(k.toLowerCase())?'[REDACTED]':redact(v)]));return value;}
function clearSensitive(){
 generation++;swaggerFlight=null;for(const controller of controllers)controller.abort();controllers.clear();
 if(confirmation){confirmation(false);confirmation=null;}if($('api-confirm').open)$('api-confirm').close();$('api-confirm-route').textContent='';
 const old=$('swagger-ui'),fresh=old.cloneNode(false);old.replaceWith(fresh);ui=null;
 // Replacing the whole mount detaches old React roots; late Redux work cannot restore old DOM.
}
function controller(){const value=new AbortController();controllers.add(value);const timer=setTimeout(()=>{value.abort();controllers.delete(value);},15000);return {value,release:()=>{clearTimeout(timer);controllers.delete(value);}};}
async function raw(path,options={}){const c=controller();try{const response=await fetch(path,{credentials:'same-origin',redirect:'error',cache:'no-store',...options,signal:c.value.signal});const text=await response.text();const limit=path==='/openapi.json'&&(options.method||'GET').toUpperCase()==='GET'?4194304:1048576;if(text.length>limit)throw Error('응답이 너무 큽니다.');return {ok:response.ok,status:response.status,data:JSON.parse(text)};}finally{c.release();}}
async function session(){
 const epoch=generation,result=await raw('/v1/auth/session');if(epoch!==generation||!visible)throw Error('페이지가 변경됐습니다.');
 const id=result.data?.user?.id||null,nextRole=result.data?.user?.role||null;
 if(id!==actor||nextRole!==role)clearSensitive();actor=id;role=nextRole;
 authenticated=result.ok&&result.data.authenticated===true&&role==='admin';$('api-session').textContent=authenticated?'로그아웃':'로그인';$('api-session').disabled=false;
 return result;
}
function sample(value){if(Array.isArray(value.type)&&value.type.includes('null')||value.anyOf?.some(x=>x.type==='null'))return null;if(value.const!==undefined)return value.const===true?false:value.const;if(value.enum)return value.enum[0];if(value.type==='object')return Object.fromEntries((value.required||[]).map(k=>[k,sample(value.properties[k])]));if(value.type==='array')return [];if(value.type==='boolean')return false;if(value.type==='number'||value.type==='integer')return value.minimum??0;return '';}
function operation(url,method){for(const [path,methods]of Object.entries(schema.paths)){const pattern='^'+path.split('/').map(part=>part.startsWith('{')&&part.endsWith('}')?'[^/]+':[...part].map(c=>/[A-Za-z0-9_-]/.test(c)?c:'\\'+c).join('')).join('/')+'$';if(new RegExp(pattern).test(url.pathname)&&methods[method])return methods[method];}return null;}
function confirmRequest(label){if(confirmation)throw Error('다른 요청을 확인 중입니다.');$('api-confirm-route').textContent=label;$('api-confirm').showModal();$('api-confirm-cancel').focus();return new Promise(resolve=>{confirmation=resolve;});}
function settleConfirmation(ok){const resolve=confirmation;confirmation=null;$('api-confirm').close();$('api-confirm-route').textContent='';resolve?.(ok);}
$('api-confirm-run').onclick=()=>settleConfirmation(true);$('api-confirm-cancel').onclick=()=>settleConfirmation(false);$('api-confirm').addEventListener('cancel',()=>settleConfirmation(false));
function render(){
 const view=generation,definition=structuredClone(schema);
 // Consent/rights constants stay in the real schema. Unfilled examples never affirm them.
 for(const methods of Object.values(definition.paths))for(const op of Object.values(methods)){const json=op?.requestBody?.content?.['application/json'];if(json?.schema){if(Object.hasOwn(op,'x-wegoh-try-example'))json.example=structuredClone(op['x-wegoh-try-example']);else if(!Object.hasOwn(json,'example')&&!json.examples)json.example=sample(json.schema);}}
 ui=SwaggerUIBundle({domNode:$('swagger-ui'),spec:definition,layout:'BaseLayout',presets:[SwaggerUIBundle.presets.apis],validatorUrl:null,queryConfigEnabled:false,persistAuthorization:false,withCredentials:false,showMutatedRequest:false,requestSnippetsEnabled:false,deepLinking:false,filter:true,docExpansion:'list',supportedSubmitMethods:['get','post','put','patch','delete'],
 requestInterceptor:async request=>{
  const url=new URL(request.url,location.origin),method=(request.method||'GET').toLowerCase(),op=operation(url,method);
  if(!visible||view!==generation)throw Error('페이지가 변경됐습니다.');
  if(url.origin!==location.origin||url.username||url.password||url.hash||!url.pathname.startsWith('/v1/')||!op||op['x-wegoh-executable']!==true)throw Error('이 요청은 여기서 실행할 수 없습니다.');
  if(swaggerFlight)throw Error('처리 중인 요청이 있습니다.');
  const flight={view};swaggerFlight=flight;try{
  request.headers={...request.headers};for(const key of Object.keys(request.headers))if(['authorization','cookie','x-wegoh-csrf'].includes(key.toLowerCase()))delete request.headers[key];
  const expected=actor,current=await session();if(view!==generation||actor!==expected)throw Error('계정이 변경됐습니다.');
  const login=url.pathname==='/v1/auth/session'&&['get','post'].includes(method);
  if(!authenticated&&!login)throw Error('로그인이 필요합니다.');
  if(method!=='get'){
   if(request.body!==undefined){if(typeof request.body!=='string'||new TextEncoder().encode(request.body).length>262144)throw Error('입력한 내용을 확인하세요.');JSON.parse(request.body);}
   if(!await confirmRequest(method.toUpperCase()+' '+url.pathname))throw Error('취소했습니다.');
   if(view!==generation||actor!==expected)throw Error('계정이 변경됐습니다.');
   const fresh=await session();if(view!==generation||actor!==expected||!visible)throw Error('계정이 변경됐습니다.');
   if(!login){if(!authenticated||!fresh.data.csrfToken)throw Error('로그인이 필요합니다.');request.headers['X-WegoH-CSRF']=fresh.data.csrfToken;}
  }
  request.credentials='same-origin';request.redirect='error';const c=controller();flight.release=c.release;request.signal=c.value.signal;c.value.signal.addEventListener('abort',()=>{if(swaggerFlight===flight)swaggerFlight=null;},{once:true});
  // No tokens in URL/storage. The timeout/clear lifecycle releases outstanding controllers.
  return request;
  }catch(error){if(swaggerFlight===flight){flight.release?.();swaggerFlight=null;}throw error;}
 },
 responseInterceptor:async response=>{
  const flight=swaggerFlight;try{
  if(view!==generation||!visible)throw Error('페이지가 변경됐습니다.');
  const expected=actor;await session();if(view!==generation||actor!==expected)throw Error('계정이 변경됐습니다.');
  if(typeof response.text==='string'){if(response.text.length>1048576)throw Error('응답이 너무 큽니다.');try{response.text=JSON.stringify(redact(JSON.parse(response.text)));}catch(error){if(error.message==='응답이 너무 큽니다.')throw error;}}
  for(const key of ['body','obj','data'])if(response[key]&&typeof response[key]==='object')response[key]=redact(response[key]);
  if(response.headers)for(const key of Object.keys(response.headers))if(['authorization','set-cookie','x-wegoh-csrf'].includes(key.toLowerCase()))delete response.headers[key];
  return response;
  }finally{if(swaggerFlight===flight){flight?.release?.();swaggerFlight=null;}}
 }});
}
async function load(){const sequence=++loadSequence;clearSensitive();status('');try{await session();if(sequence!==loadSequence||!visible)return;const epoch=generation,result=await raw('/openapi.json');if(sequence!==loadSequence||epoch!==generation||!visible)return;if(!result.ok)throw Error();schema=result.data;render();if(!authenticated)status('로그인이 필요합니다.');}catch{if(sequence===loadSequence&&visible)status('연결을 확인하세요.');}}
$('api-refresh').onclick=load;
$('api-session').onclick=async()=>{const wanted=authenticated,expected=actor;$('api-session').disabled=true;try{const fresh=await session();if(actor!==expected||authenticated!==wanted)throw Error();clearSensitive();const result=await raw('/v1/auth/session',{method:wanted?'DELETE':'POST',headers:wanted?{'X-WegoH-CSRF':fresh.data.csrfToken}:{}});if(!result.ok)throw Error();if(wanted){location.assign('/cdn-cgi/access/logout');return;}await load();}catch{clearSensitive();status('연결을 확인하세요.');}finally{$('api-session').disabled=false;}};
window.addEventListener('pagehide',()=>{visible=false;clearSensitive();});window.addEventListener('pageshow',event=>{if(event.persisted){visible=true;load();}});load();
