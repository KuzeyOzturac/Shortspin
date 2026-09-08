export const JACKPOT_CHANCE = .08;
export const PAIR_CHANCE = .22;
export const DURATIONS = [
  [...Array(9).fill(58), ...Array(4).fill(70), ...Array(3).fill(86), 115,150,215],
  [...Array(11).fill(58), ...Array(5).fill(70), ...Array(3).fill(88),120,160,225,290],
  [...Array(13).fill(58), ...Array(6).fill(72), ...Array(4).fill(90),125,170,235,310,380],
];
export const pick = (items, rng = Math.random) => items[Math.floor(rng()*items.length)];
export function chooseTargets(ready, rng = Math.random) {
  if (ready.length < 3) throw new Error('At least three unique videos are required.');
  const roll = rng();
  if (roll < JACKPOT_CHANCE) { const key = pick(ready,rng); return [key,key,key]; }
  if (roll < JACKPOT_CHANCE + PAIR_CHANCE) {
    const pair = pick(ready,rng), other = pick(ready.filter(x=>x.id!==pair.id),rng);
    const result = [pair,pair,other];
    for(let i=2;i>0;i--){const j=Math.floor(rng()*(i+1));[result[i],result[j]]=[result[j],result[i]];}
    return result;
  }
  // Preserve the Python app's independent draws, including incidental matches.
  return [pick(ready,rng),pick(ready,rng),pick(ready,rng)];
}
export function outcome(items) {
  const count = new Set(items.map(x=>x.id)).size;
  return count===1 ? 'jackpot' : count===2 ? 'pair' : 'miss';
}
export function sequence(pool,target,count,rng=Math.random){
  const result=[];let previous;
  for(let i=0;i<count-1;i++){
    const choices=pool.filter(x=>x.id!==target.id && x.id!==previous?.id);
    previous=pick(choices.length?choices:pool,rng);result.push(previous);
  }
  return [...result,target];
}
