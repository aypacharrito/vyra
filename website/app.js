(() => {
'use strict';
const root = document.querySelector('#main');
const csrf = document.querySelector('meta[name="vyra-session"]')?.content || '';
const isDesktop = location.hostname === '127.0.0.1' || location.hostname === 'localhost';
const dataKey = 'vyra_studio_v1';
const html = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const load = () => { try { const s = JSON.parse(localStorage.getItem(dataKey));return s && typeof s==='object' ? s : {} } catch {return {}} };
const base = load();
const state = {view:'home',chats:Array.isArray(base.chats)?base.chats:[],projects:Array.isArray(base.projects)?base.projects:[],active:base.active||null,configured:false,model:'gpt-5-mini',pending:false,worker:false,projectId:base.projectId||'',mode:base.mode||'assistant',prefs:{speakReplies:false,language:'en-US',voice:'',instructions:''},tasks:[],runs:[],taskError:'',runOpen:{},models:[],draft:'',attachments:[]};
let connectionFeedback={text:'',error:false};
let workspaceTimer, workspaceQueue=Promise.resolve(), workspaceLoaded=false;
function workspaceData(){return {chats:state.chats.slice(0,80),projects:state.projects.slice(0,100),active:state.active||'',projectId:state.projectId,mode:state.mode}}
function save(){
 const value=workspaceData();
 try{localStorage.setItem(dataKey,JSON.stringify(value))}catch{toast('Browser storage is full. Export older conversations.')}
 if(!isDesktop||!workspaceLoaded)return;
 clearTimeout(workspaceTimer);
 workspaceTimer=setTimeout(()=>{const snapshot=workspaceData();workspaceQueue=workspaceQueue.catch(()=>{}).then(()=>request('/api/workspace','PUT',snapshot)).catch(()=>toast('Workspace could not be saved to disk. Export a backup.'))},300);
}
const date=()=>new Date().toISOString();
const uid=()=> (globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2));
const toast=(s)=>{const el=document.querySelector('#toast');el.textContent=s;el.classList.add('show');clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.remove('show'),4700)};
const request=async(path,method='GET',body)=>{
 if(!isDesktop)throw Error('This is a website preview. Download the Windows app for OpenAI chat and local video processing.');
 const res=await fetch(path,{method,headers:{'Content-Type':'application/json','X-VYRA-SESSION':csrf},body:body===undefined?undefined:JSON.stringify(body)});
 const d=await res.json().catch(()=>({error:'Unable to parse server response'}));if(!res.ok)throw Error(d.error||'Request failed');return d;
};
const btn=(title,action,kind='secondary-btn')=>`<button class="${kind}" data-action="${action}">${title}</button>`;
function header(name){document.querySelector('#breadcrumb').textContent=name.toUpperCase();document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('selected',x.dataset.view===state.view));}
function layout(view){if(state.view==='chat'){state.draft=document.querySelector('#chat-input')?.value||state.draft;if(voiceState.active)stopVoice(true)}state.view=view;header(({home:'Discover',chat:'Intelligence',clips:'VYRA Clips',projects:'Projects',agents:'Agents',settings:'Settings'})[view]||view);renderHistory();render();}
function renderHistory(){document.querySelector('#history').innerHTML=state.chats.length?state.chats.slice(0,30).map(c=>`<button class="history-item ${c.id===state.active?'active':''}" data-chat="${html(c.id)}"><span>◷</span><span class="htext">${html(c.title)}</span></button>`).join(''):'<p class="history-empty">Your ideas live here.</p>'}
function home(){return `<div class="page"><section class="home-hero"><div class="hero-orbit"></div><div class="hero-copy"><span class="overline">WELCOME TO A NEW KIND OF WORKSPACE</span><h1 class="headline">Intelligence,<br><span class="gradient">without the limits.</span></h1><p class="lead">One place to think, create, build and bring ideas to life. Meet your personal intelligence system.</p><div class="hero-button">${btn('✦ &nbsp; Start with VYRA','new-chat','primary-btn')}${btn('Explore Creator Studio &nbsp; ↗','clips','secondary-btn')}</div></div></section><div class="section-title">Explore your workspace <small>BUILT AROUND YOU</small></div><div class="tile-grid"><button class="tile" data-action="chat"><span class="tile-icon">◈</span><span class="tile-arrow">↗</span><h3>VYRA Intelligence</h3><p>Ask, brainstorm, analyze and write with OpenAI models in your private workspace.</p></button><button class="tile" data-action="clips"><span class="tile-icon">▷</span><span class="tile-arrow">↗</span><h3>VYRA Clips</h3><p>Turn long videos into vertical highlights for Shorts, Reels and TikTok.</p></button><button class="tile" data-action="projects"><span class="tile-icon">▦</span><span class="tile-arrow">↗</span><h3>Projects & ideas</h3><p>Keep your creative work and next big ideas organized in one library.</p></button></div><div class="mini-banner"><div><h3>THE VYRA ECOSYSTEM</h3><p>Designed for ambitious builders. Inspired by the precision of modern AI and the immersive feel of <b>Steam</b>.</p></div>${btn('Connect OpenAI →','settings','ghost-btn')}</div></div>`}
function getChat(){return state.chats.find(c=>c.id===state.active)}
function createChat(){if(state.pending){toast('Stop or finish the current reply before starting another conversation.');return getChat()}state.draft='';state.attachments=[];const c={id:uid(),title:'New conversation',created:date(),messages:[]};state.chats.unshift(c);state.active=c.id;save();layout('chat');return c}
function chat(){
 const c=getChat();const files=state.attachments.length?state.attachments:c?.referenceFiles||[];const msgs=c?.messages||[];
 const project=state.projects.find(p=>p.id===state.projectId);
 return `<div class="chat-shell"><div class="chat-top"><div><strong>${html(c?.title||'New conversation')}</strong><small class="context-label">${project?'Project: '+html(project.name):'Personal workspace'} · ${html(state.model)}</small></div><div class="chat-tools"><button class="ghost-btn" data-action="export-chat" ${!msgs.length?'disabled':''}>Export</button><button class="ghost-btn" data-action="read-reply" ${!msgs.some(m=>m.role==='assistant')?'disabled':''}>Read aloud</button></div></div>
 <div class="context-controls"><label>Mode <select id="chat-mode" aria-label="Assistant mode">${modeOptions(state.mode)}</select></label><label>Project <select id="chat-project" aria-label="Project context"><option value="">Personal workspace</option>${state.projects.map(p=>`<option value="${html(p.id)}" ${p.id===state.projectId?'selected':''}>${html(p.name)}</option>`).join('')}</select></label><button class="ghost-btn" data-action="attach-code">＋ Code or text</button><input type="file" id="code-files" multiple accept=".txt,.md,.go,.py,.js,.ts,.tsx,.jsx,.json,.css,.html,.csv,.yml,.yaml,.sql,.rs,.java,.cpp,.c,.h" hidden></div>
 ${files.length?`<div class="attachment-list">${files.map((f,i)=>`<span>${html(f.name)} <button data-remove-file="${i}" aria-label="Remove ${html(f.name)}">×</button></span>`).join('')}</div>`:''}
 ${msgs.length?`<div id="messages" class="chat-messages" role="log" aria-label="Conversation">${msgs.map((m,i)=>`<div class="message ${m.role==='user'?'user':'assistant'}">${m.role==='assistant'?'<span class="msg-icon">✦</span>':''}<div class="msg-body">${formatMessage(m.content)}${m.error?`<div class="message-error">${html(m.error)}</div>`:''}${m.role==='assistant'&&!state.pending?`<div class="message-actions"><button class="tinybtn" data-copy-message="${i}">Copy</button><button class="tinybtn" data-read-message="${i}">Read aloud</button></div>`:''}</div></div>`).join('')}${state.pending?`<div class="message"><span class="msg-icon spin">✦</span><div class="msg-body live-answer" id="stream-answer">${html(state.streamText||'Thinking…')}</div></div>`:''}</div>`:
 `<div class="chat-empty"><div class="chat-sigil">✦</div><span class="overline">YOUR IDEAS, IN MOTION</span><h1>Build something that matters.</h1><p>Talk, type, share code. Make your next move with VYRA.</p><div class="prompts">${[
 ['Study my code','Read the attached code carefully. Explain what it does, find real bugs, and provide complete fixes with verification steps.','code'],
 ['Create my next video','Help me create a complete short-form video script with a strong hook, visual cues, captions and a practical shot list.','creator'],
 ['Turn an idea into a plan','Turn my project idea into a concrete plan with milestones, risks and the first three actions.','planner'],
 ['Analyze my material','Analyze the supplied project material. Separate supported findings from uncertainty and give clear recommendations.','research']
 ].map(([name,prompt,mode])=>`<button class="prompt-chip" data-prompt="${html(prompt)}" data-mode="${mode}">${html(name)} ↗</button>`).join('')}</div></div>`}
 <form id="chat-form" class="composer"><textarea id="chat-input" placeholder="Message VYRA… or use your microphone" maxlength="128000" rows="2" aria-label="Message VYRA" ${state.pending?'disabled':''}>${html(state.draft)}</textarea><div class="composer-footer"><div class="voice-tools"><button type="button" class="voice-btn" data-action="dictate" ${state.pending?'disabled':''}>◉ Live dictation</button><button type="button" class="voice-btn" data-action="record" ${state.pending?'disabled':''}>● Record</button></div>${state.pending?'<button type="button" class="secondary-btn" data-action="stop-answer">Stop</button>':'<button type="submit" class="send-btn" aria-label="Send message">➜</button>'}</div></form>
 <div class="chat-footnote">${isDesktop?'Your key stays on this device. Selected project notes and files are sent to OpenAI with your message.':'Interactive preview · Install VYRA to use AI and voice.'}</div></div>`
}
function clips(){return ''}
function projects(){return `<div class="page"><span class="overline">YOUR LIBRARY</span><h1 class="page-heading">Projects</h1><p class="lead">Give VYRA the context behind your work. Add notes and goals, then start a conversation in that project.</p><div class="form-actions">${btn('＋ New project','new-project','primary-btn')}${btn('Export workspace','export-workspace')}${btn('Import backup','import-workspace','ghost-btn')}<input id="workspace-file" type="file" accept=".json" hidden></div><div class="project-grid">${state.projects.length?state.projects.map(p=>`<article class="project-card"><div class="project-symbol">▦</div><h2>${html(p.name)}</h2><p>${html(p.note||'Add notes, goals or reference material.')}</p><small>${html(new Date(p.created).toLocaleDateString())}</small><div class="form-actions"><button class="primary-btn" data-project-chat="${html(p.id)}">Work with VYRA</button><button class="ghost-btn" data-project="${html(p.id)}">Edit notes</button><button class="tinybtn" data-delete-project="${html(p.id)}">Delete</button></div></article>`).join(''):'<div class="empty-state"><h3>Your project library is ready.</h3><p>Create a project to keep its context close to your conversations.</p></div>'}</div></div>`}
function agents(){return `<div class="page"><span class="overline">AUTOMATIONS / AI TASKS</span><h1 class="page-heading">Put your ideas to work.</h1><p class="lead">Create repeatable AI tasks for code review, content drafts, planning and analysis. Every run leaves a result you can read, copy or continue in chat.</p><div class="automation-notice"><span class="signal"></span><div><strong>Runs while VYRA is open</strong><p>Tasks use your OpenAI API billing. One AI task runs at a time, with a run limit and no automatic retries after errors. Social posting is managed separately in Clips Studio.</p></div></div>${state.taskError?`<div class="message-error">${html(state.taskError)}</div>`:''}<div class="form-actions">${btn('＋ New AI task','new-task','primary-btn')}${btn('Refresh activity','refresh-tasks')}${btn('Export task history','export-tasks','ghost-btn')}</div><div class="task-grid">${state.tasks.length?state.tasks.map(t=>{const run=state.runs.find(r=>r.taskId===t.id);const busy=run?.status==='running';return `<article class="task-card"><div class="task-heading"><h2>${html(t.name)}</h2><span class="tag ${busy?'warn':''}">${busy?'RUNNING':t.enabled?'SCHEDULED':'PAUSED'}</span></div><p>${html(t.prompt.slice(0,210))}</p><div class="task-meta">${html(t.mode)} · ${html(t.model)}<br>${t.schedule==='interval'?'Every '+t.intervalMinutes+' minutes':t.schedule==='once'?'One-time':'Manual'} · ${t.runCount}/${t.maxRuns} runs${t.enabled?'<br>Next: '+html(new Date(t.nextRun).toLocaleString()):''}</div><div class="form-actions">${busy?`<button class="secondary-btn" data-task-cancel="${html(t.id)}">Stop</button>`:`<button class="primary-btn" data-task-run="${html(t.id)}" ${t.runCount>=t.maxRuns?'disabled':''}>Run now</button>`}<button class="ghost-btn" data-task-edit="${html(t.id)}">Edit</button>${t.schedule!=='manual'?`<button class="ghost-btn" data-task-toggle="${html(t.id)}">${t.enabled?'Pause':'Resume'}</button>`:''}<button class="tinybtn" data-task-delete="${html(t.id)}" ${busy?'disabled':''}>Delete</button></div>${run?`<small class="last-run">Last run: ${html(run.status)} · ${html(new Date(run.started).toLocaleString())}</small>`:''}</article>`}).join(''):'<div class="empty-state"><h3>Your first automation starts here.</h3><p>Try a daily content brief, recurring project review, or one-time code analysis.</p></div>'}</div><section class="activity-section"><span class="overline">RUN HISTORY</span><h2>Results & activity</h2>${state.runs.length?state.runs.slice(0,30).map(r=>`<details class="run-card" data-run-id="${html(r.id)}" ${(state.runOpen[r.id]??(r.status==='running'||r.id===state.runs[0]?.id))?'open':''}><summary><strong>${html(r.name)}</strong><span>${html(r.status)} · ${html(new Date(r.started).toLocaleString())}</span></summary>${r.error?`<div class="message-error">${html(r.error)}</div>`:''}<div class="run-result">${formatMessage(r.result||'VYRA is working…')}</div>${r.result?`<div class="form-actions"><button class="secondary-btn" data-run-chat="${html(r.id)}">Continue in chat</button><button class="ghost-btn" data-run-copy="${html(r.id)}">Copy result</button></div>`:''}</details>`).join(''):'<p class="lead">Completed and interrupted runs will appear here.</p>'}</section></div>`}
function settings(){return `<div class="page"><span class="overline">SYSTEM / CONNECTIONS</span><h1 class="page-heading">Settings & connections</h1><p class="lead">Connect your own OpenAI API project. The key is never embedded in this executable or published website.</p><div class="settings-grid"><section class="form-panel"><h2>OpenAI Intelligence</h2><p>Bring your own API key to activate VYRA chat and the optional Clips Studio. API charges are separate from a ChatGPT subscription.</p><form id="settings-form"><label class="field-label" for="key">OpenAI API key</label><input id="key" class="field-input" name="key" type="password" autocomplete="new-password" placeholder="sk-…  (leave blank to keep current key)"><p class="info-line">Paste the complete secret value from <a class="answer-link" href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">OpenAI API keys ↗</a>. A key name, ID or hidden preview will not work. Quotes and a Bearer label are handled automatically.</p><div id="connection-feedback" class="connection-feedback ${connectionFeedback.error?'message-error':''}" role="status" aria-live="polite">${html(connectionFeedback.text)}</div><label class="field-label" for="model">AI model</label><select name="model" id="model" class="field-select">${modelOptions(state.model)}</select><label class="field-check"><input name="persist" type="checkbox" checked> Encrypt and remember my key on this Windows account</label><div class="info-line">Windows DPAPI encrypts saved keys for your user account. API calls go directly from the local app to OpenAI, not through the public preview website.</div><div class="form-actions"><button type="button" class="secondary-btn" data-action="load-models">Load my available models</button><button type="submit" class="primary-btn">Save & test connection</button><button type="button" class="secondary-btn" data-action="remove-key">Forget saved key</button></div></form></section><section class="form-panel"><span class="overline">SYSTEM READINESS</span><h2 style="margin-top:16px">Your setup</h2><div class="provider"><div class="provider-mark">✦</div><div><b>OpenAI API</b><small id="settings-ai-status">${state.verified?'Verified':state.configured?'Key saved — press Test connection':'Waiting for your API key'}</small></div><span class="tag">${state.verified?'READY':state.configured?'CHECK':'SETUP'}</span></div><div class="provider"><div class="provider-mark">▷</div><div><b>VYRA Clips</b><small>Python + FFmpeg worker</small></div><span class="tag">LOCAL</span></div><div class="provider"><div class="provider-mark">↗</div><div><b>Social posting</b><small id="settings-social-status">Checking account connections…</small></div><span class="tag warn" id="settings-social-tag">SETUP</span></div><div class="form-actions">${btn('Open Clips Studio','clips','secondary-btn')}${isDesktop?btn('Exit VYRA','quit','ghost-btn'):''}</div><p style="font-size:11px">VYRA runs in its own Windows window with Clips inside. Online AI and social publishing use your connected services.</p></section></div></div>`}
function render(){root.hidden=state.view==='clips';if(clipsContainer)clipsContainer.hidden=state.view!=='clips';root.innerHTML=({home,chat,clips,projects,agents,settings})[state.view]();if(state.view==='agents')refreshTasks(false);if(state.view==='settings'){renderPreferences();refreshSocialStatus()};if(state.view==='chat'){const box=document.querySelector('#messages');if(box)box.scrollTop=box.scrollHeight;const t=document.querySelector('#chat-input');if(t && !state.pending)t.focus()};if(state.view==='clips')checkClips(); if(state.view==='settings'){const page=root.querySelector('.page');if(page){const section=document.createElement('section');section.className='form-panel';section.style.marginTop='20px';section.innerHTML=`<h2>Updates &amp; connection test</h2><p>VYRA checks for updates automatically. Installing an update requires your approval. The installer replaces app files but keeps your saved OpenAI key and chats.</p><div id="updates-status" class="info-line">Checking for updates…</div><div class="form-actions"><button class="secondary-btn" data-action="check-updates">Check for updates</button><button class="primary-btn" id="install-update-btn" data-action="install-update" hidden>Install available update</button><button class="secondary-btn" data-action="test-openai">Test OpenAI connection</button></div><p style="font-size:12px">Need an API key? <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener noreferrer">Create one in OpenAI</a>. API billing is separate from ChatGPT.</p>`;page.appendChild(section);refreshUpdates()}}}
async function refreshSocialStatus(){if(!isDesktop)return;try{const data=await request('/api/clips/status');const status=document.querySelector('#settings-social-status'),tag=document.querySelector('#settings-social-tag');if(!status||!tag)return;const labels={youtube:'YouTube',instagram:'Instagram',facebook:'Facebook',tiktok:'TikTok'};const names=(data.connected||[]).map(name=>labels[name]).filter(Boolean);status.textContent=names.length?'Connected: '+names.join(', '):data.running?'Connect your accounts in Clips Studio':'Open Clips Studio to check your accounts';tag.textContent=names.length?'CONNECTED':'SETUP';tag.classList.toggle('warn',!names.length)}catch{}}
let statusRequest=null;
async function refreshStatus(quiet=false){
 if(!isDesktop){document.querySelector('#runtime-label').textContent='WEBSITE PREVIEW';return}
 if(statusRequest)return statusRequest;
 statusRequest=(async()=>{try{
  const d=await request('/api/status');state.configured=d.openai;state.verified=d.verified;state.model=d.model;state.worker=d.worker;
  const badge=document.querySelector('#top-status');badge.innerHTML=`<span class="status-led"></span> ${d.verified?'OpenAI verified':d.openai?'OpenAI key saved · test it':'OpenAI not connected'}`;badge.classList.toggle('ready',d.verified);
  if(state.view==='settings')refreshSocialStatus();
  const detail=document.querySelector('#settings-ai-status');if(detail){detail.textContent=d.verified?'Verified':d.openai?'Key saved — press Test connection':'Waiting for your API key';detail.closest('.provider').querySelector('.tag').textContent=d.verified?'READY':d.openai?'CHECK':'SETUP'}
 }catch(e){if(!quiet)toast(e.message)}finally{statusRequest=null}})();
 return statusRequest;
}
// A key saved in another VYRA window should appear without restarting the app.
window.addEventListener('focus',()=>refreshStatus(true));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshStatus(true)});
setInterval(()=>{if(!document.hidden)refreshStatus(true)},15000);
let clipsContainer=null,clipsLoading=false;
function mountClips(){
 if(!clipsContainer){clipsContainer=document.createElement('section');clipsContainer.className='main-content clips-embedded';clipsContainer.innerHTML=`<div class="studio-toolbar"><div><strong>VYRA Clips</strong><span id="clips-state" role="status">Opening your studio…</span></div><div>${btn('Repair video tools','clips-setup','ghost-btn')}${btn('Reload studio','launch-clips','ghost-btn')}</div></div><div id="studio-content" class="studio-content"><div class="studio-loading"><span class="msg-icon spin">✦</span><h2>Your creative workspace is opening.</h2><p>Clips, captions, exports and your connected accounts live right here.</p></div></div>`;root.after(clipsContainer)}
 clipsContainer.hidden=state.view!=='clips';return clipsContainer;
}
async function checkClips(){mountClips();if(!clipsContainer.querySelector('iframe')&&!clipsLoading)await runClips()}
async function watchVideoSetup(){
 try{const data=await request('/api/clips/status');mountClips();clipsContainer.querySelector('#clips-state').textContent=data.setup?.detail||'Preparing video tools…';if(data.setup?.state==='running')setTimeout(watchVideoSetup,2000);else if(data.setup?.state==='ready')await runClips();else if(data.setup?.state==='failed')toast(data.setup.detail)}catch(e){toast(e.message)}
}
async function openWebLink(url){
 const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol))return;
 if(window.VYRA_NATIVE)await request('/api/open-external','POST',{url:parsed.href});else window.open(parsed.href,'_blank','noopener,noreferrer');
}
window.addEventListener('message',event=>{
 const frame=clipsContainer?.querySelector('iframe');
 if(event.origin!=='http://127.0.0.1:8765'||event.source!==frame?.contentWindow||event.data?.type!=='vyra.openExternal'||typeof event.data.url!=='string')return;
 openWebLink(event.data.url).catch(e=>toast(e.message));
});
document.addEventListener('click',event=>{const link=event.target.closest('a[href]');if(!window.VYRA_NATIVE||!link)return;try{const url=new URL(link.href);if(['https:','http:'].includes(url.protocol)&&url.origin!==location.origin){event.preventDefault();openWebLink(url.href).catch(e=>toast(e.message))}}catch{}},true);

