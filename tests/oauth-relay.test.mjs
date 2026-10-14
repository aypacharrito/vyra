import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

for (const provider of ['facebook','instagram']) {
 const source=await readFile(new URL(`../website/api/${provider}-callback.js`,import.meta.url),'utf8');
 const {default:handler}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 test(`${provider} callback only forwards state and code to the local worker`,()=>{
  const headers={};let redirect;
  const res={setHeader:(k,v)=>headers[k]=v,redirect:(status,url)=>redirect={status,url},status(){return this},end(){},send(){}};
  handler({method:'GET',query:{state:'test-state',code:'test-code',redirect:'https://attacker.example',access_token:'never-forward'}},res);
  const url=new URL(redirect.url);
  assert.equal(redirect.status,302);assert.equal(url.origin,'http://127.0.0.1:8765');
  assert.equal(url.pathname,`/api/oauth/${provider}/callback`);
  assert.deepEqual([...url.searchParams.keys()],['state','code']);
  assert.equal(headers['Cache-Control'],'no-store');assert.equal(headers['Referrer-Policy'],'no-referrer');
 });
 test(`${provider} callback rejects an authorization code without state`,()=>{
  let status;const res={setHeader(){},status(value){status=value;return this},send(){},end(){}};
  handler({method:'GET',query:{code:'test'}},res);assert.equal(status,400);
 });
}
