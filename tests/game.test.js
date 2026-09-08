import test from 'node:test';
import assert from 'node:assert/strict';
import {chooseTargets,outcome,sequence,DURATIONS} from '../web/game.js';
const pool=Array.from({length:6},(_,id)=>({id:String(id)}));
function rng(values){return()=>values.shift()??.5;}
test('explicit jackpot, pair, and ordinary outcomes preserve Python rules',()=>{
  assert.equal(outcome(chooseTargets(pool,rng([.079,.5]))),'jackpot');
  assert.equal(outcome(chooseTargets(pool,rng([.08,.5,.2,.4,.2]))),'pair');
  assert.equal(outcome(chooseTargets(pool,rng([.299,.5,.2,.4,.2]))),'pair');
  assert.equal(outcome(chooseTargets(pool,rng([.3,0,.2,.4]))),'miss');
  assert.equal(outcome(chooseTargets(pool,rng([.8,.4,.4,.4]))),'jackpot');
});
test('the exact target is always the last thumbnail, without early target flashes',()=>{
  for(const durations of DURATIONS){
    const items=sequence(pool,pool[0],durations.length);
    assert.equal(items.length,durations.length);assert.equal(items.at(-1),pool[0]);
    assert.ok(items.slice(0,-1).every(x=>x!==pool[0]));
    for(let i=1;i<items.length-1;i++)assert.notEqual(items[i],items[i-1]);
  }
});
test('reels stop in a staggered order using original timings',()=>{
  const sums=DURATIONS.map(ds=>ds.reduce((a,b)=>a+b,0));
  assert.deepEqual(sums,[1540,2047,2766]);
});