let answerController=null;
async function submitChat(e){
 e?.preventDefault();if(state.pending)return;
 const value=document.querySelector('#chat-input')?.value.trim();if(!value)return;
 if(!state.configured){toast('Connect OpenAI in Settings first.');layout('settings');return}
 stopVoice(true);stopSpeaking();
 let c=getChat()||createChat();c.messages.push({role:'user',content:value});
 if(c.title==='New conversation')c.title=value.slice(0,45);
 if(state.attachments.length)c.referenceFiles=state.attachments.map(f=>({...f}));const context=projectContext(c);state.pending=true;state.draft='';state.streamText='';save();renderHistory();render();
 answerController=new AbortController();let answer='',complete=false,failure='';
 try{
  const res=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json','X-VYRA-SESSION':csrf},body:JSON.stringify({messages:c.messages.map(({role,content})=>({role,content})),mode:state.mode,context}),signal:answerController.signal});
  if(!res.ok){const d=await res.json();throw Error(d.error||'Could not start the reply.')}
  const reader=res.body.getReader(),decoder=new TextDecoder();let buffer='';
  const event=line=>{
   if(!line.trim())return;const d=JSON.parse(line);
   if(d.type==='delta'){answer+=d.text;state.streamText=answer;const el=document.querySelector('#stream-answer');if(el)el.textContent=answer;const box=document.querySelector('#messages');if(box)box.scrollTop=box.scrollHeight}
   if(d.type==='status'&&!answer){const el=document.querySelector('#stream-answer');if(el)el.textContent=d.text}
   if(d.type==='answer'){answer=d.text;state.streamText=answer;const el=document.querySelector('#stream-answer');if(el)el.innerHTML=formatMessage(answer)}
   if(d.type==='done')complete=true;if(d.type==='error')throw Error(d.text);
  };
  try{while(true){const {value:chunk,done}=await reader.read();if(done)break;buffer+=decoder.decode(chunk,{stream:true});let i;while((i=buffer.indexOf('\n'))>=0){event(buffer.slice(0,i));buffer=buffer.slice(i+1)}}buffer+=decoder.decode();if(buffer.trim())event(buffer)}finally{reader.releaseLock()}
  if(!complete)throw Error('The connection ended early. Your partial reply has been saved.');
 }catch(err){failure=err.name==='AbortError'?'Stopped by you.':err.message}
 finally{
  if(answer.trim())c.messages.push({role:'assistant',content:answer,...(failure?{error:failure}:{})});
  else if(failure)toast(failure);
  state.pending=false;answerController=null;state.attachments=[];save();if(state.view==='chat')render();
  if(complete&&answer&&state.prefs.speakReplies)speakText(answer);
 }
}
function showConnectionFeedback(text,error=false){connectionFeedback={text,error};const el=document.querySelector('#connection-feedback');if(el){el.textContent=text;el.classList.toggle('message-error',error)}}
async function testConnection(){
 showConnectionFeedback('Checking your saved key with OpenAI…');
 try{const data=await request('/api/openai/test','POST',{});showConnectionFeedback(data.message||'Connected to OpenAI.');await refreshStatus();return true}
 catch(error){showConnectionFeedback(error.message,true);return false}
}
async function submitSettings(e){
 e.preventDefault();const form=e.target,button=form.querySelector('button[type="submit"]');if(button.disabled)return;button.disabled=true;
 const value={key:form.elements.namedItem('key').value,model:form.elements.namedItem('model').value,persist:form.elements.namedItem('persist').checked};
 showConnectionFeedback('Saving your connection securely on this computer…');
 try{await request('/api/settings','POST',value);form.elements.namedItem('key').value='';await refreshStatus();const connected=await testConnection();toast(connected?'OpenAI connected.':'Key saved. See the connection message for the next step.')}
 catch(error){showConnectionFeedback(error.message,true);toast('Connection needs attention. See the message below the key field.')}
 finally{button.disabled=false}
}
async function runClips(){
 if(clipsLoading)return;mountClips();clipsLoading=true;const status=clipsContainer.querySelector('#clips-state');status.textContent='Starting your studio…';
 try{const data=await request('/api/clips/launch','POST',{});if(data.preparing){watchVideoSetup();return}const url=new URL(data.url);if(url.origin!=='http://127.0.0.1:8765')throw Error('Unexpected studio address.');const content=clipsContainer.querySelector('#studio-content');let frame=content.querySelector('iframe');if(!frame){frame=document.createElement('iframe');frame.title='VYRA Clips Studio';frame.allow='clipboard-write';content.replaceChildren(frame)}frame.src=url.origin+'/?embedded=1';status.textContent='Your studio · saved accounts · local processing';}
 catch(e){status.textContent=e.message;if(!clipsContainer.querySelector('iframe'))clipsContainer.querySelector('#studio-content').innerHTML=`<div class="studio-loading"><h2>Let’s finish opening Clips.</h2><p>${html(e.message)}</p>${btn('Try again','launch-clips','primary-btn')}${btn('Set up video tools','clips-setup','secondary-btn')}</div>`}
 finally{clipsLoading=false}
}
async function quit(){try{await request('/api/quit','POST',{});toast('VYRA is closing. You can close this window.')}catch(e){toast(e.message)}}
let cachedUpdate=null;async function refreshUpdates(){if(!isDesktop)return;try{showUpdate(await request('/api/updates'))}catch{}}function showUpdate(d){cachedUpdate=d;const el=document.querySelector('#updates-status');if(el)el.textContent=d.available?'Update v'+d.latest+' available — '+(d.notes||'New release'):d.error?'Update check: '+d.error:'Installed v'+(d.version||'1.2.0')+(d.lastChecked?' — last checked '+new Date(d.lastChecked).toLocaleString():' — checking online…');const button=document.querySelector('#install-update-btn');if(button)button.hidden=!d.available}
const actions={'test-openai':async()=>{const form=document.querySelector('#settings-form');if(form?.elements.namedItem('key').value.trim())await submitSettings({target:form,preventDefault(){}});else await testConnection()},'check-updates':async()=>{try{const d=await request('/api/updates/check','POST',{});showUpdate(d);toast(d.available?'Update available: '+d.latest:d.error?'Update check failed':d.latest?'VYRA is up to date':'No published update found')}catch(e){toast(e.message)}},'install-update':async()=>{if(!confirm('Download the verified VYRA installer and restart to update?'))return;try{toast('Downloading and verifying update…');await request('/api/updates/install','POST',{});toast('Updating VYRA. The app will reopen when installation completes.')}catch(e){toast(e.message)}},home:()=>layout('home'),chat:()=>layout('chat'),clips:()=>layout('clips'),projects:()=>layout('projects'),agents:()=>layout('agents'),settings:()=>layout('settings'),'new-chat':()=>createChat(),'new-project':()=>{const v=prompt('New project name:');if(v?.trim()){state.projects.unshift({id:uid(),name:v.trim().slice(0,80),note:'',created:date()});save();render();toast('Project created.')}} ,'clips-setup':async()=>{try{await request('/api/clips/setup','POST',{});toast('Installing video tools inside VYRA…');watchVideoSetup()}catch(e){toast(e.message)}},'launch-clips':runClips,'remove-key':async()=>{if(!confirm('Forget the locally saved OpenAI key?'))return;try{await request('/api/settings/key','DELETE',{});state.configured=false;await refreshStatus();render();toast('Saved OpenAI key removed.')}catch(e){toast(e.message)}},quit,'clear-history':()=>{if(confirm('Delete all saved conversation history on this device?')){state.chats=[];state.active=null;save();renderHistory();render();}}};
// Readable rendering for text and fenced code; model output never becomes HTML.
function formatMessage(text){
 const prose=part=>{let out='',offset=0;const links=/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;for(const match of part.matchAll(links)){out+=html(part.slice(offset,match.index));try{const url=new URL(match[2]);if(!url.hostname||url.username||url.password)throw Error();out+=`<a class="answer-link" href="${html(url.href)}" target="_blank" rel="noopener noreferrer">${html(match[1])}</a>`}catch{out+=html(match[0])}offset=match.index+match[0].length}out+=html(part.slice(offset));return out.replace(/^#{1,4} (.+)$/gm,'<strong class="answer-heading">$1</strong>').replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>')};
 return String(text||'').split(/```/).map((part,i)=>i%2?`<pre class="code-block"><code>${html(part.replace(/^[\w.+#-]*\n/,''))}</code></pre>`:`<span class="prose">${prose(part)}</span>`).join('');
}
function modeOptions(selected){return [['assistant','Everyday'],['code','Code partner'],['creator','Content creator'],['planner','Project planner'],['research','Research & sources']].map(([id,name])=>`<option value="${id}" ${id===selected?'selected':''}>${name}</option>`).join('')}
function modelOptions(selected){return [...new Set([selected,...state.models,'gpt-6-astra','gpt-5-mini','gpt-4o-mini'])].filter(Boolean).map(m=>`<option value="${html(m)}" ${m===selected?'selected':''}>${html(m)}</option>`).join('')}
function projectContext(conversation=getChat()){
 const p=state.projects.find(p=>p.id===state.projectId);
 return [p?`PROJECT: ${p.name}\nNOTES: ${p.note||''}`:'',...(state.attachments.length?state.attachments:conversation?.referenceFiles||[]).map(f=>`FILE: ${f.name}\n${f.text}`)].filter(Boolean).join('\n\n').slice(0,380000);
}
function downloadText(name,text,type='text/plain'){
 const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function copyText(text){try{await navigator.clipboard.writeText(text);toast('Copied.')}catch{toast('Copy is unavailable. Select the text and use Ctrl+C.')}}
function exportChat(){const c=getChat();if(!c)return;downloadText(`VYRA-${c.title.replace(/[^a-zA-Z0-9 -]/g,'').slice(0,45)||'conversation'}.md`,`# ${c.title}\n\n${c.messages.map(m=>`## ${m.role==='user'?'You':'VYRA'}\n\n${m.content}${m.error?'\n\n[Partial reply: '+m.error+']':''}`).join('\n\n')}`)}

const voiceState={active:false,recognition:null,recorder:null,stream:null,utterance:null,generation:0,timer:null,recordTimer:null};
function showVoice(text,label){const panel=document.querySelector('#voice-overlay');panel.hidden=false;document.querySelector('#voice-label').textContent=label;document.querySelector('#voice-caption').textContent=text;panel.classList.add('active')}
function stopSpeaking(){voiceState.generation++;clearTimeout(voiceState.timer);voiceState.utterance=null;if('speechSynthesis' in window)speechSynthesis.cancel()}
function stopVoice(discard=false){
 const rec=voiceState.recognition;voiceState.recognition=null;if(rec){rec.onend=null;discard?rec.abort():rec.stop()}
 if(voiceState.recorder&&voiceState.recorder.state!=='inactive'){voiceState.recorder.discard=discard;voiceState.recorder.stop()}
 voiceState.stream?.getTracks().forEach(t=>t.stop());voiceState.stream=null;voiceState.active=false;clearTimeout(voiceState.recordTimer);
 const input=document.querySelector('#chat-input');if(input)input.readOnly=false;updateVoiceButtons();
}
function closeVoice(){stopVoice(true);stopSpeaking();document.querySelector('#voice-overlay').hidden=true}
function updateVoiceButtons(){document.querySelectorAll('[data-action="dictate"],[data-action="record"]').forEach(b=>{b.classList.toggle('listening',voiceState.active);b.textContent=voiceState.active?'■ Stop microphone':b.dataset.action==='dictate'?'◉ Live dictation':'● Record'})}
function startDictation(){
 if(voiceState.active){stopVoice();return}
 if(!isDesktop){toast('Install VYRA to use microphone input.');return}
 const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
 if(!Recognition){toast('Live dictation is unavailable in this browser. Use Record for OpenAI transcription.');return}
 stopSpeaking();const input=document.querySelector('#chat-input');if(!input)return;
 const prefix=input.value.trim();let finalText='';const rec=new Recognition();rec.lang=state.prefs.language||'en-US';rec.continuous=true;rec.interimResults=true;
 voiceState.recognition=rec;voiceState.active=true;input.readOnly=true;
 showVoice('Speak naturally. Your words appear here as you talk.','YOU · LIVE DICTATION');updateVoiceButtons();
 rec.onresult=e=>{let interim='';for(let i=e.resultIndex;i<e.results.length;i++){if(e.results[i].isFinal)finalText+=e.results[i][0].transcript+' ';else interim+=e.results[i][0].transcript}const text=[prefix,finalText.trim(),interim].filter(Boolean).join(' ');input.value=text;state.draft=text;showVoice(finalText+interim,'YOU · LIVE DICTATION')};
 rec.onerror=e=>{toast(e.error==='not-allowed'?'Allow microphone access in the VYRA window to dictate.':'Live dictation could not start. Use Record to transcribe with OpenAI.');stopVoice(true);document.querySelector('#voice-label').textContent='MICROPHONE STOPPED'};
 rec.onend=()=>{voiceState.recognition=null;voiceState.active=false;input.readOnly=false;updateVoiceButtons();document.querySelector('#voice-label').textContent='YOU · REVIEW BEFORE SENDING'};
 try{rec.start()}catch{stopVoice(true);toast('Microphone could not start. Try Record.')}
}
async function recordMessage(){
 if(voiceState.active){stopVoice();return}
 if(!isDesktop||!state.configured){toast('Connect OpenAI in the installed app to transcribe a recording.');return}
 if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){toast('This browser cannot record audio. Type your message instead.');return}
 stopSpeaking();let stream;
 try{stream=await navigator.mediaDevices.getUserMedia({audio:true})}catch{toast('Microphone access was denied or unavailable.');return}
 const chunks=[];const mime=MediaRecorder.isTypeSupported('audio/webm;codecs=opus')?'audio/webm;codecs=opus':MediaRecorder.isTypeSupported('audio/mp4')?'audio/mp4':'';
 const rec=new MediaRecorder(stream,mime?{mimeType:mime}:undefined);voiceState.recorder=rec;voiceState.stream=stream;voiceState.active=true;
 const prefix=document.querySelector('#chat-input')?.value.trim()||'';let size=0;
 rec.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);size+=e.data.size;if(size>10*1024*1024)stopVoice()}};
 rec.onstop=async()=>{
  stream.getTracks().forEach(t=>t.stop());voiceState.recorder=null;voiceState.stream=null;voiceState.active=false;clearTimeout(voiceState.recordTimer);updateVoiceButtons();
  if(rec.discard)return;
  const blob=new Blob(chunks,{type:rec.mimeType||'audio/webm'});if(!blob.size){toast('Recording was empty. Try again.');return}
  showVoice('Turning your recording into text…','YOU · TRANSCRIBING');
  try{const form=new FormData();form.append('audio',blob,rec.mimeType?.includes('mp4')?'recording.mp4':'recording.webm');const res=await fetch('/api/voice/transcribe',{method:'POST',headers:{'X-VYRA-SESSION':csrf},body:form});const d=await res.json();if(!res.ok)throw Error(d.error||'Transcription failed.');state.draft=[prefix,d.Text||d.text].filter(Boolean).join(' ');const input=document.querySelector('#chat-input');if(input)input.value=state.draft;showVoice(d.Text||d.text,'YOU · REVIEW BEFORE SENDING')}catch(e){showVoice(e.message,'VOICE ERROR');toast(e.message)}
 };
 rec.onerror=()=>{rec.discard=true;stopVoice(true);toast('Recording failed. Try again.')};
 rec.start(1000);voiceState.recordTimer=setTimeout(()=>{stopVoice();toast('Recording stopped at two minutes.')},120000);showVoice('Recording your microphone. Press Stop to transcribe, then review before sending.','YOU · RECORDING');updateVoiceButtons();
}
function speakText(text){
 if(!('speechSynthesis' in window)){toast('Read aloud is unavailable in this browser.');return}
 stopVoice(true);stopSpeaking();const generation=voiceState.generation;
 const spoken=String(text).replace(/```[\s\S]*?```/g,' [Code is shown in the conversation.] ').replace(/[*#`]/g,'').trim();
 if(!spoken)return;
 const chunks=spoken.match(/[^.!?]+[.!?]+\s*|[^.!?]+$/g)||[spoken];
 let index=0;
 function next(){
  if(generation!==voiceState.generation)return;
  if(index>=chunks.length){document.querySelector('#voice-label').textContent='VYRA · FINISHED SPEAKING';document.querySelector('#voice-overlay').classList.remove('active');return}
  const chunk=chunks[index++];const u=new SpeechSynthesisUtterance(chunk);u.lang=state.prefs.language||'en-US';u.rate=1;
  const voices=speechSynthesis.getVoices();const selected=voices.find(v=>v.voiceURI===state.prefs.voice)||voices.find(v=>v.lang===u.lang&&v.localService)||voices.find(v=>v.lang.startsWith(u.lang.split('-')[0]));if(selected)u.voice=selected;
  voiceState.utterance=u;showVoice(chunk,'VYRA · SYNTHESIZED VOICE');
  // Word highlighting follows speech-engine boundaries. If the engine supplies
  // no boundaries, the full sentence stays visible; no invented timestamps.
  u.onboundary=e=>{if(generation!==voiceState.generation||e.name!=='word')return;const start=e.charIndex,end=start+(e.charLength||chunk.slice(start).search(/\s|$/));const target=document.querySelector('#voice-caption');target.innerHTML=html(chunk.slice(0,start))+`<mark>${html(chunk.slice(start,end||chunk.length))}</mark>`+html(chunk.slice(end||chunk.length))};
  u.onend=next;u.onerror=e=>{if(generation!==voiceState.generation||e.error==='interrupted'||e.error==='canceled')return;toast('Voice playback stopped. Your text is still in the conversation.');document.querySelector('#voice-label').textContent='VOICE STOPPED'};
  speechSynthesis.speak(u);
 }
 next();
}
function renderPreferences(){
 const page=root.querySelector('.page');if(!page)return;
 const section=document.createElement('section');section.className='form-panel preference-panel';section.innerHTML=`<span class="overline">MAKE VYRA YOURS</span><h2>Research, voice & personal instructions</h2><form id="preferences-form"><label class="field-check"><input type="checkbox" name="webSearch" ${state.prefs.webSearch!==false?'checked':''}> Search the web when helpful, with clickable sources</label><label class="field-check"><input type="checkbox" name="speakReplies" ${state.prefs.speakReplies?'checked':''}> Read completed replies aloud with on-screen captions</label><label class="field-label" for="voice-language">Speech language</label><select id="voice-language" class="field-select" name="language">${[['en-US','English (US)'],['en-GB','English (UK)'],['es-US','Spanish (US)'],['es-ES','Spanish (Spain)'],['fr-FR','French'],['pt-BR','Portuguese'],['de-DE','German']].map(([id,label])=>`<option value="${id}" ${state.prefs.language===id?'selected':''}>${label}</option>`).join('')}</select><label class="field-label" for="voice-choice">Read-aloud voice</label><select id="voice-choice" name="voice" class="field-select"><option value="">Automatic voice</option>${(window.speechSynthesis?.getVoices()||[]).map(v=>`<option value="${html(v.voiceURI)}" ${state.prefs.voice===v.voiceURI?'selected':''}>${html(v.name)} · ${html(v.lang)}</option>`).join('')}</select><label class="field-label" for="personal-instructions">What should VYRA remember about how you work?</label><textarea id="personal-instructions" name="instructions" class="field-input" rows="5" maxlength="4000" placeholder="My projects, preferences, coding style, and how I like responses…">${html(state.prefs.instructions)}</textarea><div class="info-line">Live dictation uses the browser's speech service when supported. Record sends microphone audio to OpenAI after you stop. Read aloud uses your browser's voices and displays the spoken sentence, highlighting words when the voice supports timing.</div><div class="form-actions"><button class="primary-btn" type="submit">Save preferences</button><button class="secondary-btn" type="button" data-action="test-voice">Try voice & captions</button></div></form>`;page.appendChild(section);
}
async function refreshTasks(renderPage=true){
 if(!isDesktop)return;
 try{const d=await request('/api/tasks');state.tasks=d.tasks||[];state.runs=d.runs||[];state.taskError=d.error||'';if(renderPage&&state.view==='agents')root.innerHTML=agents()}catch(e){if(renderPage)toast(e.message)}
}
const taskExamples=[
 {name:'Daily content ideas',mode:'creator',prompt:'Using my project context, create three original short-form video ideas. For each, give a hook, 30-second script, visual plan and caption. Explain which idea to make first.'},
 {name:'Project progress review',mode:'planner',prompt:'Review my project notes. Identify the most important unresolved decisions, risks and next actions. Create a practical checklist for the next work session.'},
 {name:'Code quality review',mode:'code',prompt:'Study the supplied code and project context. Identify real bugs, failure cases, and security or reliability gaps. Prioritize the findings, provide complete fixes and describe how to verify them. Be explicit if the context contains no code.'},
 {name:'Writing and analysis',mode:'research',prompt:'Analyze my reference material. Summarize the main evidence, identify contradictions and uncertainty, and give a clear recommendation grounded in the material.'}
];
function taskEditor(id){
 if(!isDesktop){toast('Install VYRA to create AI tasks.');return}
 const task=state.tasks.find(t=>t.id===id)||{name:'',prompt:'',mode:'assistant',model:state.model,schedule:'manual',intervalMinutes:1440,nextRun:'',enabled:false,maxRuns:10,context:projectContext()};
 const dialog=document.querySelector('#task-dialog');dialog.dataset.id=id||'';const when=task.nextRun&&!task.nextRun.startsWith('0001')?new Date(task.nextRun):new Date(Date.now()+3600000);const local=new Date(when.getTime()-when.getTimezoneOffset()*60000).toISOString().slice(0,16);
 dialog.innerHTML=`<div class="dialog-heading"><div><span class="overline">AI TASK</span><h2 id="task-dialog-title">${id?'Edit task':'Create a repeatable workflow'}</h2></div><button type="button" class="ghost-btn" data-action="close-task">×</button></div><form id="task-form"><label class="field-label" for="task-example">Start with an example</label><select id="task-example" class="field-select"><option value="">Custom task</option>${taskExamples.map((x,i)=>`<option value="${i}">${html(x.name)}</option>`).join('')}</select><label class="field-label" for="task-name">Name</label><input id="task-name" name="name" class="field-input" maxlength="100" required value="${html(task.name)}"><label class="field-label" for="task-prompt">Instructions</label><textarea id="task-prompt" name="prompt" class="field-input" rows="5" maxlength="128000" required>${html(task.prompt)}</textarea><div class="dialog-grid"><label class="field-label">Mode<select name="mode" class="field-select">${modeOptions(task.mode)}</select></label><label class="field-label">Model<select name="model" class="field-select">${modelOptions(task.model)}</select></label><label class="field-label">Schedule<select name="schedule" class="field-select"><option value="manual" ${task.schedule==='manual'?'selected':''}>Manual only</option><option value="once" ${task.schedule==='once'?'selected':''}>One-time</option><option value="interval" ${task.schedule==='interval'?'selected':''}>Recurring</option></select></label><label class="field-label">Every (minutes)<input name="intervalMinutes" class="field-input" type="number" min="60" max="10080" value="${task.intervalMinutes||1440}"></label><label class="field-label">Next run<input name="nextRun" class="field-input" type="datetime-local" value="${local}"></label><label class="field-label">Maximum total runs<input name="maxRuns" class="field-input" type="number" min="1" max="100" value="${task.maxRuns}" required></label></div><label class="field-label" for="task-context">Reference context (a snapshot for this task)</label><textarea id="task-context" name="context" class="field-input" rows="4" maxlength="45000">${html(task.context||'')}</textarea><label class="field-check"><input name="enabled" type="checkbox" ${task.enabled?'checked':''}> Enable the schedule while VYRA is open</label><p class="info-line">Each run sends these instructions and reference context to OpenAI and uses your API billing. The task produces a draft or analysis for review. Missed runs are combined into one run when VYRA reopens.</p><div class="form-actions"><button class="primary-btn" type="submit">Save task</button><button class="ghost-btn" type="button" data-action="close-task">Cancel</button></div></form>`;dialog.showModal();
}
async function saveTask(e){
 e.preventDefault();const form=e.target,dialog=document.querySelector('#task-dialog');const data=Object.fromEntries(new FormData(form));data.enabled=form.elements.enabled.checked;data.intervalMinutes=Number(data.intervalMinutes);data.maxRuns=Number(data.maxRuns);data.nextRun=data.nextRun?new Date(data.nextRun).toISOString():'0001-01-01T00:00:00Z';
 try{await request('/api/tasks'+(dialog.dataset.id?'/'+dialog.dataset.id:''),dialog.dataset.id?'PUT':'POST',data);dialog.close();await refreshTasks();toast('Task saved.')}catch(e){toast(e.message)}
}
async function initialize(){
 if(isDesktop){
  try{state.prefs=await request('/api/preferences');const stored=await request('/api/workspace');if(Array.isArray(stored.chats)){state.chats=stored.chats;state.projects=stored.projects||[];state.active=stored.active||null;state.projectId=stored.projectId||'';state.mode=stored.mode||'assistant'}workspaceLoaded=true;save()}catch(e){toast(e.message)}
 }
 await refreshStatus();await refreshTasks(false);renderHistory();layout(location.hash==='#clips'?'clips':'home');
 if(window.speechSynthesis)speechSynthesis.getVoices();
 setInterval(()=>{if(state.view==='agents'&&!document.querySelector('#task-dialog').open)refreshTasks()},5000);
}
Object.assign(actions,{
 'dictate':startDictation,'record':recordMessage,'stop-voice':closeVoice,
 'test-voice':()=>speakText('Hey, I’m VYRA. Your words and my replies stay visible while we speak. Let’s build something great.'),
 'read-reply':()=>{const m=getChat()?.messages.filter(m=>m.role==='assistant').at(-1);if(m)speakText(m.content)},
 'stop-answer':()=>answerController?.abort(),
 'attach-code':()=>document.querySelector('#code-files')?.click(),
 'export-chat':exportChat,
 'export-workspace':()=>downloadText('VYRA-workspace.json',JSON.stringify(workspaceData(),null,2),'application/json'),
 'import-workspace':()=>document.querySelector('#workspace-file')?.click(),
 'new-task':()=>taskEditor(),
 'close-task':()=>document.querySelector('#task-dialog').close(),
 'refresh-tasks':()=>refreshTasks(),
 'export-tasks':()=>downloadText('VYRA-task-history.json',JSON.stringify({tasks:state.tasks,runs:state.runs},null,2),'application/json'),
 'load-models':async()=>{try{toast('Loading models from your API project…');const d=await request('/api/models');state.models=d.models;render();toast('Available models loaded. Choose one and save.')}catch(e){toast(e.message)}}
});
document.addEventListener('click',async e=>{
 const n=e.target.closest('[data-remove-file],[data-copy-message],[data-read-message],[data-project-chat],[data-delete-project],[data-task-run],[data-task-edit],[data-task-delete],[data-task-toggle],[data-task-cancel],[data-run-chat],[data-run-copy]');if(!n)return;
 try{
  if(n.dataset.removeFile!==undefined){state.draft=document.querySelector('#chat-input')?.value||'';if(!state.attachments.length)state.attachments=(getChat()?.referenceFiles||[]).map(f=>({...f}));state.attachments.splice(Number(n.dataset.removeFile),1);if(getChat())getChat().referenceFiles=state.attachments.map(f=>({...f}));save();render()}
  if(n.dataset.copyMessage!==undefined)await copyText(getChat().messages[Number(n.dataset.copyMessage)].content);
  if(n.dataset.readMessage!==undefined)speakText(getChat().messages[Number(n.dataset.readMessage)].content);
  if(n.dataset.projectChat){if(state.pending){toast('Stop or finish the current reply first.');return}state.projectId=n.dataset.projectChat;createChat()}
  if(n.dataset.deleteProject&&confirm('Delete this project and its saved notes?')){state.projects=state.projects.filter(p=>p.id!==n.dataset.deleteProject);if(state.projectId===n.dataset.deleteProject)state.projectId='';save();render()}
  if(n.dataset.taskEdit)taskEditor(n.dataset.taskEdit);
  if(n.dataset.taskRun){await request('/api/tasks/'+n.dataset.taskRun+'/run','POST',{});await refreshTasks();toast('VYRA is working. The result will appear in activity.')}
  if(n.dataset.taskCancel){await request('/api/tasks/'+n.dataset.taskCancel+'/cancel','POST',{});await refreshTasks();toast('Stopping task…')}
  if(n.dataset.taskDelete&&confirm('Delete this task? Its run history will stay available.')){await request('/api/tasks/'+n.dataset.taskDelete,'DELETE',{});await refreshTasks()}
  if(n.dataset.taskToggle){const t=state.tasks.find(t=>t.id===n.dataset.taskToggle);const next=(!t.enabled&&new Date(t.nextRun)<new Date())?new Date(Date.now()+60000).toISOString():t.nextRun;await request('/api/tasks/'+t.id,'PUT',{...t,enabled:!t.enabled,nextRun:next});await refreshTasks()}
  if(n.dataset.runCopy){const r=state.runs.find(r=>r.id===n.dataset.runCopy);await copyText(r.result)}
  if(n.dataset.runChat){if(state.pending){toast('Stop or finish the current reply first.');return}const r=state.runs.find(r=>r.id===n.dataset.runChat),t=state.tasks.find(t=>t.id===r.taskId);const c=createChat();c.title=r.name;c.messages=[{role:'user',content:t?.prompt||r.name},{role:'assistant',content:r.result}];if(t?.context)state.attachments=[{name:'Task reference context',text:t.context}];save();renderHistory();render()}
 }catch(err){toast(err.message)}
});
document.addEventListener('toggle',e=>{if(e.target.matches('details[data-run-id]'))state.runOpen[e.target.dataset.runId]=e.target.open},true);
document.addEventListener('change',async e=>{
 if(e.target.id==='chat-mode'){state.mode=e.target.value;save()}
 if(e.target.id==='chat-project'){state.projectId=e.target.value;save();state.draft=document.querySelector('#chat-input')?.value||'';render()}
 if(e.target.id==='task-example'&&e.target.value!==''){const x=taskExamples[Number(e.target.value)],f=document.querySelector('#task-form');f.elements.name.value=x.name;f.elements.prompt.value=x.prompt;f.elements.mode.value=x.mode}
 if(e.target.id==='code-files'){
  const files=Array.from(e.target.files||[]);let budget=state.attachments.reduce((n,f)=>n+f.text.length,0);const rejected=[];
  for(const f of files){if(f.size>120000||state.attachments.length>=8||/^(\.env|.*\.(pem|key|p12|pfx))$/i.test(f.name)){rejected.push(f.name);continue}const text=await f.text();if(text.includes('\0')||budget+text.length>30000){rejected.push(f.name);continue}state.attachments.push({name:f.name,text});budget+=text.length}
  state.draft=document.querySelector('#chat-input')?.value||'';render();toast(rejected.length?'Skipped files that are too large, private, or not text: '+rejected.join(', '):'Files attached. They will be included with your next message.');
 }
 if(e.target.id==='workspace-file'){
  const f=e.target.files?.[0];if(!f)return;
  try{if(f.size>1800000)throw Error('Backup is too large.');const d=JSON.parse(await f.text());if(!Array.isArray(d.chats)||!Array.isArray(d.projects)||d.chats.length>80||d.projects.length>100)throw Error('Invalid VYRA backup.');if(!confirm('Replace this device’s workspace with the selected backup? Export your current workspace first if you need it.'))return;state.chats=d.chats;state.projects=d.projects;state.active=d.active||null;state.projectId=d.projectId||'';save();renderHistory();render();toast('Workspace imported.')}catch(e){toast(e.message)}
 }
});
document.addEventListener('submit',async e=>{
 if(e.target.id==='task-form')saveTask(e);
 if(e.target.id==='preferences-form'){e.preventDefault();const f=e.target;const p={model:state.model,webSearch:f.elements.webSearch.checked,instructions:f.elements.instructions.value,speakReplies:f.elements.speakReplies.checked,language:f.elements.language.value,voice:f.elements.voice.value};try{state.prefs=await request('/api/preferences','PUT',p);toast('Preferences saved.')}catch(e){toast(e.message)}}
});
window.addEventListener('beforeunload',()=>{stopVoice(true);stopSpeaking();if(workspaceLoaded&&isDesktop)fetch('/api/workspace',{method:'PUT',headers:{'Content-Type':'application/json','X-VYRA-SESSION':csrf},body:JSON.stringify(workspaceData()),keepalive:true}).catch(()=>{})});

document.addEventListener('click',e=>{const n=e.target.closest('[data-action],[data-view],[data-chat],[data-prompt],[data-project]');if(!n)return;if(n.dataset.action){const f=actions[n.dataset.action];if(f)f();return}if(n.dataset.view){layout(n.dataset.view);return}if(n.dataset.chat){if(state.pending){toast('Stop or finish the current reply before switching conversations.');return}state.active=n.dataset.chat;save();layout('chat');return}if(n.dataset.prompt){if(n.dataset.mode)state.mode=n.dataset.mode;if(!state.active)createChat();else layout('chat');const t=document.querySelector('#chat-input');if(!t||state.pending)return;t.value=n.dataset.prompt;t.focus();return}if(n.dataset.project){const p=state.projects.find(x=>x.id===n.dataset.project);if(p){const note=prompt('Notes for '+p.name,p.note||'');if(note!==null){p.note=note.slice(0,15000);save();render()}}}});
document.addEventListener('submit',e=>{if(e.target.id==='chat-form')submitChat(e);if(e.target.id==='settings-form')submitSettings(e)});
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();createChat()}if(e.key==='Enter'&&!e.shiftKey&&e.target.id==='chat-input'){e.preventDefault();e.target.form.requestSubmit()}});
document.querySelector('#top-settings').addEventListener('click',()=>layout('settings'));
document.querySelector('#new-chat').addEventListener('click',createChat);
document.querySelector('#clear-history').addEventListener('click',actions['clear-history']);
document.querySelector('#collapse').addEventListener('click',()=>document.querySelector('#side').classList.toggle('compact'));
if(!isDesktop){document.body.classList.add('preview');document.querySelector('#runtime-label').textContent='WEB PREVIEW'}
initialize();
})();
