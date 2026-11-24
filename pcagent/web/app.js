const $=s=>document.querySelector(s);
const chat=$('#chat'),input=$('#input'),sendBtn=$('#send');
let els={},items={},busy=false,configured=false,servers=[],PROF={},engine='';
const NAMES={list_media:'Просмотр медиафайлов',make_video:'Создание видео',make_voice:'Озвучка',check_video:'Проверка видео',publish_project:'Публикация',check_page:'Автопроверка страницы',screenshot_page:'Скриншот',read_document:'Чтение документа',create_docx:'Создание Word',create_xlsx:'Создание Excel',web_search:'Поиск в интернете',fetch_url:'Чтение страницы',open_preview:'Предпросмотр',preview_errors:'Ошибки страницы',list_dir:'Просмотр папки',read_file:'Чтение файла',write_file:'Запись файла',edit_file:'Правка файла',make_dir:'Создание папки',move_file:'Перемещение',delete_file:'Удаление',search:'Поиск',run_command:'Команда'};
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function md(s){return s.split('```').map((p,i)=>{
  if(i%2)return '<pre><code>'+esc(p.replace(/^[\w+#.-]*\n/,''))+'</code></pre>';
  return esc(p).replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>').replace(/^#{1,4} (.*)$/gm,'<b>$1</b>').replace(/\n/g,'<br>');
}).join('');}
async function api(p,b){try{const r=await fetch('/api/'+p,{method:'POST',headers:{'X-Token':TOKEN,'Content-Type':'application/json'},body:JSON.stringify(b||{})});return await r.json();}catch(e){return {error:String(e)};}}
function toast(t){const e=$('#toast');e.textContent=t;e.style.display='block';setTimeout(()=>e.style.display='none',3500);}
const brief=a=>{a=a||{};return a.path||a.command||a.pattern||(a.src?a.src+' → '+a.dst:'')||'';};
function scrollDown(force){if(force||chat.scrollHeight-chat.scrollTop-chat.clientHeight<160)chat.scrollTop=chat.scrollHeight;}
function fillTool(el,it){
  const done=it.result!==null&&it.result!==undefined;
  el.innerHTML='<summary>'+(done?'✓':'⏳')+' <b>'+esc(NAMES[it.name]||it.name)+'</b> <span class="br">'+esc(brief(it.args).slice(0,90))+'</span>'+(it.undo?'<button class="ub">↩ Отменить</button>':'')+(it.undone?' <span class="dim">↩ отменено</span>':'')+'</summary><pre>'+esc(JSON.stringify(it.args,null,1).slice(0,3000))+'</pre>'+(done?'<pre class="res">'+esc(it.result)+'</pre>':'');
}
function fillConfirm(el,it){
  el.className='confirm '+it.state;
  let h='<div>'+(it.state==='pending'?'❓ ':it.state==='yes'?'✅ ':'⛔ ')+esc(it.title)+'</div>';
  if(it.detail)h+='<pre>'+esc(it.detail)+'</pre>';
  if(it.state==='pending')h+='<div class="btns"><button data-a="yes">Разрешить</button><button data-a="always">Всегда разрешать</button><button data-a="no" class="no">Отклонить</button></div>';
  el.innerHTML=h;
  el.querySelectorAll('button').forEach(b=>b.onclick=()=>api('confirm',{id:it.id,answer:b.dataset.a}));
}
function fillPlan(el,it){
  el.className='plan '+it.state;
  if(it.state==='pending'){
    el.innerHTML='<b>📋 План действий</b><div class="dim">Можно отредактировать шаги перед запуском.</div><textarea></textarea><div class="btns row"><button class="go">✅ Выполнять</button><button class="no">Отклонить</button></div>';
    const ta=el.querySelector('textarea');ta.value=it.steps;
    el.querySelector('.go').onclick=()=>api('plan',{id:it.id,answer:'yes',text:ta.value});
    el.querySelector('.no').onclick=()=>api('plan',{id:it.id,answer:'no'});
  }else el.innerHTML='<b>'+(it.state==='yes'?'✅ План утверждён':'⛔ План отклонён')+'</b><pre>'+esc(it.steps)+'</pre>';
}
function showCtx(c){const el=$('#ctx');if(!c){el.textContent='';return;}el.textContent='Контекст '+c.pct+'%';el.style.color=c.pct>=80?'var(--bad)':c.pct>=60?'var(--warn)':'var(--dim)';}
function fmtN(n){return n>=1e6?(n/1e6).toFixed(2)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':String(n);}
function showUsage(u){$('#usage').textContent=u&&(u.prompt||u.completion)?('Токены: ↑'+fmtN(u.prompt)+' ↓'+fmtN(u.completion)+(u.cost!=null?' · ≈$'+u.cost.toFixed(4):'')):'';}
function hostUrl(u){try{const x=new URL(u);x.hostname=location.hostname;return x.href;}catch(e){return u;}}
function addItem(it){
  let el;
  if(it.role==='user'){el=document.createElement('div');el.className='msg user';el.textContent=it.text;}
  else if(it.role==='assistant'){el=document.createElement('div');el.className='msg bot';el.dataset.raw=it.text||'';el.innerHTML=md(el.dataset.raw);}
  else if(it.role==='tool'){el=document.createElement('details');el.className='tool';fillTool(el,it);}
  else if(it.role==='confirm'){el=document.createElement('div');fillConfirm(el,it);}
  else if(it.role==='image'){el=document.createElement('div');el.className='linkcard';el.innerHTML='📷 '+esc(it.title)+'<br><img style="max-width:100%;border-radius:8px;margin-top:6px;cursor:zoom-in" src="'+esc(it.url)+'?t='+TOKEN+'">';el.querySelector('img').onclick=e=>window.open(e.target.src,'_blank');}
  else if(it.role==='plan'){el=document.createElement('div');fillPlan(el,it);}
  else if(it.role==='link'){el=document.createElement('div');el.className='linkcard';el.innerHTML='▶ <a target="_blank" rel="noopener" href="'+esc(hostUrl(it.url))+'">Открыть в браузере: '+esc(it.title)+'</a>';}
  else{el=document.createElement('div');el.className=it.role;el.textContent=it.text;}
  items[it.id]=it;els[it.id]=el;chat.appendChild(el);
  $('#hello').style.display='none';scrollDown(it.role==='user');
}
function renderTree(list){
  const t=$('#tree');t.innerHTML='';
  if(!list.length){t.innerHTML='<div class="dim">Пока пусто</div>';return;}
  list.forEach(f=>{const d=document.createElement('div');d.style.paddingLeft=(f.depth*13+4)+'px';
    d.textContent=(f.d?'📁 ':'📄 ')+f.p.split('/').pop();d.title=f.p;d.onclick=async()=>{const r=await api('open',{path:f.p});if(r.error)toast(r.error);};t.appendChild(d);});
}
function setBusy(b,l){busy=b;if(l!==undefined)engine=l;sendBtn.textContent=b?'Стоп':'Отправить';sendBtn.className=b?'stop':'';$('#stt').textContent=b?'⏳ Агент работает'+(engine?' ('+engine+')':'')+'…':'';}
function renderProfiles(p,mode){
  PROF=p||{};const box=$('#pm');box.innerHTML='';
  [['cloud','☁ Облако'],['local','💻 Локально']].forEach(([k,label])=>{
    if(!PROF[k])return;
    const d=document.createElement('div');d.innerHTML='<div class="dim">'+label+' — модель'+(PROF[k].tools==='text'?' · текстовый режим':'')+'</div>';
    const i=document.createElement('input');i.type='text';i.setAttribute('list','models');i.value=PROF[k].model||'';
    i.onfocus=async()=>{const r=await api('models',{profile:k});const dl=$('#models');dl.innerHTML='';(r.models||[]).forEach(m=>{const o=document.createElement('option');o.value=m;dl.appendChild(o);});};
    i.onchange=()=>api('model',{profile:k,model:i.value});
    d.appendChild(i);box.appendChild(d);
  });
  const m=$('#mode');m.options[0].disabled=Object.keys(PROF).length<2;m.options[1].disabled=!PROF.cloud;m.options[2].disabled=!PROF.local;m.value=mode||'auto';
}
function onEvent(e){
  if(e.type==='snapshot'){
    $('#ws').textContent=e.workspace;$('#auto').checked=e.auto;$('#plan').checked=e.plan;$('#pin').value=e.prices[0]??'';$('#pout').value=e.prices[1]??'';showUsage(e.usage);renderProfiles(e.profiles,e.mode);
    chat.innerHTML='';els={};items={};e.transcript.forEach(addItem);
    $('#hello').style.display=e.transcript.length?'none':'block';
    $('#perr').style.display='none';$('#verify').checked=!!e.verify;showCtx(e.ctx);$('#ctxlocal').value=(e.profiles.local&&e.profiles.local.ctx)||'';$('#ctxcloud').value=(e.profiles.cloud&&e.profiles.cloud.ctx)||'';$('#autopilot').checked=!!e.autopilot;$('#forcetext').checked=!!e.force_text;const dk=e.docker||{};$('#dockon').checked=!!dk.on;$('#dockimg').value=dk.image||'';$('#docknet').checked=dk.net===false;
    renderTree(e.tree);setBusy(e.busy);
    const rs=$('#recent');rs.innerHTML='';(e.recent||[]).forEach(p=>{const o=document.createElement('option');o.value=p;o.textContent=p.split(/[\\/]/).filter(Boolean).pop()+' — '+p;if(p===e.workspace)o.selected=true;rs.appendChild(o);});configured=e.configured;
    $('#setup').style.display=e.configured?'none':'flex';scrollDown(true);
  }else if(e.type==='item')addItem(e.item);
  else if(e.type==='delta'){const el=els[e.id];if(el){el.dataset.raw+=e.delta;el.innerHTML=md(el.dataset.raw);scrollDown();}}
  else if(e.type==='update'){const it=Object.assign(items[e.id]||{},e.patch),el=els[e.id];if(el){if(it.role==='tool')fillTool(el,it);else if(it.role==='confirm')fillConfirm(el,it);else if(it.role==='plan')fillPlan(el,it);else if(it.role==='assistant'){el.dataset.raw=it.text||'';el.innerHTML=md(el.dataset.raw);}}scrollDown();}
  else if(e.type==='tree')renderTree(e.items);
  else if(e.type==='auto')$('#auto').checked=e.value;
  else if(e.type==='busy')setBusy(e.value,e.engine);
  else if(e.type==='engine'){engine=e.label;if(busy)setBusy(true);}
  else if(e.type==='preview_errors'){$('#perr').style.display=e.count?'block':'none';$('#perrt').textContent='⚠ В предпросмотре ошибок: '+e.count;}
  else if(e.type==='usage')showUsage(e);
  else if(e.type==='ctx')showCtx(e);
  else if(e.type==='status'){if(e.text)$('#stt').textContent=e.text;else if(busy)setBusy(true);}
  else if(e.type==='mode')$('#mode').value=e.value;
  else if(e.type==='profiles'){renderProfiles(e.profiles,e.mode);$('#forcetext').checked=!!e.force_text;}
}
chat.addEventListener('click',async e=>{const b=e.target.closest('.ub');if(!b)return;e.preventDefault();e.stopPropagation();
  const d=b.closest('details');const id=Object.keys(els).find(k=>els[k]===d);const r=await api('undo',{id:items[id].undo});if(r.error)toast(r.error);});
const es=new EventSource('/api/events?t='+TOKEN);
es.onmessage=m=>onEvent(JSON.parse(m.data));
async function send(){
  if(busy){api('stop');return;}
  const t=input.value.trim();if(!t)return;
  const r=await api('chat',{message:t});
  if(r.error){toast(r.error);return;}
  input.value='';autosize();
}
function autosize(){input.style.height='auto';input.style.height=Math.min(input.scrollHeight,200)+'px';}
input.addEventListener('input',autosize);
input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!busy)send();}});
sendBtn.onclick=send;
document.querySelectorAll('.chips button').forEach(b=>b.onclick=()=>{input.value=b.textContent;input.focus();autosize();});
$('#auto').onchange=e=>api('auto',{value:e.target.checked});
$('#newchat').onclick=async()=>{const r=await api('reset');if(r.error)toast(r.error);};
$('#openws').onclick=()=>api('open',{path:'.'});
$('#preview').onclick=async()=>{const r=await api('preview',{});if(r.error){toast(r.error);return;}window.open(hostUrl(r.url),'_blank');if(r.missing&&r.missing.length)toast('Нет файлов: '+r.missing.slice(0,5).join(', '));};
$('#undolast').onclick=async()=>{const r=await api('undo',{id:'last'});if(r.error)toast(r.error);};
$('#perrhide').onclick=()=>$('#perr').style.display='none';
$('#perrfix').onclick=async()=>{const r=await api('chat',{message:'В предпросмотре страницы появились ошибки. Вызови preview_errors, найди причину и исправь, потом снова открой предпросмотр.'});if(r.error)toast(r.error);else $('#perr').style.display='none';};
$('#menu').onclick=()=>document.querySelector('aside').classList.toggle('open');
async function loadHist(){
  const r=await api('history');const box=$('#hbox');box.innerHTML='';
  $('#purl').value=(r.publish&&r.publish.url)||'';$('#pbranch').value=(r.publish&&r.publish.branch)||'';
  if(!r.git){$('#hmsg').textContent='Git не установлен — поставь с git-scm.com, тогда заработает история.';return;}
  if(!r.repo){$('#hmsg').textContent='История выключена для этой папки.';
    const b=document.createElement('button');b.textContent='Включить историю (git)';b.onclick=async()=>{const x=await api('git_init');if(x.error)toast(x.error);else loadHist();};box.appendChild(b);return;}
  $('#hmsg').textContent='Каждое задание агента сохраняется как версия. Можно вернуться к любой.';
  const l=document.createElement('label');l.innerHTML='<input type="checkbox"> Сохранять каждое задание автоматически';l.firstChild.checked=r.auto;
  l.firstChild.onchange=e=>api('git_auto',{value:e.target.checked});box.appendChild(l);
  (r.commits||[]).forEach(c=>{const d=document.createElement('div');d.className='hrow';
    d.innerHTML='<span>'+esc(c.h)+' · '+esc(c.date)+' · '+esc(c.subject)+'</span>';
    const b=document.createElement('button');b.textContent='Вернуть';b.onclick=async()=>{if(!confirm('Вернуть проект к версии '+c.h+'? Текущее состояние сохранится в истории.'))return;
      const x=await api('restore',{hash:c.h});if(x.error)toast(x.error);else{loadHist();}};d.appendChild(b);box.appendChild(d);});
}
$('#histbtn').onclick=()=>{$('#hist').style.display='flex';$('#pres').textContent='';loadHist();};
$('#pclose').onclick=()=>$('#hist').style.display='none';
$('#pgo').onclick=async()=>{$('#pres').style.color='var(--dim)';$('#pres').textContent='Отправляю… (может занять до пары минут)';
  const r=await api('publish',{url:$('#purl').value,branch:$('#pbranch').value});
  $('#pres').style.color=r.error?'var(--bad)':'var(--ok)';$('#pres').textContent=r.error||('✅ '+(r.msg||'Готово'));loadHist();};
