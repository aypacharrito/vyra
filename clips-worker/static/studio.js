(() => {
'use strict';
const wrap=document.querySelector('.wrap');
const modes={'#create':'studio','#library':'library','#queue':'publishing','#accounts':'accounts'};
function select(){const hash=modes[location.hash]?location.hash:'#create';wrap.dataset.mode=modes[hash];document.querySelectorAll('.studio-tabs a').forEach(link=>{if(link.hash===hash)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current')});window.scrollTo({top:0,behavior:'instant'})}
window.addEventListener('hashchange',select);select();
const counts=()=>{document.getElementById('libraryCount').textContent=document.querySelectorAll('#clipsList .clip').length;document.getElementById('queueCount').textContent=document.querySelectorAll('#activity .activity-item').length};
new MutationObserver(counts).observe(document.getElementById('clipsList'),{childList:true,subtree:true});
new MutationObserver(counts).observe(document.getElementById('activity'),{childList:true,subtree:true});counts();
window.addEventListener('message',event=>{if(event.origin!=='http://127.0.0.1:48791'||event.source!==window.parent)return;if(event.data?.type==='vyra.newSource'){location.hash='#create';document.getElementById('sourceURL')?.focus()}});
// Release file handles before replacing a library that no longer contains an uploaded clip.
const original=window.loadLibrary;
window.loadLibrary=async()=>{document.querySelectorAll('#clipsList video').forEach(video=>{if(!video.paused){video.pause();video.removeAttribute('src');video.load()}});await original();counts()};
})();
