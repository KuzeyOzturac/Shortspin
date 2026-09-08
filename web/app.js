import {DURATIONS,pick,chooseTargets,outcome,sequence} from './game.js';

const $=s=>document.querySelector(s);
const button=$('#spin'),label=button.querySelector('span'),result=$('#result'),row=$('#reels');
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let phase='idle',pool=[],generation=0,locked=0;
function notice(message=''){const el=$('#notice');el.textContent=message;el.hidden=!message;}
function status(message,style=''){result.textContent=message;result.className=style;}
function later(callback,ms,token=generation){setTimeout(()=>{if(token===generation)callback();},ms);}

class Sounds{
  constructor(){this.context=null;this.buffers={};this.active=new Map();}
  async unlock(){
    this.context??=new (window.AudioContext||window.webkitAudioContext)();
    await this.context.resume();
  }
  async load(){
    const names={click:'click_spin',spin:'spin',lock:'lock',win:'win',pair:'two_matched',loading:'loading',loaded:'loaded'};
    await Promise.all(Object.entries(names).map(async([key,file])=>{
      const response=await fetch(`./sounds/${file}.mp3`,{signal:AbortSignal.timeout(15000)});
      if(!response.ok)throw Error(`Could not load ${file}.mp3`);
      this.buffers[key]=await this.context.decodeAudioData(await response.arrayBuffer());
    }));
  }
  play(name,loop=false){
    if(!this.context||!this.buffers[name])return;
    if(name!=='lock')this.stop(name);
    const source=this.context.createBufferSource(),gain=this.context.createGain();
    source.buffer=this.buffers[name];source.loop=loop;
    gain.gain.value={click:.95,spin:.72,loading:.85}[name]??1;
    source.connect(gain).connect(this.context.destination);
    const key=name==='lock'?Symbol('lock'):name;
    this.active.set(key,source);source.onended=()=>{if(this.active.get(key)===source)this.active.delete(key);};source.start();
  }
  stop(name){const source=this.active.get(name);if(source){source.stop();this.active.delete(name);}}
  stopAll(){for(const source of this.active.values())source.stop();this.active.clear();}
}
const sounds=new Sounds();

let youtubePromise;
function youtube(){
  if(window.YT?.Player)return Promise.resolve();
  if(youtubePromise)return youtubePromise;
  youtubePromise=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    const timer=setTimeout(()=>{script.remove();youtubePromise=null;reject(Error('YouTube did not respond. Please try again.'));},15000);
    window.onYouTubeIframeAPIReady=()=>{clearTimeout(timer);resolve();};
    script.src='https://www.youtube.com/iframe_api';
    script.onerror=()=>{clearTimeout(timer);script.remove();youtubePromise=null;reject(Error('YouTube could not load. Check your connection.'));};
    document.head.append(script);
  });return youtubePromise;
}