function tgShow(r){const e=$('#tgst');e.style.color=r.error?'var(--bad)':'var(--dim)';
  e.textContent=r.error||(r.on?('✅ Бот @'+r.bot+' включён. Подключено чатов: '+r.chats+'\nЧтобы подключить телефон, отправь боту:  /pair '+r.pair):'Бот выключен.');}
$('#tgbtn').onclick=async()=>{$('#tg').style.display='flex';tgShow(await api('tg_status'));};
$('#tgok').onclick=async()=>{$('#tgst').textContent='Проверяю…';const r=await api('tg_setup',{token:$('#tgtoken').value});if(!r.error)$('#tgtoken').value='';tgShow(r);};
$('#tgoff').onclick=async()=>tgShow(await api('tg_off'));
$('#tgclose').onclick=()=>$('#tg').style.display='none';
$('#recent').onchange=async e=>{const r=await api('workspace',{path:e.target.value});if(r.error)toast(r.error);};
const SR=window.SpeechRecognition||window.webkitSpeechRecognition;let rec=null,recOn=false;
if(SR)$('#mic').style.display='inline-block';
$('#mic').onclick=()=>{
  if(recOn){rec.stop();return;}
  rec=new SR();rec.lang='ru-RU';rec.interimResults=true;rec.continuous=true;
  const base=input.value;let fin='';
  rec.onresult=e=>{let tmp='';for(let i=e.resultIndex;i<e.results.length;i++){const r=e.results[i];if(r.isFinal)fin+=r[0].transcript+' ';else tmp+=r[0].transcript;}
    input.value=(base?base+' ':'')+fin+tmp;autosize();};
  rec.onerror=e=>toast(e.error==='not-allowed'||e.error==='service-not-allowed'?'Нет доступа к микрофону. По сети (http) браузер его блокирует — на телефоне используй диктовку клавиатуры или Telegram.':'Голос: '+e.error);
  rec.onend=()=>{recOn=false;$('#mic').textContent='🎤';$('#mic').classList.remove('rec');};
  rec.start();recOn=true;$('#mic').textContent='⏹';$('#mic').classList.add('rec');
};
function kindText(t){return t.kind==='every'?('каждые '+t.minutes+' мин'):(t.kind==='weekdays'?'по будням ':'каждый день ')+t.time;}
function schRender(r){
  if(r.error){$('#scherr').textContent=r.error;return;}$('#scherr').textContent='';
  $('#schws').textContent=r.ws;const box=$('#schlist');box.innerHTML='';
  if(!r.tasks.length)box.innerHTML='<div class="dim">Заданий пока нет.</div>';
  r.tasks.forEach(t=>{const d=document.createElement('div');d.className='hrow';
    d.innerHTML='<span>'+(t.enabled===false?'⏸ ':'⏰ ')+esc(kindText(t))+' · '+esc(t.workspace.split(/[\\/]/).filter(Boolean).pop())+' · «'+esc(t.text.slice(0,70))+'»'+(t.last_run?' <span class="dim">(последний запуск '+esc(t.last_run.replace('T',' '))+')</span>':'')+'</span>';
    const mk=(txt,fn)=>{const b=document.createElement('button');b.textContent=txt;b.onclick=fn;d.appendChild(b);};
    mk('▶',async()=>{const x=await api('sched_run',{id:t.id});if(x.error)toast(x.error);else{$('#sch').style.display='none';}});
    mk(t.enabled===false?'Вкл':'Выкл',async()=>schRender(await api('sched_toggle',{id:t.id})));
    mk('✖',async()=>schRender(await api('sched_del',{id:t.id})));box.appendChild(d);});
}
$('#schbtn').onclick=async()=>{$('#sch').style.display='flex';schRender(await api('sched_list'));};
$('#schclose').onclick=()=>$('#sch').style.display='none';
$('#schkind').onchange=e=>{const ev=e.target.value==='every';$('#schmin').style.display=ev?'block':'none';$('#schtime').style.display=ev?'none':'block';};
$('#schadd').onclick=async()=>{const r=await api('sched_add',{text:$('#schtext').value,kind:$('#schkind').value,time:$('#schtime').value,minutes:$('#schmin').value,auto:$('#schauto').checked});
  schRender(r);if(!r.error)$('#schtext').value='';};
