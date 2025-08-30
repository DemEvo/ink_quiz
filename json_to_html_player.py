
from __future__ import annotations
import json

def build_html_player(data: dict) -> str:
    """Return a self-contained HTML player for Ink JSON (our simplified schema)."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    css = r"""
  :root { --bg:#0b1324; --card:#121b34; --muted:#9fb0d1; --accent:#5aa8ff; --ok:#39d98a; --warn:#ffb020; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial; background:var(--bg); color:#e9f1ff; }
  .wrap { max-width: 920px; margin: 32px auto; padding: 0 16px; }
  header { margin-bottom: 16px; }
  h1 { font-size: 22px; margin:0 0 6px 0; }
  .meta { color: var(--muted); font-size: 14px; }
  .card { background: var(--card); border-radius: 16px; padding: 20px; box-shadow: 0 8px 24px rgba(0,0,0,.25);}
  .speaker { font-weight: 700; letter-spacing:.2px; margin-bottom:8px; color:#d4e5ff; }
  .text { font-size: 20px; line-height: 1.5; margin: 6px 0 12px 0; }
  .opts { display: grid; gap: 10px; margin-top: 10px; }
  .btn { appearance: none; border:1px solid rgba(255,255,255,.08); background: #162241; color:#e9f1ff;
         border-radius: 12px; padding: 12px 14px; text-align:left; cursor:pointer; font-size:16px; }
  .btn:hover { border-color: rgba(90,168,255,.6); }
  .sys { color: var(--muted); font-size: 13px; margin-top: 10px; }
  .footer { display:flex; gap:8px; margin-top:12px; }
  .chip { font-size:12px; color:#cfe3ff; background:#18294d; border:1px solid rgba(255,255,255,.08);
          padding:6px 8px; border-radius:999px; }
  .end { color: var(--ok); font-weight: 600; margin-top: 8px; }
  #fatal { display:none; background:#3a0d0d; color:#ffd9d9; border:1px solid #ff5a5a; padding:12px; border-radius:12px; margin-bottom:12px }
  .msg { background:#0f1a33; border:1px solid rgba(255,255,255,.06); border-radius:12px; padding:10px 12px; margin-top:8px; }
  .msg .hdr { font-weight:700; font-size:14px; color:#cfe3ff; margin-bottom:4px; }
  .msg .txt { font-size:15px; white-space:pre-wrap; }
"""

    js = r"""
(function(){
  let scenario = null;
  const elFatal = document.getElementById('fatal');
  function showFatal(msg){
    if (!elFatal) return;
    elFatal.style.display = 'block';
    elFatal.textContent = 'Ошибка: ' + msg;
  }
  try {
    scenario = JSON.parse(document.getElementById('scenario-data').textContent);
  } catch(e){
    showFatal('Не удалось разобрать JSON сценария: ' + (e && e.message ? e.message : e));
    return;
  }

  const stepsArr = scenario.steps || [];
  const steps = {};
  stepsArr.forEach(s => steps[s.id] = s);

  const vars = Object.assign({}, scenario.vars || {});
  const chosen = new Set();
  const history = [];
  const transcript = [];
  const loggedSteps = new Set();

  function safeEval(expr, vars){
    if (typeof expr !== 'string') return expr;
    const original = String(expr);
  
    // 1) Меняем строковые литералы на плейсхолдер — чтобы Unicode/слэши не мешали проверке
    const STR = '"__STR__"';
    const stripped = original.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g, STR);
  
    // 2) Очень консервативная проверка посимвольно — без регекспа
    const isAsciiLetter = c => (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
    const isDigit = c => (c >= '0' && c <= '9');
    const extra = new Set([' ', '\t', '\r', '\n', '_', '[', ']', '\'', '"', '.', ',', ':', '+', '*', '/', '(', ')', '<', '>', '!', '=', '?', '&', '|', '-', '\\']);
    for (const ch of stripped){
      if (isAsciiLetter(ch) || isDigit(ch) || extra.has(ch)) { continue; }
      throw new Error('Недопустимые символы: ' + original);
    }
  
    // 3) Подставляем vars["name"] для идентификаторов
    const compiled = original.replace(/\b([A-Za-z_]\w*)\b/g, (m, name)=>{
      if (Object.prototype.hasOwnProperty.call(vars, name)) return 'vars["'+name+'"]';
      if (['true','false','null','undefined'].includes(name)) return name;
      return name;
    });
  
    // 4) Выполняем выражение
    const fn = new Function('vars', 'return (' + compiled + ')');
    return fn(vars);
  }


  function renderInline(raw){
    if (!raw) return '';
    let s = String(raw);
    // {cond ? A | B}
    const ternary = /\\{([^{}?:|]+?)\\?\\s*([^{}|]+?)\\|\\s*([^{}]+?)\\}/g;
    s = s.replace(ternary, (_, cond, yes, no)=>{
      let ok = false;
      try { ok = !!safeEval(cond.trim(), vars); } catch(e){ ok = false; }
      return ok ? yes.trim() : no.trim();
    });
    // {var}
    s = s.replace(/\\{([A-Za-z_]\\w*)\\}/g, (_, name)=> (name in vars) ? String(vars[name]) : '{'+name+'}');
    // newlines
    s = s.replace(/\\n/g, '<br>');
    return s;
  }

  function runActions(actions){
    if (!actions) return;
    for (const act of actions){
      if (act.type === 'set'){
        try {
          if (!(act.var in vars)) vars[act.var] = 0;
          const v = safeEval(act.expr, vars);
          vars[act.var] = v;
          log('~ set '+act.var+' = '+v);
        } catch(e){
          log('! ошибка set: '+e.message);
        }
      } else if (act.type === 'call'){
        log('~ call '+act.fn+'('+ (act.args||'') +')');
      }
    }
  }

  function isEmptyStep(step){
    if (!step) return true;
    const hasText = !!(step.text_raw || step.text || step.speaker);
    const hasUI = (step.options && step.options.length) || step.audio || step.end || step.divert;
    const hasAct = step.actions && step.actions.length;
    return !(hasText || hasUI || hasAct);
  }
  function firstChildStitch(knotId){
    const prefix = knotId + '.';
    if (steps[prefix + 'start']) return prefix + 'start';
    if (Array.isArray(scenario.order)){
      const idx = scenario.order.indexOf(knotId);
      if (idx >= 0){
        for (let j = idx + 1; j < scenario.order.length; j++){
          const id = scenario.order[j];
          if (id && id.startsWith(prefix)) return id;
          if (id && !id.includes('.')) break;
        }
      }
    }
    const list = Object.keys(steps).filter(k => k.startsWith(prefix)).sort();
    return list.length ? list[0] : null;
  }
  function applyDivert(divert){
    if (!divert) return null;
    if (divert === 'END' || divert === 'DONE') return '__END__';
    return divert;
  }
  function pushNpc(speaker, text){
    if (!text || !String(text).trim()) return;
    const spk = (speaker && speaker !== 'system') ? speaker : 'Система';
    transcript.push({role:'npc', speaker: spk, text: String(text).trim()});
  }
  function pushUser(text){
    if (!text || !String(text).trim()) return;
    transcript.push({role:'user', speaker:'Вы', text: String(text).trim()});
  }

  const elTitle = document.getElementById('title');
  const elMeta  = document.getElementById('meta');
  const elSpk   = document.getElementById('speaker');
  const elText  = document.getElementById('text');
  const elAudio = document.getElementById('audio');
  const elOpts  = document.getElementById('opts');
  const elEnd   = document.getElementById('end');
  const elChipSt= document.getElementById('chipState');
  const elTranscript = document.getElementById('transcript');
  const elQAList = document.getElementById('qaList');
  const elSys   = document.getElementById('syslog');
  function log(msg){ if (elSys) elSys.textContent = msg; }

  function renderTranscript(){
    elTranscript.style.display = transcript.length ? 'block' : 'none';
    elQAList.innerHTML = '';
    transcript.forEach((m)=>{
      const box = document.createElement('div'); box.className = 'msg ' + (m.role === 'user' ? 'user' : 'npc');
      const hdr = document.createElement('div'); hdr.className = 'hdr'; hdr.textContent = m.speaker;
      const txt = document.createElement('div'); txt.className = 'txt'; txt.textContent = m.text;
      box.appendChild(hdr); box.appendChild(txt);
      elQAList.appendChild(box);
    });
  }

  function render(stepId){
    try {
      if (!stepId) stepId = 'start';
      const step = steps[stepId];
      if (!step){ elText.textContent = '❌ Нет шага: ' + stepId; return; }
      history.push(stepId);

      runActions(step.actions);

      elTitle.textContent = scenario.title || (scenario.scenario_id || 'Scenario');
      elMeta.textContent  = 'Шаг: ' + stepId;

      const speaker = step.speaker || 'system';
      elSpk.textContent = speaker;

      const raw = step.text_raw || step.text || '';
      const renderedText = renderInline(raw);
      elText.innerHTML  = renderedText;
      if (!loggedSteps.has(stepId)) { pushNpc(speaker, elText.textContent || ''); loggedSteps.add(stepId); }

      elAudio.innerHTML = '';
      if (step.audio){
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.src = step.audio;
        elAudio.appendChild(audio);
      }

      elOpts.innerHTML = '';
      let options = step.options || [];
      options = options.filter(opt => opt.repeatable || !chosen.has(opt.id));

      if (options.length){
        options.forEach((opt, idx)=>{
          const btn = document.createElement('button');
          btn.className = 'btn';
          btn.textContent = opt.text || ('Вариант ' + (idx+1));
          btn.onclick = ()=>{
            if (opt.id) chosen.add(opt.id);
            pushUser(opt.text || ('Вариант ' + (idx+1)));
            if (opt.next === 'END' || opt.next === 'DONE'){
              elEnd.textContent = 'Сценарий завершён';
              renderTranscript();
              elOpts.innerHTML = '';
              return;
            }
            render(opt.next || stepId);
          };
          elOpts.appendChild(btn);
        });
        elEnd.textContent = '';
      } else {
        // empty node? autostitch into first child
        if (isEmptyStep(step)){
          const child = firstChildStitch(stepId);
          if (child){ render(child); return; }
        }
        const target = applyDivert(step.divert);
        if (target === '__END__' || step.end){
          elEnd.textContent = 'Сценарий завершён';
          renderTranscript();
        } else if (target){
          const btn = document.createElement('button');
          btn.className = 'btn';
          btn.textContent = 'Далее';
          btn.onclick = ()=> render(target);
          elOpts.appendChild(btn);
          elEnd.textContent = '';
        } else {
          elEnd.textContent = 'Нет вариантов. Конец.';
          renderTranscript();
        }
      }

      elChipSt.textContent = 'История: ' + history.join(' → ');
    } catch(e){
      showFatal('Сбой при рендере: ' + (e && e.message ? e.message : e));
      return;
    }
  }

  const entry = (steps['start'] && isEmptyStep(steps['start'])) ? (firstChildStitch('start') || 'start') : 'start';
  render(entry);
})();"""

    transcript_html = r"""
  <div class="transcript" id="transcript" style="display:none">
    <h2>История диалога</h2>
    <div id="qaList"></div>
  </div>
"""

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scenario Player</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="title">Сценарий</h1>
    <div class="meta" id="meta"></div>
  </header>

  <div id="fatal"></div>
  <div class="card">
    <div class="speaker" id="speaker"></div>
    <div class="text" id="text"></div>
    <div class="audio" id="audio"></div>
    <div class="opts" id="opts"></div>
    <div class="end" id="end"></div>
    <div class="footer">
      <div class="chip" id="chipState"></div>
    </div>
    <div class="sys" id="syslog"></div>
  </div>

  {transcript_html}
</div>

<script id="scenario-data" type="application/json">{payload}</script>
<script>{js}</script>
</body>
</html>"""
    return html