class Reel{
  constructor(index){
    this.index=index;this.token=0;this.current=null;this.player=null;this.video=null;this.playing=false;
    this.el=document.createElement('section');this.el.className='reel';this.el.setAttribute('aria-label',`Reel ${index+1}`);
    this.el.innerHTML='<div class="media"></div><div class="spinner"><img class="current" alt=""><img class="next" alt=""></div><button class="retry" type="button" hidden>Play video</button>';
    row.append(this.el);this.media=this.el.querySelector('.media');this.spinner=this.el.querySelector('.spinner');
    this.images=[...this.spinner.querySelectorAll('img')];this.retry=this.el.querySelector('.retry');
    this.retry.addEventListener('click',()=>this.retryPlayback());
    this.resizeObserver=new ResizeObserver(()=>this.sizeEmbeddedPlayer());
    this.resizeObserver.observe(this.media);
  }
  sizeEmbeddedPlayer(){
    const frame=this.media.querySelector('iframe');if(!frame)return;
    const {width,height}=this.media.getBoundingClientRect();if(!width||!height)return;
    // Put provider chrome in the player's letterbox area outside the reel.
    // Constrain the portrait picture to the reel height, including jackpot.
    const scale=Math.min(1,width/200);
    frame.style.width=Math.max(200,Math.min(width,height*9/16))+'px';
    frame.style.height=(height/scale+240)+'px';
    frame.style.transform=`translate(-50%,-50%) scale(${scale})`;
  }
  showThumb(item){this.images[0].src=item.thumbnail;this.images[0].alt=item.title||'Short video';this.images[1].removeAttribute('src');this.spinner.hidden=false;}
  mute(){if(this.video)this.video.muted=true;this.player?.mute?.();}
  pause(){this.mute();this.video?.pause();this.player?.pauseVideo?.();}
  dispose(){clearTimeout(this.revealTimer);this.revealTimer=null;this.player?.destroy?.();this.player=null;if(this.video){this.video.pause();this.video.removeAttribute('src');this.video.load();}this.video=null;this.media.replaceChildren();}
  async load(item){
    const token=++this.token;this.current=item;this.playing=false;this.retry.hidden=true;
    this.el.classList.remove('unavailable');this.dispose();
    let resolvePlaying;
    const ready=new Promise(resolve=>{resolvePlaying=resolve;});
    const played=()=>{
      if(token!==this.token)return;
      if(this.revealTimer||this.playing)return;
      const reveal=()=>{
        this.revealTimer=null;if(token!==this.token)return;
        this.playing=true;resolvePlaying(true);
        if(!this.el.classList.contains('moving')){this.spinner.hidden=true;this.retry.hidden=true;this.el.classList.remove('unavailable');}
      };
      // The provider briefly paints central transport controls on startup.
      // Keep the selected thumbnail in front until those controls fade.
      if(item.type==='youtube')this.revealTimer=setTimeout(reveal,2500);else reveal();
    };
    const failed=()=>{if(token!==this.token)return;clearTimeout(this.revealTimer);this.revealTimer=null;this.playing=false;resolvePlaying(false);if(!this.el.classList.contains('moving'))this.fallback();};
    if(item.type==='video'){
      const video=document.createElement('video');this.video=video;
      video.muted=true;video.loop=true;video.playsInline=true;video.preload='auto';video.src=item.url;
      video.addEventListener('playing',played);video.addEventListener('error',failed);
      this.media.append(video);video.play().catch(failed);
    }else{
      try{
        await youtube();if(token!==this.token)return false;
        const host=document.createElement('div');this.media.append(host);
        this.player=new YT.Player(host,{
          width:'100%',height:'100%',videoId:item.id,
          playerVars:{autoplay:1,controls:0,disablekb:1,fs:0,iv_load_policy:3,playsinline:1,rel:0,loop:1,playlist:item.id,origin:location.origin},
          events:{
            onReady:event=>{if(token===this.token){
              const frame=event.target.getIframe();frame.setAttribute('tabindex','-1');frame.setAttribute('aria-hidden','true');frame.setAttribute('title','');frame.setAttribute('inert','');
              this.sizeEmbeddedPlayer();event.target.mute();event.target.playVideo();
            }},
            onStateChange:event=>{
              if(token!==this.token)return;
              if(event.data===1)played();
              else if([0,2,3].includes(event.data)){
                clearTimeout(this.revealTimer);this.revealTimer=null;this.playing=false;this.spinner.hidden=false;
                if(event.data===0)event.target.playVideo();
              }
            },
            onError:event=>{if([100,101,150].includes(event.data))item.unavailable=true;failed();},
            onAutoplayBlocked:()=>{if(token===this.token){resolvePlaying(false);if(!this.el.classList.contains('moving'))this.fallback('Play video');}},
          },
        });
      }catch{failed();}
    }
    return Promise.race([ready,delay(10000).then(()=>false)]);
  }
  fallback(text='Retry video'){
    this.spinner.hidden=false;this.retry.hidden=false;this.retry.textContent=text;this.el.classList.add('unavailable');
  }
  async retryPlayback(){
    if(phase==='spinning')return;
    const generationAtClick=generation;
    this.retry.disabled=true;
    if(this.video){try{await this.video.play();}catch{this.fallback();}}
    else if(this.player){this.player.playVideo();}
    if(phase==='jackpot'&&this.index===0)this.unmute();
    await delay(600);
    if(generationAtClick===generation&&!this.playing){const item=this.current;const ok=await this.load(item);if(generationAtClick===generation){if(!ok)this.fallback();if(phase==='jackpot'&&this.index===0)this.unmute();}}
    this.retry.disabled=false;
  }
  unmute(){
    if(this.video){this.video.muted=false;this.video.play().catch(()=>this.fallback('Play with sound'));}
    else{this.player?.unMute?.();this.player?.setVolume?.(100);this.player?.playVideo?.();}
  }
  async spin(target,items,durations){
    this.pause();this.el.classList.add('moving');this.retry.hidden=true;this.spinner.hidden=false;
    // Preload behind the moving thumbnails; reveal only after actual playback.
    const loading=this.load(target);
    for(let i=0;i<items.length;i++){
      this.images[1].src=items[i].thumbnail;
      if(!reduced){
        const animations=this.images.map(img=>img.animate([{transform:'translateY(0)'},{transform:'translateY(-100%)'}],{duration:durations[i],easing:'linear'}));
        await Promise.all(animations.map(a=>a.finished));
      }else await delay(durations[i]);
      this.images[0].src=items[i].thumbnail;this.images[0].alt=items[i].title||'Short video';
    }
    this.el.classList.remove('moving');
    const ok=this.playing||await Promise.race([loading,delay(2600).then(()=>false)]);
    if(ok)this.spinner.hidden=true;else this.fallback();
  }
}
const reels=[0,1,2].map(i=>new Reel(i));

