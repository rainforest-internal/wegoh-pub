"use strict";
// Reviewer vehicle connection: the former enroll screen logic on /reviewer API paths.
(() => {
  const el=id=>document.getElementById(id), API="/reviewer/v1";
  const valid=value=>/^[A-HJ-NP-Z2-9]{8}$/.test(value);
  // Accepts the 8 characters or a pasted QR link (?user_code=, #CODE).
  function extract(value){
    const text=value.trim(), match=text.match(/[?&]user_code=([A-Za-z0-9]{8})(?:[&#]|$)/)||text.match(/#([A-Za-z0-9]{8})$/);
    return (match?match[1]:text.replace(/[\s-]/g,"")).toUpperCase();
  }
  let session=null, detail=null, contract=null, busy=false, revision=0;
  const status=el("enrollment-status"), say=text=>{status.textContent=text;};
  const canonical=value=>Array.isArray(value)?"["+value.map(canonical).join(",")+"]":value&&typeof value==="object"?
    "{"+Object.keys(value).sort().map(key=>JSON.stringify(key)+":"+canonical(value[key])).join(",")+"}":JSON.stringify(value);
  const exact=(value,keys)=>value&&typeof value==="object"&&!Array.isArray(value)&&Object.keys(value).sort().join("|")===keys.slice().sort().join("|");
  const same=(a,b)=>canonical(a)===canonical(b);
  function clear(){detail=null;el("enrollment-detail").hidden=true;el("enrollment-scopes").replaceChildren();el("enrollment-remember").checked=false;}
  function present(){
    const pending=detail?.state==="PENDING";
    el("enrollment-detail").hidden=!detail||!["PENDING","APPROVED"].includes(detail.state);
    el("enrollment-consent").hidden=!pending;el("enrollment-approve").hidden=!pending;
    el("enrollment-cancel").textContent=pending?"취소":"연결 해제";
  }
  function signedIn(){
    const yes=Boolean(session?.authenticated);
    el("reviewer-login-form").hidden=yes;el("reviewer-account").hidden=!yes;el("enrollment-code-form").hidden=!yes;
    el("enrollment-account").textContent=yes?session.user.displayName+" 계정으로 연결합니다.":"";
    if(!yes)clear();
  }
  function lock(value){busy=value;
    for(const id of ["reviewer-login-form","enrollment-code-form"])el(id).querySelector("button").disabled=value;
    el("reviewer-logout").disabled=value;
    el("enrollment-approve").disabled=value||!detail||detail.state!=="PENDING";
    el("enrollment-cancel").disabled=value||!detail||!["PENDING","APPROVED"].includes(detail.state);}
  function errorText(error){return error.status===401?"이메일로 다시 시작해 주세요.":error.status===403?"이 이메일로는 시작할 수 없습니다.":[404,410].includes(error.status)?
    "코드가 만료되었거나 올바르지 않습니다.":error.status===409?"연결 정보를 다시 확인해 주세요.":error.status===429?"잠시 후 다시 시도해 주세요.":"연결을 확인해 주세요.";}
  async function api(path,options={}){
    const headers=new Headers({Accept:"application/json"});
    if(options.method){headers.set("Content-Type","application/json");if(session?.csrfToken)headers.set("X-WegoH-CSRF",session.csrfToken);}
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
    try{const response=await fetch(path,{...options,headers,credentials:"same-origin",cache:"no-store",redirect:"error",signal:controller.signal});
      if(!response.ok){const error=new Error("Request rejected");error.status=response.status;throw error;}
      if(!response.headers.get("Content-Type")?.startsWith("application/json"))throw new Error("Invalid response");return await response.json();
    }finally{clearTimeout(timer);}
  }
  const PRESELECTED=new Set(["courses:read","playlists:read"]);
  function policyRow(policy){
    const names={"account:read":"계정 확인","account:write":"계정 이름 변경","device:self:manage":"연결 관리","courses:read":"드라이브 코스","playlists:read":"플레이리스트"};
    const section=document.createElement("section");section.className="connection-scope";
    const label=document.createElement("label");label.className="connection-choice";
    const input=document.createElement("input");input.type="checkbox";input.value=policy.scope;input.checked=policy.required||PRESELECTED.has(policy.scope);input.disabled=policy.required;
    input.dataset.scope=policy.scope;const title=document.createElement("strong");title.textContent=names[policy.scope]||policy.scope;
    const kind=document.createElement("span");kind.className="scope-kind";kind.textContent=policy.required?"필수":"선택";
    label.append(input,title,kind);section.append(label);
    const purpose=document.createElement("p");purpose.textContent=policy.purpose;section.append(purpose);
    const list=document.createElement("dl");
    for(const [name,value] of [[policy.scope==="account:write"?"변경 정보":"조회 정보",policy.dataCategories.join(", ")],["보관",policy.retention],["거부",policy.refusalEffect],["철회",policy.withdrawalEffect]]){
      const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=name;dd.textContent=value;list.append(dt,dd);
    }
    section.append(list);return section;
  }
  async function validate(value,target){
    const fields=Object.keys(contract.phoneOperations.find(x=>x.action==="PHONE_STATUS").responseRequired);
    if(!exact(value,fields)||value.authorizationVersion!==1||value.userCode!==target||!contract.states.includes(value.state)||
      typeof value.deviceName!=="string"||typeof value.currentAccountDisplayName!=="string"||value.keepSignedInDefault!==false||
      !Number.isSafeInteger(value.expiresAt)||!Number.isSafeInteger(value.consentVersion)||value.consentVersion<1)throw new Error("Invalid connection");
    const mandatory=contract.disclosureRegistry.scopePolicies.filter(x=>x.required).map(x=>x.scope).sort();
    if(!Array.isArray(value.requestedScopes)||!same(value.requestedScopes,[...new Set(value.requestedScopes)].sort())||
       !same(value.requiredScopes,mandatory)||!mandatory.every(x=>value.requestedScopes.includes(x)))throw new Error("Invalid scopes");
    const registry=contract.disclosureRegistry;
    const snapshot={disclosureVersion:registry.version,scopeDisclosures:registry.scopePolicies.filter(x=>value.requestedScopes.includes(x.scope)),
      bindingMaxSeconds:contract.lifetimes.bindingSeconds,keepSignedInDisclosure:registry.keepSignedInDisclosure};
    if(snapshot.scopeDisclosures.length!==value.requestedScopes.length)throw new Error("Unknown scope");
    const digest=new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(canonical(snapshot))));
    snapshot.disclosureSha256=[...digest].map(x=>x.toString(16).padStart(2,"0")).join("");
    if(!same(value.disclosureSnapshot,snapshot))throw new Error("Changed disclosure");
    return value;
  }
  async function load(){
    const target=extract(el("enrollment-code").value),current=++revision;clear();
    if(!valid(target)){say("차량에 표시된 8자리 코드나 QR 링크를 입력해 주세요.");return;}
    el("enrollment-code").value=target;
    if(!session?.authenticated){say("이메일로 먼저 시작해 주세요.");return;}
    lock(true);say("확인하고 있습니다.");
    try{const value=await validate(await api(API+"/connections/"+target),target);
      if(current!==revision)return;detail=value;
      el("enrollment-name").textContent=value.deviceName;
      el("enrollment-code-comparison").textContent=value.userCode;
      el("enrollment-scopes").replaceChildren(...value.disclosureSnapshot.scopeDisclosures.map(policyRow));
      el("enrollment-remember-disclosure").textContent=value.disclosureSnapshot.keepSignedInDisclosure;
      present();
      say(value.state==="PENDING"?"차량의 이름과 코드를 확인해 주세요.":value.state==="APPROVED"?"차량에서 연결을 완료해 주세요.":"연결 상태를 확인해 주세요.");
    }catch(error){if(current===revision){if(error.status===401){session=null;signedIn();}say(errorText(error));}}finally{lock(false);}
  }
  el("reviewer-login-form").addEventListener("submit",async event=>{
    event.preventDefault();if(busy)return;lock(true);say("시작하고 있습니다.");
    try{session=await api(API+"/login",{method:"POST",body:JSON.stringify({email:el("reviewer-email").value.trim()})});
      signedIn();say("차량에 표시된 코드나 QR 링크를 입력해 주세요.");
      if(el("enrollment-code").value){lock(false);await load();}
    }catch(error){say(errorText(error));}finally{lock(false);}
  });
  el("reviewer-logout").addEventListener("click",async()=>{
    if(busy)return;lock(true);
    try{await api(API+"/session",{method:"DELETE"});session=null;signedIn();say("로그아웃했습니다.");}
    catch(error){say(errorText(error));}finally{lock(false);}
  });
  el("enrollment-code-form").addEventListener("submit",event=>{event.preventDefault();if(!busy)load();});
  el("enrollment-code").addEventListener("input",()=>{revision++;clear();});
  el("enrollment-approve").addEventListener("click",async()=>{
    if(busy||detail?.state!=="PENDING")return;const target=detail,current=revision;lock(true);
    const approved=target.disclosureSnapshot.scopeDisclosures.filter(policy=>policy.required||
      [...el("enrollment-scopes").querySelectorAll("input[data-scope]")].some(input=>input.value===policy.scope&&input.checked)).map(x=>x.scope).sort();
    try{const result=await api(API+"/connections/"+target.userCode,{method:"POST",body:JSON.stringify({authorizationVersion:1,
      consentVersion:target.consentVersion,approvedScopes:approved,keepSignedIn:el("enrollment-remember").checked,
      disclosureVersion:target.disclosureSnapshot.disclosureVersion,disclosureSha256:target.disclosureSnapshot.disclosureSha256})});
      if(current!==revision)return;
      if(result.authorizationVersion!==1||result.userCode!==target.userCode||!["APPROVED","DENIED"].includes(result.state))throw new Error("Invalid result");
      if(result.state==="APPROVED"){detail={...target,state:"APPROVED"};present();say("차량에서 연결을 완료해 주세요.");}
      else {clear();say("연결을 허용하지 않았습니다.");}
    }catch(error){if(current===revision){clear();say(errorText(error));}}finally{lock(false);}
  });
  el("enrollment-cancel").addEventListener("click",async()=>{
    if(busy||!detail)return;const target=detail,current=revision;lock(true);
    try{const result=await api(API+"/connections/"+target.userCode,{method:"DELETE",body:JSON.stringify({authorizationVersion:1})});
      if(current!==revision)return;if(result.authorizationVersion!==1||result.userCode!==target.userCode||result.state!=="DENIED")throw new Error("Invalid result");
      clear();say(target.state==="APPROVED"?"연결을 해제했습니다.":"연결을 취소했습니다.");
    }catch(error){if(current===revision)say(errorText(error));}finally{lock(false);}
  });
  async function initialize(){
    revision++;session=null;clear();lock(true);
    const code=new URLSearchParams(location.search).get("user_code")||"";
    if(code)el("enrollment-code").value=extract(code);
    if(location.search||location.hash)history.replaceState(null,"",location.pathname);
    try{contract=await api("/reviewer/assets/native-access-wire.json");session=await api(API+"/session");
      if(contract.schemaVersion!==1)throw new Error("Invalid contract");
      signedIn();
      if(!session.authenticated)say("심사용 이메일을 입력해 주세요.");
      else if(valid(el("enrollment-code").value)){lock(false);await load();}
      else say("차량에 표시된 코드나 QR 링크를 입력해 주세요.");
    }catch(error){say(errorText(error));}finally{lock(false);}
  }
  window.addEventListener("pageshow",event=>{if(event.persisted)initialize();});initialize();
})();
