// Load the Studio's pure scripts (engine + model from index.html, plus studio-lib.js) into a VM context.
import fs from 'node:fs';import vm from 'node:vm';import path from 'node:path';import {fileURLToPath} from 'node:url';
const dir=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
export function loadStudio(){
  const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
  const script=id=>{const m=new RegExp('<script id="'+id+'">([\\s\\S]*?)</script>').exec(html);if(!m)throw new Error('missing script '+id);return m[1];};
  const ctx=vm.createContext({console,crypto:globalThis.crypto,TextEncoder,URL,structuredClone});
  ctx.globalThis=ctx;
  vm.runInContext(fs.readFileSync(path.join(dir,'studio-lib.js'),'utf8'),ctx,{filename:'studio-lib.js'});
  vm.runInContext(script('engine'),ctx,{filename:'engine'});
  vm.runInContext(script('model'),ctx,{filename:'model'});
  return {E:ctx.Workbench,M:ctx.StudioModel,L:ctx.StudioLib,ctx};
}
export const studioDir=dir;
