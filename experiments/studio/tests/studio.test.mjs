// Model-level checks for the Studio prototype. Run: node --test experiments/studio/tests/
import test from 'node:test';import assert from 'node:assert/strict';
import {loadStudio} from './load.mjs';

const {E,M,L}=loadStudio();
const sha=async t=>{const b=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(t));return [...new Uint8Array(b)].map(x=>x.toString(16).padStart(2,'0')).join('');};
async function doc(path,text,extra={}){const h=await sha(text);return {path,text,format:L.formatOf(path),size:text.length,modified:'2024-01-02T03:04:05.000Z',byteHash:'b'+h,textHash:h,...extra};}
const plain=x=>JSON.parse(JSON.stringify(x));
const eq=(a,b,m)=>assert.deepEqual(plain(a),plain(b),m); // values cross the VM realm boundary
const blank=()=>M.blankWorkspace();

test('segments keep exact offsets for headings, bullets, Unicode and emoji',()=>{
  const text='# Ünïcode résumé 🚀\r\n\r\nLed a team of 5 🎉 engineers\nacross two time zones.\n\n- Shipped 🌍 search\n  continued line\n* Cut costs 12%\n1. Numbered item\n\n---\n\nAI\n';
  const {segments,skipped}=L.segment(text);
  for(const s of segments)assert.equal(text.slice(s.start,s.end),s.text);
  eq(segments.map(s=>s.kind),['heading','paragraph','item','item','item','paragraph']);
  assert.equal(segments[2].text,'- Shipped 🌍 search\n  continued line');
  assert.equal(segments.at(-1).text,'AI'); // short lines are kept
  assert.equal(skipped,1); // the --- rule
});

test('a long document is imported completely, beyond the old 80-paragraph cap',async()=>{
  const s=blank(),text=Array.from({length:250},(_,i)=>'Paragraph number '+i+' about delivery.').join('\n\n');
  const r=M.importDocument(s,await doc('notes/long.md',text));
  assert.equal(r.status,'imported');assert.equal(r.count,250);
  assert.equal(s.facts.filter(f=>f.source===r.sid).length,250);
});

test('the segment limit is reported, not silent',()=>{
  const text=Array.from({length:12},(_,i)=>'Item '+i).join('\n\n');
  const {segments,overflow}=L.segment(text,{maxSegments:10});
  assert.equal(segments.length,10);assert.equal(overflow,2);
});

test('nested paths survive and same-named files stay distinct',async()=>{
  const s=blank();
  const a=M.importDocument(s,await doc('Career/2022/resume.md','Built the billing system.'));
  const b=M.importDocument(s,await doc('Career/2024/resume.md','Led the platform team.'));
  assert.equal(a.status,'imported');assert.equal(b.status,'imported');
  eq(s.sources.map(d=>d.path),['Career/2022/resume.md','Career/2024/resume.md']);
  assert.ok(M.search(s,'path:career/2024').rows.length===1);
});

test('reimport: unchanged is skipped, changed makes a snapshot, drafts keep their source',async()=>{
  const s=blank(),p=s.projects[0];
  const v1=M.importDocument(s,await doc('cv/resume.md','# Resume\n\nReduced latency by 40%.'));
  const fid=s.facts.find(f=>f.source===v1.sid&&/latency/.test(f.text)).family;
  M.toggle(s,fid);const block=M.insertBlock(s,p,fid);block.text='Reduced p95 latency by 40% (edited).';
  assert.equal(M.importDocument(s,await doc('cv/resume.md','# Resume\n\nReduced latency by 40%.')).status,'unchanged');
  const v2=M.importDocument(s,await doc('cv/resume.md','# Resume\n\nReduced latency by 45%.'));
  assert.equal(v2.status,'updated');
  const old=s.sources.find(d=>d.id===v1.sid);
  assert.equal(old.supersededBy,v2.sid);assert.ok(old.archived);
  assert.equal(block.sid,v1.sid);assert.equal(block.text,'Reduced p95 latency by 40% (edited).');
  assert.ok(s.facts.some(f=>f.id===block.eid));
  // the unchanged heading merged into the same material family across snapshots
  const heading=s.facts.filter(f=>f.text==='# Resume');assert.equal(heading.length,2);assert.equal(heading[0].family,heading[1].family);
  // discovery shows only the latest snapshot
  assert.equal(M.search(s,'45%').rows.length,1);assert.equal(M.search(s,'40%').rows.length,0);
});

test('identical text at another path is recorded as an alias',async()=>{
  const s=blank();
  const a=M.importDocument(s,await doc('A/cover.txt','Dear team, I build reliable things.'));
  const b=M.importDocument(s,await doc('B/cover-copy.txt','Dear team, I build reliable things.'));
  assert.equal(b.status,'duplicate');assert.equal(b.sid,a.sid);
  eq(s.sources[0].aliases,['B/cover-copy.txt']);assert.equal(s.sources.length,1);
});