class Effects{
  constructor(){this.canvas=$('#effects');this.ctx=this.canvas.getContext('2d');this.particles=[];this.flash=0;this.running=false;this.spin=false;this.colors=['#ffd84d','#ffffff','#ff7a59','#55e6c1','#7db7ff','#c28cff'];}
  start(){if(reduced||this.running)return;this.running=true;this.last=performance.now();requestAnimationFrame(t=>this.tick(t));}
  burst(el,count=30){
    if(reduced)return;const rect=el.getBoundingClientRect();
    for(let i=0;i<count;i++){const a=Math.random()*Math.PI*2,s=90+Math.random()*180;this.particles.push({x:rect.x+rect.width/2,y:rect.y+rect.height/2,vx:Math.cos(a)*s,vy:Math.sin(a)*s-65,life:.28+Math.random()*.3,age:0,size:2.5+Math.random()*3.5,color:pick(this.colors),angle:a,spin:Math.random()*18-9});}
    this.flash=Math.max(this.flash,90);this.start();
  }
  jackpot(){if(reduced)return;for(let i=0;i<170;i++)this.particles.push({x:Math.random()*innerWidth,y:Math.random()*130-120,vx:Math.random()*170-85,vy:110+Math.random()*220,life:1.4+Math.random()*1.3,age:0,size:4.5+Math.random()*5,color:pick(this.colors),angle:Math.random()*Math.PI*2,spin:Math.random()*24-12,confetti:true});this.flash=185;this.start();}
  tick(time){
    const dt=Math.min((time-this.last)/1000,.05);this.last=time;const c=this.ctx,dpr=devicePixelRatio||1;
    if(this.canvas.width!==Math.round(innerWidth*dpr)||this.canvas.height!==Math.round(innerHeight*dpr)){this.canvas.width=Math.round(innerWidth*dpr);this.canvas.height=Math.round(innerHeight*dpr);this.canvas.style.width=innerWidth+'px';this.canvas.style.height=innerHeight+'px';}
    c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,innerWidth,innerHeight);
    if(this.spin){c.strokeStyle=`rgba(255,215,70,${(.13+.09*Math.sin(time/100))})`;c.lineWidth=4;c.strokeRect(5,5,innerWidth-10,innerHeight-10);}
    if(this.flash>0){c.fillStyle=`rgba(255,225,90,${this.flash/255})`;c.fillRect(0,0,innerWidth,innerHeight);this.flash=Math.max(0,this.flash-235*dt);}
    this.particles=this.particles.filter(p=>p.age<p.life);
    for(const p of this.particles){p.age+=dt;p.vy+=260*dt;p.x+=p.vx*dt;p.y+=p.vy*dt;p.angle+=p.spin*dt;c.save();c.translate(p.x,p.y);c.rotate(p.angle);c.globalAlpha=Math.max(0,1-p.age/p.life);c.fillStyle=p.color;if(p.confetti)c.fillRect(-p.size,-p.size*.45,p.size*2,p.size*.9);else{c.beginPath();c.arc(0,0,p.size,0,Math.PI*2);c.fill();}c.restore();}
    if(this.spin||this.flash||this.particles.length)requestAnimationFrame(t=>this.tick(t));else this.running=false;
  }
}
const fx=new Effects();

