import path from 'node:path';import {fileURLToPath} from 'node:url';import {buildData} from './build-data.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
export function benchmarkDataPlugin({root=path.resolve(here,'../..'),out=path.resolve(here,'../public/data')}={}){
 return {name:'benchmark-results-watcher',async configureServer(server){
  await buildData({root,out});
  const watched=[path.join(root,'judge/final-results'),path.join(root,'data/questions.jsonl'),path.join(root,'website/dataset.json'),path.join(root,'judge/evaluation.schema.json')];server.watcher.add(watched);
  let timer,running=Promise.resolve();
  const update=file=>{if(!watched.some(p=>file===p||file.startsWith(p+path.sep)))return;clearTimeout(timer);timer=setTimeout(()=>{running=running.then(async()=>{try{await buildData({root,out});server.ws.send({type:'full-reload'});}catch(e){server.config.logger.error(`Data build failed: ${e}`);}});},200);};
  server.watcher.on('add',update).on('change',update).on('unlink',update);
  server.httpServer?.once('close',()=>{clearTimeout(timer);server.watcher.off('add',update).off('change',update).off('unlink',update);});
 }};
}
