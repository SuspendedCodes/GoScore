// GoScore layout editor: 16:9 broadcast canvas, preview-only panel visibility,
// shared server-persisted geometry used by the live overlay and OBS.
const CRICKET = [
  ['bug','Scorebug'],['popup','Event pop-ups'],['p-testsum','Match summary'],['p-innsum','Innings summary'],
  ['p-scorecard','Scorecard'],['p-bowling','Bowling'],['p-partnership','Partnership'],['p-fow','Fall of wickets'],
  ['p-overs','Over-by-over'],['p-worm','Worm chart'],['p-target','Target'],['p-teams','Teams'],['p-toss','Toss'],
  ['p-result','Result'],['p-banner','Banner'],['p-summary','Summary'],['lower','Lower third']
];
const FOOTBALL = [
  ['bug','Scorebug'],['tracker','Match tracker'],['popup','Event pop-ups'],['pn-lineups','Line-ups'],
  ['pn-formation_home','Home formation'],['pn-formation_away','Away formation'],['pn-stats_classic','Match statistics'],
  ['pn-timeline','Timeline'],['pn-table','Standings'],['lower','Lower third']
];
const SAMPLE = {
  bug: ['SCOREBUG','HOME  2 — 1  AWAY','68:24  ·  LIVE'], popup:['EVENT POP-UP','GOAL!','Home team · 68\''],
  tracker:['MATCH TRACKER','HOME  2 — 1  AWAY','68:24 · 2nd half'], 'p-testsum':['MATCH SUMMARY','Renegades 164/6 · 18.2 ov','Strikers 161/8 · 20 ov'],
  'p-innsum':['INNINGS SUMMARY','Melbourne Renegades 164/6','Run rate 8.95'], 'p-scorecard':['SCORECARD','M. Whitmore 54 (32) *','E. Caldwell 28 (19)'],
  'p-bowling':['BOWLING','N. Williams 3.2 · 0 · 24 · 2','L. Moretti 2.0 · 0 · 18 · 1'],
  'p-partnership':['PARTNERSHIP','Whitmore / Caldwell','48 runs · 29 balls'], 'p-fow':['FALL OF WICKETS','1–24 · 2–67 · 3–103','Wicket timeline'],
  'p-overs':['OVER BY OVER','Over 16  ·  1  4  0  1  2  6','14 runs'], 'p-worm':['WORM CHART','Home 164 · Away 161','Run progression'],
  'p-target':['CHASE REQUIREMENTS','Target 165 · Need 24','From 10 balls'], 'p-teams':['TEAMS','Melbourne Renegades','Adelaide Strikers'],
  'p-toss':['TOSS','Renegades won the toss','Elected to bat'], 'p-result':['RESULT','Melbourne Renegades won','By 3 runs'],
  'p-summary':['MATCH SUMMARY','Renegades 164/6','Strikers 161/8'], 'p-banner':['BANNER','MATCH DAY · LIVE','Melbourne vs Adelaide'],
  lower:['LOWER THIRD','PLAYER OF THE MATCH','Marcus Whitmore'], 'pn-lineups':['LINE-UPS','HOME  4-3-3','AWAY  4-2-3-1'],
  'pn-formation_home':['HOME FORMATION','4-3-3','GK · DEF · MID · FWD'], 'pn-formation_away':['AWAY FORMATION','4-2-3-1','GK · DEF · MID · FWD'],
  'pn-stats_classic':['MATCH STATISTICS','Possession 54% — 46%','Shots 12 — 8'], 'pn-timeline':['MATCH TIMELINE','12\' Goal · 44\' Yellow card','68\' Goal'],
  'pn-table':['STANDINGS','1. Home FC  ·  24 pts','2. Away FC  ·  21 pts']
};
const DEFAULTS = {
  bug:{x:180,y:830,w:1560,h:180}, popup:{x:430,y:150,w:1060,h:250}, tracker:{x:80,y:80,w:600,h:150}, lower:{x:120,y:850,w:900,h:150},
  'p-scorecard':{x:50,y:70,w:850,h:560}, 'p-bowling':{x:1330,y:70,w:540,h:420}, 'p-overs':{x:1320,y:500,w:550,h:400},
  'p-testsum':{x:430,y:100,w:1060,h:400}, 'p-innsum':{x:360,y:120,w:1200,h:440}, 'p-partnership':{x:50,y:650,w:850,h:250},
  'p-fow':{x:50,y:650,w:850,h:250}, 'p-worm':{x:460,y:100,w:1000,h:550}, 'p-target':{x:500,y:80,w:920,h:300},
  'p-teams':{x:260,y:80,w:1400,h:700}, 'p-toss':{x:410,y:360,w:1100,h:300}, 'p-result':{x:360,y:260,w:1200,h:500},
  'p-summary':{x:360,y:260,w:1200,h:500}, 'p-banner':{x:260,y:760,w:1400,h:220},
  'pn-lineups':{x:100,y:100,w:800,h:650}, 'pn-formation_home':{x:50,y:100,w:600,h:700}, 'pn-formation_away':{x:1270,y:100,w:600,h:700},
  'pn-stats_classic':{x:460,y:100,w:1000,h:400}, 'pn-timeline':{x:300,y:700,w:1320,h:220}, 'pn-table':{x:550,y:100,w:820,h:650}
};
export function installLayoutEditor({ stage, sport, selector }) {
  const editing = new URLSearchParams(location.search).get('edit') === '1';
  const items = sport === 'football' ? FOOTBALL : CRICKET;
  let layout = {}, selected = new Set(items.map(x => x[0])), placeholders = new Map(), attached = new WeakSet(), baseSizes = new WeakMap();
  const request = async (method='GET', body) => {
    const res = await fetch(`/api/layout/${sport}`, {method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,cache:'no-store'});
    if(!res.ok) throw new Error(`Layout API returned ${res.status}`); return res.json();
  };
  const geom = id => layout[id] || DEFAULTS[id] || {x:80,y:80,w:600,h:240};
  // Scale the whole native graphic. Setting width/height on its outer node squashes
  // internal flex/table layouts and caused scorebug columns to collapse.
  const baseSize = el => {
    let b=baseSizes.get(el); if(b) return b;
    if(el.id==='bug'&&!el.querySelector('.bug')) return null;
    if(el.id==='popup'&&!el.querySelector('.pop')) return null;
    const measured=(el.id==='bug'&&el.querySelector('.bug'))?el.querySelector('.bug'):(el.id==='popup'&&el.querySelector('.pop'))?el.querySelector('.pop'):el;
    const w=measured.offsetWidth||parseFloat(getComputedStyle(measured).width)||600;
    const h=measured.offsetHeight||parseFloat(getComputedStyle(measured).height)||240;
    b={w:Math.max(1,w),h:Math.max(1,h)};baseSizes.set(el,b);return b;
  };
  const isSample = el => el.classList.contains('gs-layout-sample');
  const setGeom = (el,id,v) => {
    el.style.position='absolute';el.style.left=`${v.x}px`;el.style.top=`${v.y}px`;
    el.style.right='auto';el.style.bottom='auto';el.style.margin='0';el.style.boxSizing='border-box';
    if(el.id==='bug'){el.style.width='max-content';el.style.height='max-content';el.style.justifyContent='flex-start';}
    if(el.id==='popup'){el.style.width='max-content';el.style.height='max-content';el.style.justifyContent='flex-start';el.style.alignItems='flex-start';}
    if(isSample(el)) { el.style.width=`${v.w}px`;el.style.height=`${v.h}px`;el.style.transform='none'; }
    else {
      const b=baseSize(el);if(!b)return;const scale=Math.max(.08,Math.min(3,Number(v.w)/b.w||1));
      el.dataset.gsScale=String(scale);el.style.width='';el.style.height='';el.style.transformOrigin='top left';
      el.style.setProperty('transform',`scale(${scale})`,'important');
    }
  };
  const apply = () => {
    document.querySelectorAll(selector).forEach(el=>{const v=layout[el.id];if(v)setGeom(el,el.id,v);});
    placeholders.forEach((el,id)=>setGeom(el,id,geom(id)));
  };
  const refreshVisibility = () => {
    if(!editing)return;
    items.forEach(([id])=>{
      const real=document.getElementById(id), ph=placeholders.get(id), on=selected.has(id);
      if(real){real.style.visibility=on?'visible':'hidden';if(real.classList.contains('pn')&&!real.classList.contains('show'))real.style.display='block';}
      if(ph){const inactive=!real || !real.children.length || (real.classList.contains('pn')&&!real.classList.contains('show')) || (id==='bug'&&real.classList.contains('off')) || (id==='popup'&&!real.querySelector('*'));ph.style.display=on&&inactive?'flex':'none';}
    });
  };
  request().then(r=>{layout=r.layout||{};apply();if(editing)buildEditor();}).catch(err=>{console.error('Could not load shared overlay layout',err);if(editing)buildEditor();});
  if(!editing){const mo=new MutationObserver(apply);mo.observe(stage,{childList:true,subtree:true});return;}
  document.body.classList.add('gs-layout-edit');
  function buildEditor(){
    if(document.getElementById('gs-layout-sidebar'))return;
    const sidebar=document.createElement('aside');sidebar.id='gs-layout-sidebar';
    sidebar.innerHTML='<header><strong>Overlay layout</strong><small>1920 × 1080 canvas · Preview only · Saved positions apply to /overlay/live</small></header><div class="gs-layout-list"></div><footer><button data-save>Save layout</button><button data-reset>Reset</button><button data-done>Done</button><span class="gs-layout-status" role="status"></span></footer>';
    document.body.append(sidebar);const list=sidebar.querySelector('.gs-layout-list');
    items.forEach(([id,label])=>{const row=document.createElement('label');row.className='gs-layout-row';row.innerHTML=`<input type="checkbox" checked><span>${label}</span>`;row.querySelector('input').addEventListener('change',e=>{if(e.target.checked)selected.add(id);else selected.delete(id);refreshVisibility();});list.append(row);});
    const style=document.createElement('style');style.textContent=`
      html,body{width:100%;height:100%;margin:0;overflow:hidden;background:#10151c;color:#e8edf4;font:14px Segoe UI,Arial,sans-serif}
      body.gs-layout-edit #stage{position:absolute!important;left:12px!important;top:12px!important;width:1920px!important;height:1080px!important;transform-origin:top left!important;outline:1px solid #526173;background:#10151c;overflow:hidden}
      #gs-layout-sidebar{position:fixed;z-index:100000;right:0;top:0;bottom:0;width:300px;box-sizing:border-box;background:#171c23;border-left:1px solid #35404d;display:flex;flex-direction:column;padding:14px;gap:10px}
      #gs-layout-sidebar header{display:flex;flex-direction:column;gap:6px}#gs-layout-sidebar header strong{font-size:19px}#gs-layout-sidebar small{color:#aeb8c6;line-height:1.4}
      .gs-layout-list{overflow:auto;flex:1;border-top:1px solid #303945;border-bottom:1px solid #303945}.gs-layout-row{display:flex;align-items:center;gap:10px;padding:9px 4px;border-bottom:1px solid #252d37;cursor:pointer}.gs-layout-row input{accent-color:#3b82f6;width:16px;height:16px}
      #gs-layout-sidebar footer{display:grid;grid-template-columns:1fr 1fr;gap:8px}#gs-layout-sidebar button{background:#263446;color:#f5f7fa;border:1px solid #475569;border-radius:5px;padding:10px;cursor:pointer}#gs-layout-sidebar [data-save]{background:#2563eb;border-color:#2563eb}.gs-layout-status{grid-column:1/-1;min-height:30px;color:#a7f3d0;font-size:12px}
      body.gs-layout-edit .pn,body.gs-layout-edit #bug,body.gs-layout-edit #popup,body.gs-layout-edit #tracker,body.gs-layout-edit #lower{pointer-events:auto!important;transform:none!important;cursor:move;max-width:none!important;max-height:none!important}
      body.gs-layout-edit .pn:not(.show){display:block!important;visibility:hidden}body.gs-layout-edit #bug.off{display:flex!important;visibility:hidden}
      body.gs-layout-edit .gs-layout-selected{outline:2px solid #60a5fa!important;outline-offset:2px!important}
      .gs-layout-sample{position:absolute;z-index:50000;box-sizing:border-box;display:flex;flex-direction:column;padding:0;background:rgba(10,15,24,.96);border:1px solid rgba(255,255,255,.14);border-radius:14px;box-shadow:0 14px 40px rgba(0,0,0,.5);overflow:hidden;color:#fff;cursor:move;pointer-events:auto;font-family:Segoe UI,Arial,sans-serif}
      .gs-layout-sample .ph{background:var(--c,#1f6feb);padding:12px 22px;font-size:clamp(12px,1.56cqw,30px);font-weight:900;letter-spacing:.04em;display:flex;justify-content:space-between;gap:12px;flex-shrink:0}
      .gs-layout-sample .pb{padding:12px 22px;font-size:clamp(11px,1.35cqw,26px);min-height:0;overflow:hidden;flex:1}
      .gs-layout-sample table{width:100%;border-collapse:collapse}.gs-layout-sample th{font-size:clamp(9px,.9cqw,17px);opacity:.6;text-transform:uppercase;text-align:right;padding:2px 8px}.gs-layout-sample td{padding:5px 8px;text-align:right;font-weight:700}.gs-layout-sample th:first-child,.gs-layout-sample td:first-child{text-align:left}
      .gs-layout-sample .sample-scorebug{display:flex;flex-direction:column;height:100%;background:#0c111a}.gs-layout-sample .sample-main{display:flex;align-items:stretch;flex:1;min-height:0}.gs-layout-sample .sample-team{background:var(--c,#1f6feb);font-size:clamp(10px,1.7cqw,32px);font-weight:900;padding:12px;display:flex;align-items:center}.gs-layout-sample .sample-score{background:#fff;color:#0b1220;font-size:clamp(18px,3.5cqw,66px);font-weight:900;padding:12px;display:flex;align-items:center}.gs-layout-sample .sample-player{font-size:clamp(10px,1.4cqw,27px);padding:8px;display:flex;flex-direction:column;justify-content:center;flex:1;min-width:0}.gs-layout-sample .sample-status{background:var(--c,#1f6feb);padding:7px 12px;font-size:clamp(9px,1.3cqw,25px);font-weight:700}
      .gs-resize-handle{position:absolute;right:0;bottom:0;width:14px;height:14px;background:#3b82f6;border:1px solid #fff;border-radius:2px;cursor:nwse-resize;z-index:99999;touch-action:none;display:none}
      .gs-layout-selected>.gs-resize-handle,.gs-layout-sample.gs-layout-selected>.gs-resize-handle{display:block}
      /* Do not globally zero min-width in the live overlay: that collapses scorebug columns. */
      body.gs-layout-edit .gs-layout-sample *{min-width:0}
    `;document.head.append(style);
    const fit=()=>{const availW=Math.max(100,innerWidth-324),availH=Math.max(100,innerHeight-24),s=Math.min(availW/1920,availH/1080);stage.style.transform=`scale(${s})`;stage.style.left=`${12+(availW-1920*s)/2}px`;stage.style.top=`${12+(availH-1080*s)/2}px`;};fit();addEventListener('resize',fit);
    createPlaceholders();decorate();apply();refreshVisibility();
    sidebar.querySelector('[data-save]').onclick=async()=>{try{apply();await request('PUT',{layout});sidebar.querySelector('.gs-layout-status').textContent='Saved. /overlay/live and OBS will use these positions.';}catch(e){sidebar.querySelector('.gs-layout-status').textContent='Save failed: '+e.message;}};
    sidebar.querySelector('[data-reset]').onclick=async()=>{layout={};apply();try{await request('PUT',{layout});sidebar.querySelector('.gs-layout-status').textContent='Default layout restored.';}catch(e){sidebar.querySelector('.gs-layout-status').textContent='Reset failed: '+e.message;}};
    sidebar.querySelector('[data-done]').onclick=()=>{const u=new URL(location.href);u.searchParams.delete('edit');location.href=u.toString();};
  }
  function createPlaceholders(){
    items.forEach(([id,label])=>{
      const sample=document.createElement('div'); sample.className='gs-layout-sample'; sample.style.containerType='size'; sample.dataset.gsSample=id;
      const c=SAMPLE[id]||[label.toUpperCase(),`${label} preview`,`Sample content · resize and position`];
      if(id==='bug'){
        sample.innerHTML=`<div class="sample-scorebug"><div class="sample-main"><div class="sample-team">MELBOURNE RENEGADES</div><div class="sample-score">164/6<br><small style="font-size:.38em">18.2 ov</small></div><div class="sample-player"><b>Marcus Whitmore *</b><span>54 (32)</span><b>Ethan Caldwell</b><span>28 (19)</span></div><div class="sample-player"><b>Noah Williams</b><span>2–24 · 3.2 ov</span><span>●　4　●　6　W</span></div><div class="sample-team">CRR 8.95</div></div><div class="sample-status">LIVE · TARGET 165 · NEED 24 RUNS FROM 10 BALLS</div></div>`;
      } else if(id==='popup') {
        sample.innerHTML=`<div class="hd" style="background:#1f9d55;padding:12px 20px;font-size:clamp(16px,4cqw,72px);font-weight:900;text-align:center">GOAL!</div><div class="bd" style="padding:12px 20px;background:#0e1420;text-align:center;font-size:clamp(11px,1.9cqw,36px);font-weight:700">Melbourne Renegades · 68′</div>`;
      } else {
        const rows = id==='p-scorecard' ? [['Batter','R','B','4s','6s','SR'],['M. Whitmore *','54','32','5','2','168.8'],['E. Caldwell','28','19','3','1','147.4'],['L. Hartley','17','12','2','0','141.7'],['Extras','12','','','','']] :
          id==='p-bowling' ? [['Bowler','O','M','R','W','Econ'],['N. Williams','3.2','0','24','2','7.20'],['L. Moretti','2.0','0','18','1','9.00'],['S. Brooks','4.0','0','31','1','7.75']] :
          id==='pn-stats_classic' ? [['Statistic','Home','Away'],['Possession','54%','46%'],['Shots','12','8'],['On target','6','3'],['Corners','7','4']] :
          id==='p-teams'||id==='pn-lineups' ? [['MELBOURNE RENEGADES','ADELAIDE STRIKERS'],['M. Whitmore (c)','A. Reid (c)'],['E. Caldwell','M. Clarke'],['L. Hartley','D. Foster'],['O. Bennett †','T. Laurent †']] :
          [['DETAIL','VALUE'],[c[1],'54'],[c[2],'28'],['Status','LIVE']];
        sample.innerHTML=`<div class="ph"><span>${c[0]}</span><span style="opacity:.7">${id.startsWith('pn-')?'LIVE':'T20'}</span></div><div class="pb"><table><thead><tr>${rows[0].map(v=>`<th>${v}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map(row=>`<tr>${row.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table><div style="margin-top:10px;opacity:.65;font-size:clamp(10px,.95cqw,18px)">${c[1]} · ${c[2]}</div></div>`;
      }
      stage.append(sample); placeholders.set(id,sample);
    });
  }
  function decorate(){
    let active=null;
    const attach=(el,id=el.id)=>{if(!id||attached.has(el))return;attached.add(el);el.dataset.gsEditorAttached='1';
      const handle=document.createElement('div');handle.className='gs-resize-handle';el.append(handle);
      el.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('#gs-layout-sidebar'))return;document.querySelectorAll('.gs-layout-selected').forEach(n=>n.classList.remove('gs-layout-selected'));el.classList.add('gs-layout-selected');begin(e,el,id,e.target===handle);});
    };
    const begin=(e,el,id,resize)=>{
      const r=el.getBoundingClientRect(),sr=stage.getBoundingClientRect(),sc=sr.width/1920||1;
      const x=(r.left-sr.left)/sc,y=(r.top-sr.top)/sc;
      if(isSample(el)) active={el,id,resize,sx:e.clientX,sy:e.clientY,x,y,w:r.width/sc,h:r.height/sc,sc,sample:true};
      else {const b=baseSize(el);if(!b)return;const scale=(r.width/sc)/b.w;active={el,id,resize,sx:e.clientX,sy:e.clientY,x,y,w:r.width/sc,h:r.height/sc,sc,sample:false,baseW:b.w,baseH:b.h,scale};}
      el.setPointerCapture?.(e.pointerId);e.preventDefault();e.stopPropagation();
    };
    const move=e=>{
      if(!active)return;const dx=(e.clientX-active.sx)/active.sc,dy=(e.clientY-active.sy)/active.sc,el=active.el;
      el.style.position='absolute';el.style.right='auto';el.style.bottom='auto';el.style.margin='0';
      if(active.resize){
        if(active.sample){el.style.width=Math.max(120,Math.min(1920-active.x,active.w+dx))+'px';el.style.height=Math.max(70,Math.min(1080-active.y,active.h+dy))+'px';}
        else {
          // Uniform scaling preserves the real graphic's internal layout and typography.
          const sx=(active.w+dx)/active.baseW,sy=(active.h+dy)/active.baseH;
          const scale=Math.max(.08,Math.min(3,Math.max(sx,sy)));
          el.dataset.gsScale=String(scale);el.style.width='';el.style.height='';el.style.transformOrigin='top left';
          el.style.setProperty('transform',`scale(${scale})`,'important');
        }
      } else {el.style.left=Math.max(0,Math.min(1920-active.w,active.x+dx))+'px';el.style.top=Math.max(0,Math.min(1080-active.h,active.y+dy))+'px';}
    };
    const finish=()=>{
      if(!active)return;const a=active,el=a.el,x=Math.round(parseFloat(el.style.left)||0),y=Math.round(parseFloat(el.style.top)||0);
      if(a.sample) layout[a.id]={x,y,w:Math.round(el.offsetWidth),h:Math.round(el.offsetHeight)};
      else {const scale=Number(el.dataset.gsScale)||a.scale||1;layout[a.id]={x,y,w:Math.round(a.baseW*scale),h:Math.round(a.baseH*scale)};}
      active=null;
    };
    stage.addEventListener('pointermove',move);stage.addEventListener('pointerup',finish);stage.addEventListener('pointercancel',finish);
    const mo=new MutationObserver(()=>{apply();document.querySelectorAll(selector).forEach(el=>attach(el));refreshVisibility();});mo.observe(stage,{childList:true,subtree:true});
  }
}
