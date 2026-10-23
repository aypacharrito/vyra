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
    :isMeta?'Use your Meta developer app with '+(name==='instagram'?'Instagram API / Instagram Login. Use the Instagram App ID and Instagram App Secret from API setup with Instagram login, rather than the parent Facebook App ID. Your Instagram account needs to be a Business or Creator account. In development mode, accept the Instagram tester invitation before connecting.':'Facebook Login and Page publishing permissions. You will choose your Facebook Page after signing in.')+' Register the exact callback below in the app’s settings, then enter the app ID and secret.'
    :'Use your approved TikTok developer app with Login Kit and Content Posting API, then enter its client key and secret.';
   const callback=isMeta?'https://vyra-five-lac.vercel.app/api/'+name+'-callback':config.callback;
   el('connectionFields').innerHTML=`<p class="note">${escape(instructions)}</p><p><a class="btn subtle" target="_blank" rel="noopener noreferrer" href="${escape(config.developer_url)}">Open ${name==='youtube'?'Google':isMeta?'Meta':'TikTok'} app setup ↗</a>${name==='youtube'?' <a class="btn subtle" target="_blank" rel="noopener noreferrer" href="https://console.cloud.google.com/apis/library/youtube.googleapis.com">Enable YouTube API ↗</a>':''}</p><div class="setup-step"><span class="eyebrow">CALLBACK ADDRESS</span><code>${escape(config.callback||callback)}</code><button type="button" class="btn subtle" id="copyCallback">Copy address</button></div>${name==='youtube'?'<label for="googleCredential">Google OAuth client JSON</label><input id="googleCredential" type="file" accept=".json,application/json"><p class="note" id="credentialStatus">Choose the downloaded Desktop app JSON. It stays on this computer.</p>':`<label for="clientId">${name==='instagram'?'Instagram App ID':isMeta?'App ID':'Client key'}</label><input class="input" id="clientId" name="client_id" autocomplete="off" maxlength="4096" placeholder="${config.saved_fields.includes('client_id')?'Saved — leave blank to keep it':'Enter your app ID'}"><label for="clientSecret">${name==='instagram'?'Instagram App Secret':isMeta?'App secret':'Client secret'}</label><input class="input" id="clientSecret" name="client_secret" type="password" autocomplete="new-password" maxlength="4096" placeholder="${config.saved_fields.includes('client_secret')?'Saved — leave blank to keep it':'Enter privately here'}">${isMeta?`<label for="redirectUri">Approved callback address</label><input class="input" id="redirectUri" name="redirect_uri" type="url" value="${escape(config.callback||callback)}" required>`:''}`}
    <p class="note">${config.configured?'App details are saved. You can connect your account now or replace the details below.':'Finish this one-time app setup, then use the platform’s official sign-in.'} Secrets are encrypted locally for this Windows account. Changing the app details requires reconnecting.</p>`;
   if(name==='instagram'){
    const storage=config.storage||{saved_fields:[]};
    el('connectionFields').insertAdjacentHTML('beforeend',`<div class="setup-step"><h3>Temporary video storage</h3><p class="note">Instagram downloads each Reel from a temporary URL. Use a private Cloudflare R2 bucket and Object Read & Write S3 credentials. VYRA deletes its temporary files after processing; nothing needs to be made public.</p>${[['account_id','Cloudflare account ID'],['access_key_id','R2 access key ID'],['secret_access_key','R2 secret access key'],['bucket','R2 bucket name']].map(([key,label])=>`<label for="storage_${key}">${label}</label><input class="input" id="storage_${key}" type="${key==='access_key_id'||key==='secret_access_key'?'password':'text'}" autocomplete="off" placeholder="${storage.saved_fields.includes(key)?'Saved — leave blank to keep it':label}">`).join('')}<button type="button" class="btn subtle" id="saveVideoStorage" style="margin-top:16px">Save video storage</button><button type="button" class="btn subtle" id="testInstagramSetup" style="margin-top:16px">Test posting setup</button><p class="status" id="storageResult">${storage.configured?'Storage details saved.':'Storage setup required before your first Reel.'}</p></div>`);
    el('saveVideoStorage').onclick=async()=>{
     const button=el('saveVideoStorage');button.disabled=true;
     try{const value=Object.fromEntries(['account_id','access_key_id','secret_access_key','bucket'].map(key=>[key,el('storage_'+key).value]));await api('/api/connections/instagram/storage','PUT',value);['account_id','access_key_id','secret_access_key','bucket'].forEach(key=>{el('storage_'+key).value='';el('storage_'+key).placeholder='Saved — leave blank to keep it'});el('storageResult').textContent='Storage details saved. Use Check platform status to verify Instagram.';await window.loadStatus()}catch(error){el('storageResult').textContent=error.message}finally{button.disabled=false}
    };
   }
   if(name==='instagram')el('testInstagramSetup').onclick=()=>testPosting(el('testInstagramSetup'));
   el('copyCallback').onclick=async()=>{try{await navigator.clipboard.writeText(config.callback||callback);el('connectionError').textContent='Callback address copied.'}catch{el('connectionError').textContent='Select the address above and copy it.'}};
   el('googleCredential')?.addEventListener('change',()=>{const file=el('googleCredential').files[0];el('credentialStatus').textContent=file?'Selected: '+file.name:'Choose the Google OAuth client JSON.'});
   el('connectionSave').textContent=config.configured?'Save app details':'Save & continue';
  }catch(error){el('connectionError').textContent=error.message}
 }
 async function testPosting(button){
  button.disabled=true;
  const feedback=el('storageResult');if(feedback)feedback.textContent='Checking Instagram sign-in, permission and temporary video access…';
  try{
   const result=await api('/api/connections/instagram/test','POST',{});
   const message=result.ready?(result.storage_test?.message||'Instagram posting setup verified.'):result.message+' '+(result.setup_message||'');
   if(feedback)feedback.textContent=message;
   window.toast(message);await window.loadStatus();
  }catch(error){if(feedback)feedback.textContent=error.message;window.toast(error.message)}finally{button.disabled=false}
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
  const testButton=event.target.closest('[data-test-instagram]');if(testButton){await testPosting(testButton);return}
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