$('#probe').onclick=async()=>{const r=await api('probe');if(r.error)toast(r.error);else toast('Проверяю… результат появится в чате');};
$('#forcetext').onchange=e=>api('force_text',{value:e.target.checked});
$('#autopilot').onchange=e=>api('autopilot',{value:e.target.checked});
async function vidLoad(){
  const r=await api('media_list'),c=r.counts||{};
  const box=$('#vmedia');
  box.innerHTML=(r.ffmpeg?'':'<div style="color:var(--warn)">⚠ ffmpeg не найден — без него видео не собрать. Нажми «Установить ffmpeg».</div>')+
    '<div>Найдено: 🖼 фото '+(c.image||0)+' · 🎞 видео '+(c.video||0)+' · 🎵 музыка '+(c.audio||0)+' · 📝 тексты '+(c.text||0)+'</div>'+
    ((r.files||[]).length?'<div class="dim" style="margin-top:4px;word-break:break-all">'+esc(r.files.slice(0,12).join(', '))+((r.files.length>12)?' …':'')+'</div>':'<div class="dim">Пока пусто — добавь файлы.</div>');
  $('#vinstall').style.display=r.ffmpeg?'none':'inline-block';
}
async function uploadMedia(files){
  $('#vst').textContent='Загружаю файлы…';
  for(const f of files){const r=await fetch('/api/upload?name='+encodeURIComponent(f.name),{method:'POST',headers:{'X-Token':TOKEN},body:f});
    const j=await r.json();if(!j.path)toast(j.error||'Ошибка загрузки');}
  $('#vst').textContent='';vidLoad();
}
$('#videobtn').onclick=()=>{$('#video').style.display='flex';vidLoad();};
$('#vclose').onclick=()=>$('#video').style.display='none';
$('#vadd').onclick=()=>$('#vfile').click();
$('#vfile').onchange=e=>{uploadMedia(e.target.files);e.target.value='';};
$('#vinstall').onclick=async()=>{$('#vst').textContent='Устанавливаю ffmpeg (до пары минут)…';const r=await api('video_install');
  $('#vst').textContent=r.error?('Не вышло: '+r.error):'ffmpeg установлен.';vidLoad();};
