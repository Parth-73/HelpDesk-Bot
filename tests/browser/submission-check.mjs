import {chromium} from './node_modules/playwright/index.mjs';
import fs from 'node:fs';
const browser=await chromium.launch({executablePath:'C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const checks=[],errors=[],requests=[],transcripts=new Map();let failure=false;
const check=(ok,name)=>{if(!ok)throw Error(name);checks.push(name);};
page.on('pageerror',e=>errors.push(e.message));
await page.route('**/api/**',async route=>{
 const req=route.request(),path=new URL(req.url()).pathname;
 let body,status=200;
 if(path==='/api/stats')body={total_questions:requests.length,gemini_api_calls:0,cache_hits:0};
 else if(path==='/api/faq/suggestions')body={suggestions:[],knowledge_version:null};
 else if(path==='/api/session'&&req.method()==='POST'){const id=crypto.randomUUID();transcripts.set(id,[]);body={session_id:id};}
 else if(path.startsWith('/api/session/')){const id=path.split('/').at(-1);if(!transcripts.has(id)){status=404;body={error:{code:'UNKNOWN_SESSION',message:'Unknown session',retryable:false}};}else body={sessionId:id,messages:transcripts.get(id)};}
 else if(path==='/api/chat'){
  const input=req.postDataJSON();requests.push(input);await new Promise(r=>setTimeout(r,350));
  if(failure){status=503;body={error:{code:'AI_UNAVAILABLE',message:'Temporarily unavailable. Please retry.',retryable:true}};}
  else {const answer='At least 60% overall AND 40% separately in the final exam.';body={answer,sources:['03_grading_policy_v2.txt'],cached:false,session_id:input.session_id,answer_path:'deterministic'};transcripts.get(input.session_id).push({id:input.request_id,role:'user',content:input.question,timestamp:new Date().toISOString()},{id:crypto.randomUUID(),role:'assistant',content:answer,sources:body.sources,timestamp:new Date().toISOString()});}
 }else throw Error(path);
 await route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
});
try {
 await page.goto('http://127.0.0.1:8788');await page.waitForFunction(()=>!document.querySelector('textarea').disabled);
 check(!await page.locator('.demo-notice').count(),'production mode initializes a server session');
 await page.getByLabel('Your DPM-101 question').fill('What are passing requirements?');
 await page.getByRole('button',{name:'Send question'}).click();
 check(await page.locator('textarea').isDisabled(),'composer disabled during request');
 await page.locator('textarea').press('Enter');await page.locator('.assistant').waitFor();
 check(requests.length===1,'Enter during loading does not duplicate submission');
 check((await page.locator('.sources').innerText()).includes('03_grading_policy_v2.txt'),'source citation displayed');
 await page.reload();await page.waitForFunction(()=>!document.querySelector('textarea').disabled);
 check(await page.locator('.message').count()===2,'reload reconciles persisted server transcript');
 failure=true;await page.getByLabel('Your DPM-101 question').fill('What if I score 35% in it?');await page.getByRole('button',{name:'Send question'}).click();await page.getByRole('alert').waitFor();
 check((await page.getByRole('alert').innerText()).includes('unavailable'),'friendly failure shown');
 failure=false;await page.getByRole('button',{name:'Retry',exact:true}).click();await page.waitForFunction(()=>document.querySelectorAll('.assistant').length===2);
 check(requests.at(-1).request_id===requests.at(-2).request_id,'retry retains idempotency key');
 check(await page.locator('.user').count()===2,'retry retains one user message');
 for(const width of [320,390,768]){await page.setViewportSize({width,height:844});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`no overflow at ${width}px`);}
 check(errors.length===0,'no browser runtime errors');
 fs.writeFileSync('backend/artifacts/submission_browser.json',JSON.stringify({checks,errors,scope:'Production Vite bundle, mocked HTTP API; backend behavior tested separately with PostgreSQL.'},null,2));
 console.log(`${checks.length} browser checks passed`);
}finally{await browser.close();}