test('identical paragraphs in different documents share one material family',async()=>{
  const s=blank();
  M.importDocument(s,await doc('r/2022.md','Mentored six engineers.\n\nOld line.'));
  M.importDocument(s,await doc('r/2024.md','Mentored six engineers.\n\nNew line.'));
  const fam=s.facts.filter(f=>f.text==='Mentored six engineers.').map(f=>f.family);
  assert.equal(fam.length,2);assert.equal(fam[0],fam[1]);
  assert.equal(M.search(s,'mentored').rows.length,1);
});

test('permanently removed text stays blocked through the new import path',async()=>{
  const s=blank(),text='Secret draft I deleted.';
  const r=M.importDocument(s,await doc('x/a.md',text));
  M.queue(s,'source',r.sid);await M.purge(s,'source',r.sid);
  assert.equal(M.importDocument(s,await doc('y/b.md',text)).status,'blocked');
});

test('PDF page numbers are attached to passages',async()=>{
  const s=blank(),text='Page one text.\n\nPage two text.';
  const r=M.importDocument(s,await doc('cv.pdf',text,{pages:[{page:1,start:0,end:14},{page:2,start:16,end:30}]}));
  eq(s.facts.filter(f=>f.source===r.sid).map(f=>f.page),[1,2]);
  const p=s.projects[0];const fid=s.facts.find(f=>f.page===2).family;M.insertBlock(s,p,fid);
  assert.match(M.editorText(s,p),/cv\.pdf · page 2 · characters 16–30/);
});

test('import, collect, insert, edit and export works end to end',async()=>{
  const s=blank(),p=s.projects[0];
  M.importDocument(s,await doc('Jobs/acme.md','# Acme\n\n- Shipped the onboarding redesign.\n- Cut support tickets 30%.'));
  const fid=M.search(s,'tickets').rows[0].family.id;
  M.toggle(s,fid);const b=M.insertBlock(s,p,fid);b.text='Cut support tickets by 30% in two quarters.';
  const out=M.editorText(s,p);
  assert.match(out,/Cut support tickets by 30% in two quarters\. \[1\]/);
  assert.match(out,/Jobs\/acme\.md · characters \d+–\d+ · Project-edited wording/);
  const draft=M.build(s,p);assert.doesNotMatch(draft.text,/fictional/i);
});

test('workspace export round-trips and validation rejects damage',async()=>{
  const s=blank();M.importDocument(s,await doc('a/b.md','One.\n\nTwo.'));
  const file=plain(L.exportWorkspace(s));
  const ok=L.validateWorkspace(file,{valid:M.valid});eq(ok.errors,[]);
  const restored=M.migrate(plain(file.workspace));eq(restored,M.migrate(plain(s)));
  const bad=plain(file);bad.workspace.facts[0].start+=1;
  assert.ok(L.validateWorkspace(bad,{valid:M.valid}).errors.some(e=>/no longer matches/.test(e)));
  assert.ok(L.validateWorkspace({format:'other'},{valid:M.valid}).errors.length);
  const missing=plain(file);missing.workspace.projects[0].ids.push('nope');
  assert.ok(L.validateWorkspace(missing,{valid:M.valid}).errors.some(e=>/missing material/.test(e)));
});

test('old saved state (pre-change shape) still loads and works',async()=>{
  // Shape written by the previous version: imported source without the new metadata fields.
  const old=M.seed();await M.importText(old,'legacy.md','Legacy imported paragraph text here.');
  const json=JSON.stringify(old),s=M.migrate(JSON.parse(json));
  assert.ok(M.valid(s));
  assert.equal(M.importDocument(s,await doc('imports/legacy.md','Legacy imported paragraph text here.')).status,'unchanged');
  assert.ok(M.search(s,'legacy').rows.length>=1);
});

test('large archive stays responsive',async()=>{
  const s=blank();const words='led built reduced latency team mentoring systems design incident budget migrated customers'.split(' ');
  for(let d=0;d<300;d++){const text=Array.from({length:40},(_,k)=>Array.from({length:12},(_,i)=>words[(d+k*3+i)%words.length]).join(' ')+' '+d+'.'+k).join('\n\n');M.importDocument(s,{path:'bulk/'+d+'.md',text,textHash:'h'+d,byteHash:'b'+d});}
  const t=performance.now();
  s.families.filter(f=>M.status(s,f.id)==='review');M.search(s,'');M.search(s,'latency');
  assert.ok(performance.now()-t<1500,'took '+(performance.now()-t)+'ms');
});