$('#vgo').onclick=async()=>{const r=await api('make_video',{idea:$('#videa').value,format:$('#vfmt').value,captions:$('#vcap').checked,music:$('#vmus').checked,voice:$('#vvoice').checked,seconds:$('#vsec').value});
  if(r.error){$('#vst').style.color='var(--bad)';$('#vst').textContent=r.error;return;}$('#video').style.display='none';$('#videa').value='';};
let gameGenre='';
$('#gamebtn').onclick=()=>{$('#game').style.display='flex';};
$('#gameclose').onclick=()=>$('#game').style.display='none';
document.querySelectorAll('#game .chips button').forEach(b=>b.onclick=()=>{gameGenre=b.textContent;document.querySelectorAll('#game .chips button').forEach(x=>x.style.outline='');b.style.outline='2px solid var(--acc)';});
$('#gamego').onclick=async()=>{const r=await api('make_game',{idea:$('#gameidea').value,genre:gameGenre,publish:$('#gamepub').checked});
  if(r.error){toast(r.error);return;}$('#game').style.display='none';$('#gameidea').value='';};
$('#compact').onclick=async()=>{const r=await api('compact');if(r.error)toast(r.error);};
['#ctxlocal','#ctxcloud'].forEach(i=>$(i).onchange=()=>api('ctx_set',{local:$('#ctxlocal').value,cloud:$('#ctxcloud').value}));
$('#verify').onchange=e=>api('verify',{value:e.target.checked});
async function dockSave(){const r=await api('docker_set',{on:$('#dockon').checked,image:$('#dockimg').value,nonet:$('#docknet').checked});if(r.error){toast(r.error);$('#dockon').checked=false;}}
['#dockon','#docknet'].forEach(i=>$(i).onchange=dockSave);$('#dockimg').onchange=dockSave;
$('#plan').onchange=e=>api('plan_mode',{value:e.target.checked});
$('#rules').onclick=async()=>{const r=await api('rules');if(r.error)toast(r.error);};
['#pin','#pout'].forEach(id=>$(id).onchange=async()=>{const r=await api('prices',{inp:$('#pin').value,out:$('#pout').value});if(r.error)toast(r.error);});
$('#mode').onchange=e=>api('mode',{mode:e.target.value});
$('#rekey').onclick=()=>{$('#setup').style.display='flex';$('#sclose').style.display=configured?'block':'none';showTab(PROF.local&&!PROF.cloud?'local':'cloud');};
$('#sclose').onclick=()=>$('#setup').style.display='none';
function showTab(t){
  $('#pcloud').style.display=t==='cloud'?'flex':'none';$('#plocal').style.display=t==='local'?'flex':'none';
  $('#tabcloud').className=t==='cloud'?'on':'';$('#tablocal').className=t==='local'?'on':'';
  if(t==='local')scanLocal();
}
$('#tabcloud').onclick=()=>showTab('cloud');$('#tablocal').onclick=()=>showTab('local');
function fillModels(){const s=servers[$('#lsrv').value];const m=$('#lmodel');m.innerHTML='';
  (s?s.models:[]).forEach(x=>{const o=document.createElement('option');o.value=o.textContent=x;m.appendChild(o);});}
