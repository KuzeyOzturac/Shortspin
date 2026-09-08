import {cp,mkdir,rm,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../',import.meta.url));
process.chdir(root);
const catalog=JSON.parse(await readFile('web/videos.json','utf8'));
if(!Array.isArray(catalog.videos)||new Set(catalog.videos.map(v=>v.id)).size<6) throw Error('Catalog must contain at least six distinct videos.');
for(const name of ['click_spin','spin','lock','win','two_matched','loading','loaded']){
  if((await readFile(`sounds/${name}.mp3`)).length===0) throw Error(`Empty sound: ${name}`);
}
await rm('dist',{recursive:true,force:true});await mkdir('dist');
await cp('web','dist',{recursive:true});await cp('sounds','dist/sounds',{recursive:true});
await writeFile('dist/.nojekyll','');
console.log(`Built GitHub Pages site with ${catalog.videos.length} videos and seven original sounds.`);
