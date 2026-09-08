import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

// Run the real reel method with instant animation ticks and an indefinitely
// buffering provider. A lock must finish without awaiting provider readiness.
const source=readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
const reelClass=source.slice(source.indexOf('class Reel{'),source.indexOf('const reels='));
const Reel=vm.runInNewContext(`${reelClass}; Reel`,{reduced:true,delay:()=>Promise.resolve()});
test('a buffering video cannot delay the mechanical reel lock',async()=>{
  const classes=new Set();
  const reel={pause(){},token:0,playing:false,
    el:{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)}},
    retry:{hidden:false},spinner:{hidden:false},images:[{},{}],
    load(){this.token++;return new Promise(()=>{});},
    fallback(){throw Error('Buffering alone must not force an immediate error');},
  };
  let timeout;
  try{
    await Promise.race([
      Reel.prototype.spin.call(reel,{id:'target'},[{thumbnail:'target.jpg'}],[58]),
      new Promise((_,reject)=>{timeout=setTimeout(()=>reject(Error('Lock waited for playback')),100);}),
    ]);
    assert.equal(classes.has('moving'),false);
    assert.equal(reel.images[0].src,'target.jpg');
    assert.equal(reel.spinner.hidden,false);
  }finally{clearTimeout(timeout);}
});