async function scanLocal(){
  $('#lerr').style.color='var(--dim)';$('#lerr').textContent='Ищу локальный сервер…';
  const r=await api('local_scan',{base_url:$('#lurl').value});servers=r.servers||[];
  const sel=$('#lsrv');sel.innerHTML='';
  servers.forEach((s,i)=>{const o=document.createElement('option');o.value=i;o.textContent=s.name+' — '+s.base_url+' ('+s.models.length+' мод.)';sel.appendChild(o);});
  fillModels();$('#lerr').style.color='var(--bad)';
  $('#lerr').textContent=servers.length?(servers.some(s=>s.models.length)?'':'Сервер найден, но моделей нет. Скачай модель, например: ollama pull qwen2.5:7b'):'Сервер не найден. Запусти Ollama (ollama serve) или LM Studio (Developer → Start Server) и нажми «Найти снова».';
}
$('#lsrv').onchange=fillModels;$('#lscan').onclick=scanLocal;
$('#lok').onclick=async()=>{
  const s=servers[$('#lsrv').value];const url=s?s.base_url:$('#lurl').value;
  $('#lerr').style.color='var(--dim)';$('#lerr').textContent='Подключаю…';
  const r=await api('local_setup',{base_url:url,model:$('#lmodel').value});
  if(r.error){$('#lerr').style.color='var(--bad)';$('#lerr').textContent=r.error;}else $('#lerr').textContent='';
};

