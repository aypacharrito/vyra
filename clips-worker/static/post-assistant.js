(() => {
 'use strict';
 const el=id=>document.getElementById(id);
 const form=el('publishForm');
 const controls=document.createElement('div');controls.className='setup-step';
 controls.innerHTML='<div class="headline-row"><strong>AI post assistant</strong><button type="button" class="btn subtle" id="regenerateCopy">Regenerate copy</button></div><p class="note" id="copyStatus" role="status">Preparing your post…</p><label for="timingMode">Posting time</label><select class="input" id="timingMode"><option value="recommended">Choose automatically</option><option value="now">Post now</option><option value="manual">Choose a time</option></select><p class="note" id="timingStatus" role="status"></p>';
 form.prepend(controls);
 let requestId=0, plan=null;
 window.assistantBusy=false;
 const localInput=iso=>{const date=new Date(iso);return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)};
 function setTiming(){
  const tiktok=el('postPlatform').value==='tiktok';
  const mode=el('timingMode').value;
  el('timingMode').disabled=tiktok;
  el('postSchedule').classList.toggle('hidden',tiktok||mode!=='manual');
  el('postSchedule').required=!tiktok&&mode==='manual';
  el('scheduleLabel').classList.toggle('hidden',tiktok||mode!=='manual');
  if(tiktok||mode==='now')el('postSchedule').value='';
  else if(mode==='recommended'&&plan)el('postSchedule').value=localInput(plan.scheduled_at);
 }
 function releaseButton(){
  window.assistantBusy=false;el('regenerateCopy').disabled=false;
  el('confirmPublish').disabled=el('postPlatform').value==='instagram'&&!window.accountStatus?.instagram?.publishing?.ready;
 }
 async function prepare(regenerate=false,timingOnly=false){
  if(!activeClip)return;
  const sequence=++requestId;
  const selected=activeClip, platform=el('postPlatform').value;
  const before={title:el('postTitle').value,caption:el('postCaption').value};
  window.assistantBusy=true;el('confirmPublish').disabled=true;el('regenerateCopy').disabled=true;
  el('postConsent').checked=false;
  el('copyStatus').textContent='Writing platform-specific copy from this clip…';
  el('timingStatus').textContent='Choosing a window in your timezone…';
  try{
   const zone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';
   const response=await secureFetch('/api/post-assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:selected.job_id,filename:selected.file,platform,timezone:zone,regenerate})});
   const result=await json(response);
   if(sequence!==requestId||activeClip!==selected||el('postPlatform').value!==platform)return;
   // Preserve anything typed while the model was working.
   if(!timingOnly&&el('postTitle').value===before.title)el('postTitle').value=result.title;
   if(!timingOnly&&el('postCaption').value===before.caption)el('postCaption').value=result.caption;
   el('copyStatus').textContent=(result.ai_generated?'AI copy ready. ':'')+result.reason;
   plan=result.timing;
   const time=new Date(plan.scheduled_at).toLocaleString(undefined,{weekday:'short',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'});
   el('timingStatus').textContent=(platform==='tiktok'?'Suggested time: ':'Selected time: ')+time+'. '+plan.reason+(platform==='tiktok'?' Open Vyra then and confirm Public for that post.':' Vyra must remain open to send scheduled posts.');
   setTiming();form.dispatchEvent(new Event('change',{bubbles:true}));
  }catch(error){
   if(sequence!==requestId||activeClip!==selected)return;
   plan=null;el('timingMode').value='manual';setTiming();
   el('copyStatus').textContent=error.message;
   el('timingStatus').textContent='Automatic preparation did not finish. Review the existing text and choose a time before submitting.';
  }finally{if(sequence===requestId)releaseButton()}
 }
 const originalOpen=window.openPublisher;
 window.openPublisher=clip=>{originalOpen(clip);plan=null;el('timingMode').value='recommended';prepare()};
 const originalClose=window.closePublisher;
 window.closePublisher=()=>{++requestId;window.assistantBusy=false;originalClose()};
 el('postPlatform').addEventListener('change',()=>{plan=null;el('timingMode').value='recommended';prepare()});
 el('regenerateCopy').addEventListener('click',()=>prepare(true));
 el('timingMode').addEventListener('change',()=>{el('postConsent').checked=false;if(el('timingMode').value==='recommended')prepare(false,true);else setTiming()});
 form.addEventListener('input',event=>{if(event.target.id!=='postConsent')el('postConsent').checked=false});
 form.addEventListener('submit',event=>{
  if(window.assistantBusy){event.preventDefault();event.stopImmediatePropagation();toast('Wait for post preparation to finish.');return}
  if(el('postPlatform').value==='tiktok'&&el('postVisibility').value!=='PUBLIC_TO_EVERYONE'){
   event.preventDefault();event.stopImmediatePropagation();toast('Choose Public for this TikTok post.');return;
  }
 },true);
 el('clipsList').addEventListener('click',async event=>{
  const button=event.target.closest('[data-delete-clip]');if(!button)return;
  const [job,file]=button.dataset.deleteClip.split(':');
  if(!confirm('Delete this local clip and cancel its queued posts and unsent drafts? Posts already on social accounts stay online.'))return;
  button.disabled=true;
  for(const video of el('clipsList').querySelectorAll('video')){
   if(video.src.includes('/'+job+'/files/'+file)){video.pause();video.removeAttribute('src');video.load()}
  }
  try{
   const result=await json(await secureFetch('/api/clips/'+encodeURIComponent(job)+'/'+encodeURIComponent(file),{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirm:true})}));
   if(activeClip?.job_id===job&&activeClip?.file===file)closePublisher();
   toast(result.message);await Promise.all([loadLibrary(),loadQueue()]);
  }catch(error){toast(error.message);button.disabled=false;await loadLibrary()}
 });
 window.preparePostAutomatically=prepare;
 window.refreshPostTiming=()=>prepare(false,true);
})();