async function thumbnail(item){
  const candidates=item.type==='youtube'?[`https://i.ytimg.com/vi/${item.id}/oar2.jpg`,`https://i.ytimg.com/vi/${item.id}/hqdefault.jpg`]:[item.thumbnail];
  for(const src of candidates){if(!src)continue;const image=new Image();image.src=src;try{await Promise.race([image.decode(),delay(8000).then(()=>{throw Error('Thumbnail timed out');})]);if(image.naturalWidth>120){item.thumbnail=src;return item;}}catch{}}
  return null;
}

async function start(){
  const token=++generation;phase='loading';button.disabled=true;status('Preparing streams…');notice('');
  label.textContent='PREPARING 0%';button.classList.add('loading');button.style.setProperty('--progress',0);
  let target=0,value=0,failed=false,audioStarted=false;
  try{
    await sounds.unlock();await sounds.load();
    const response=await fetch('./videos.json',{signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw Error('The video list could not load. Please retry.');
    const catalog=await response.json();
    const unique=new Map();
    for(const item of catalog.videos??[]){if(item.type==='youtube'&&/^[\w-]{11}$/.test(item.id)||item.type==='video'&&item.id&&item.url)unique.set(item.id,item);}
    if(unique.size<6)throw Error('Add at least six videos to the catalog.');
    const finish=new Promise(resolve=>{
      function frame(){
        if(failed||token!==generation){resolve();return;}
        if(value<target)value=Math.min(target,value+Math.max(.0025,(target-value)*.085));
        if(value>0&&!audioStarted){audioStarted=true;sounds.play('loading',true);}
        button.style.setProperty('--progress',value);label.textContent=`PREPARING ${Math.round(value*100)}%`;
        if(value>=1){sounds.stop('loading');sounds.play('loaded');resolve();return;}
        requestAnimationFrame(frame);
      }requestAnimationFrame(frame);
    });
    // Load a bounded catalog concurrently. Fill reflects completed thumbnail
    // preparation (80%) and the initial three player attempts (20%).
    const candidates=[...unique.values()].sort(()=>Math.random()-.5).slice(0,60);
    let completed=0;
    const thumbnails=await Promise.all(candidates.map(async item=>{const ready=await thumbnail(item);completed++;target=.8*completed/candidates.length;return ready;}));
    pool=thumbnails.filter(Boolean);if(pool.length<6)throw Error('Not enough video thumbnails loaded. Check your connection and retry.');
    const initial=[...pool].sort(()=>Math.random()-.5).slice(0,3);let players=0;
    await Promise.all(reels.map(async(reel,i)=>{reel.showThumb(initial[i]);const ok=await reel.load(initial[i]);if(!ok)reel.fallback('Play video');players++;target=.8+.2*players/3;}));
    target=1;await finish;
    if(reels.some(r=>!r.playing))notice('Some videos could not start. Use Play video or spin again.');
    phase='ready';button.classList.remove('loading');button.disabled=false;label.textContent='SPIN';status('Press SPIN');
  }catch(error){failed=true;sounds.stopAll();phase='idle';button.classList.remove('loading');button.disabled=false;label.textContent='RETRY';status('Could not prepare videos');notice(error.message);}
}

async function spin(){
  if(!['ready','jackpot'].includes(phase))return;
  const ready=pool.filter(item=>!item.unavailable);
  if(ready.length<3){notice('Too few playable videos remain. Reload to retry, or refresh the video catalog.');return;}
  const token=++generation;phase='spinning';locked=0;
  row.classList.remove('jackpot');row.setAttribute('aria-label','Three video reels');
  reels.forEach(reel=>reel.mute());sounds.stop('win');sounds.stop('pair');
  button.disabled=true;label.textContent='SPINNING';status('SPINNING');notice('');
  sounds.play('click');sounds.play('spin',true);fx.spin=true;fx.start();
  const targets=chooseTargets(ready);
  const dots=setInterval(()=>{if(phase==='spinning')status('SPINNING'+'.'.repeat(1+Math.floor(performance.now()/200)%3));},200);
  try{
    await Promise.all(reels.map(async(reel,i)=>{
      await reel.spin(targets[i],sequence(pool,targets[i],DURATIONS[i].length),DURATIONS[i]);
      if(token!==generation)return;
      locked++;reel.el.classList.add('locked');later(()=>reel.el.classList.remove('locked'),170,token);
      sounds.stop('spin');sounds.play('lock');fx.burst(reel.el);
      if(locked<3)later(()=>{if(phase==='spinning'&&locked<3)sounds.play('spin',true);},180,token);
    }));
    clearInterval(dots);sounds.stop('spin');fx.spin=false;
    if(token!==generation)return;
    const match=outcome(targets);
    if(match==='jackpot'){
      phase='jackpot';status('JACKPOT','jackpot-text');
      reels[1].pause();reels[2].pause();row.classList.add('jackpot');row.setAttribute('aria-label','Expanded jackpot video');
      // Resize the existing player; never create a second audio timeline.
      reels[0].unmute();later(()=>sounds.play('win'),160,token);fx.jackpot();
      $('#machine').classList.add('shake');later(()=>$('#machine').classList.remove('shake'),250,token);
      for(const [ms,text] of [[180,'JACKPOT ✦'],[360,'✦ JACKPOT ✦'],[540,'JACKPOT ✦'],[760,'JACKPOT']])later(()=>status(text,'jackpot-text'),ms,token);
    }else{
      phase='ready';
      if(match==='pair'){status('TWO MATCHED','pair-text');later(()=>sounds.play('pair'),160,token);fx.burst(row,58);}
      else status('SPIN AGAIN');
    }
    if(reels.some(r=>!r.playing))notice('A video could not play here. Retry it or spin again.');
  }catch(error){clearInterval(dots);sounds.stopAll();fx.spin=false;reels.forEach(r=>{r.el.classList.remove('moving');r.fallback();});phase='ready';status('SPIN AGAIN');notice('Playback was interrupted. You can spin again.');}
  button.disabled=false;label.textContent='SPIN';
}
button.addEventListener('click',()=>phase==='idle'?start():spin());
document.addEventListener('visibilitychange',()=>{
  if(document.hidden){sounds.context?.suspend();reels.forEach(r=>r.pause());}
  else{sounds.context?.resume().catch(()=>{});reels.forEach((r,i)=>{if(r.current&&(phase!=='jackpot'||i===0)){if(r.video)r.video.play().catch(()=>r.fallback('Play video'));else r.player?.playVideo?.();}});if(phase==='jackpot')reels[0].unmute();}
});
