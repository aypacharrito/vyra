(() => {
 'use strict';
 const el=id=>document.getElementById(id);
 const csrf=document.querySelector('meta[name="vyra-csrf"]').content;
 const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const labels={youtube:'YouTube Shorts',instagram:'Instagram Reels',facebook:'Facebook Reels',tiktok:'TikTok'};
 const api=async(path,method='GET',body)=>{
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json','x-vyra-csrf':csrf},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error(data.detail||'Connection setup could not finish.');return data;
 };
 const embedded=window.parent!==window&&new URLSearchParams(location.search).get('embedded')==='1';
 function openAccountLink(url){if(embedded)window.parent.postMessage({type:'vyra.openExternal',url},'http://127.0.0.1:48791');else location.assign(url)}
 if(embedded){document.documentElement.classList.add('embedded');document.addEventListener('click',event=>{const link=event.target.closest('a[target="_blank"]');if(link){event.preventDefault();openAccountLink(link.href)}},true)}
 window.addEventListener('focus',()=>window.loadStatus?.());document.addEventListener('visibilitychange',()=>{if(!document.hidden)window.loadStatus?.()});
 let provider='', busy=false;
 const dialog=el('connectionDialog');
 async function setup(name){
  provider=name;el('connectionTitle').textContent='Connect '+labels[name];el('connectionError').textContent='';
  el('connectionFields').innerHTML='<p class="note">Loading your connection settings…</p>';dialog.showModal();
  try{
   const config=await api('/api/connections/'+name);if(provider!==name)return;
   const isMeta=name==='instagram'||name==='facebook';
   const instructions=name==='youtube'
    ?'Enable YouTube Data API v3 in your Google project, then create an OAuth client with the Desktop app type. Download its JSON file and choose it below. After saving, choose your channel’s Google or Brand account. Google will ask you to allow channel verification and video uploads.'
    :isMeta?'Use your Meta developer app with '+(name==='instagram'?'Instagram API / Instagram Login. Your Instagram account needs to be a Business or Creator account.':'Facebook Login and Page publishing permissions. You will choose your Facebook Page after signing in.')+' Register the exact callback below in the app’s settings, then enter the app ID and secret.'
    :'Use your approved TikTok developer app with Login Kit and Content Posting API, then enter its client key and secret.';
   const callback=isMeta?'https://vyra-five-lac.vercel.app/api/'+name+'-callback':config.callback;
   el('connectionFields').innerHTML=`<p class="note">${escape(instructions)}</p><p><a class="btn subtle" target="_blank" rel="noopener noreferrer" href="${escape(config.developer_url)}">Open ${name==='youtube'?'Google':isMeta?'Meta':'TikTok'} app setup ↗</a>${name==='youtube'?' <a class="btn subtle" target="_blank" rel="noopener noreferrer" href="https://console.cloud.google.com/apis/library/youtube.googleapis.com">Enable YouTube API ↗</a>':''}</p><div class="setup-step"><span class="eyebrow">CALLBACK ADDRESS</span><code>${escape(config.callback||callback)}</code><button type="button" class="btn subtle" id="copyCallback">Copy address</button></div>${name==='youtube'?'<label for="googleCredential">Google OAuth client JSON</label><input id="googleCredential" type="file" accept=".json,application/json"><p class="note" id="credentialStatus">Choose the downloaded Desktop app JSON. It stays on this computer.</p>':`<label for="clientId">${isMeta?'App ID':'Client key'}</label><input class="input" id="clientId" name="client_id" autocomplete="off" maxlength="4096" placeholder="${config.saved_fields.includes('client_id')?'Saved — leave blank to keep it':'Enter your app ID'}"><label for="clientSecret">${isMeta?'App secret':'Client secret'}</label><input class="input" id="clientSecret" name="client_secret" type="password" autocomplete="new-password" maxlength="4096" placeholder="${config.saved_fields.includes('client_secret')?'Saved — leave blank to keep it':'Enter privately here'}">${isMeta?`<label for="redirectUri">Approved callback address</label><input class="input" id="redirectUri" name="redirect_uri" type="url" value="${escape(config.callback||callback)}" required>`:''}`}
    <p class="note">${config.configured?'App details are saved. You can connect your account now or replace the details below.':'Finish this one-time app setup, then use the platform’s official sign-in.'} Secrets are encrypted locally for this Windows account. Changing the app details requires reconnecting.</p>`;
   el('copyCallback').onclick=async()=>{try{await navigator.clipboard.writeText(config.callback||callback);el('connectionError').textContent='Callback address copied.'}catch{el('connectionError').textContent='Select the address above and copy it.'}};
   el('googleCredential')?.addEventListener('change',()=>{const file=el('googleCredential').files[0];el('credentialStatus').textContent=file?'Selected: '+file.name:'Choose the Google OAuth client JSON.'});
   el('connectionSave').textContent=config.configured?'Save app details':'Save & continue';
  }catch(error){el('connectionError').textContent=error.message}
 }
 async function connect(name){
  if(busy)return;busy=true;
  try{const data=await api('/api/oauth/'+name+'/start','POST',{});openAccountLink(data.url)}
  catch(error){window.toast(error.message);await setup(name)}finally{busy=false}
 }
 el('connectionClose').onclick=()=>dialog.close();
 el('connectionForm').addEventListener('submit',async event=>{
  event.preventDefault();if(busy)return;busy=true;const name=provider,button=el('connectionSave');button.disabled=true;
  try{
   let body=Object.fromEntries(new FormData(event.target));
   if(name==='youtube'){
    const file=el('googleCredential').files[0];
    if(!file){if(!window.accountStatus?.[name]?.configured)throw Error('Choose the downloaded Google OAuth client JSON first.');body={}}
    else{if(file.size>24000)throw Error('Choose the small OAuth client JSON file downloaded from Google.');body={credential_json:await file.text()}}
   }
   await api('/api/connections/'+name,'PUT',body);event.target.reset();dialog.close();await window.loadStatus();window.toast('App details saved. Click Connect account to approve access.');
  }catch(error){el('connectionError').textContent=error.message}finally{busy=false;button.disabled=false}
 });
 el('accountsList').addEventListener('click',async event=>{
  const setupButton=event.target.closest('[data-setup]');if(setupButton){await setup(setupButton.dataset.setup);return}
  const connectButton=event.target.closest('[data-connect]');if(connectButton){await connect(connectButton.dataset.connect);return}
  const pageButton=event.target.closest('[data-save-page]');if(pageButton){
   if(!el('facebookPage').value){window.toast('Choose your Facebook Page first.');return}
   pageButton.disabled=true;
   try{await api('/api/accounts/facebook/page','POST',{page_id:el('facebookPage').value});await window.loadStatus();window.toast('Facebook Page connected.')}catch(error){window.toast(error.message)}finally{pageButton.disabled=false}
  }
 });
 window.VYRAConnections={setup,connect};
})();