$('#keyok').onclick=async()=>{$('#keyerr').textContent='Проверяю…';const r=await api('setup',{api_key:$('#key').value,base_url:$('#keyurl').value,model:$('#keymodel').value});
  if(r.error)$('#keyerr').textContent=r.error;else{$('#keyerr').textContent='';$('#key').value='';}};
$('#key').addEventListener('keydown',e=>{if(e.key==='Enter')$('#keyok').click();});
$('#pick').onclick=async()=>{
  let r=await api('pick');let p=r.path;
  if(r.error==='no_tk')p=prompt('Путь к рабочей папке:');
  if(!p)return;const w=await api('workspace',{path:p});if(w.error)toast(w.error);
};
async function upload(files){
  for(const f of files){
    const r=await fetch('/api/upload?name='+encodeURIComponent(f.name),{method:'POST',headers:{'X-Token':TOKEN},body:f});
    const j=await r.json();
    if(j.path)input.value+=(input.value?' ':'')+'[файл: '+j.path+']';else toast(j.error||'Ошибка загрузки');
  }
  input.focus();autosize();
}
$('#attach').onclick=()=>$('#file').click();
$('#file').onchange=e=>{upload(e.target.files);e.target.value='';};
addEventListener('dragover',e=>e.preventDefault());
addEventListener('drop',e=>{e.preventDefault();if(!e.dataTransfer.files.length)return;if($('#video').style.display==='flex')uploadMedia(e.dataTransfer.files);else upload(e.dataTransfer.files);});
