# json_to_html_player.py
# API:
#   build_html_player(data: dict) -> str
#
# CLI (без файлов):  cat story.json | python -m json_to_html_player > out.html

import json
import sys

TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Scenario Player</title>
<style>
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
  .text .morph { padding:2px 4px; border-radius:6px; }
  .audio { margin: 10px 0; }
  .opts { display: grid; gap: 10px; margin-top: 10px; }
  .btn { appearance: none; border:1px solid rgba(255,255,255,.08); background: #162241; color:#e9f1ff;
         border-radius: 12px; padding: 12px 14px; text-align:left; cursor:pointer; font-size:16px; }
  .btn:hover { border-color: rgba(90,168,255,.6); }
  .sys { color: var(--muted); font-size: 13px; margin-top: 10px; }
  .footer { display:flex; gap:8px; margin-top:12px; }
  .chip { font-size:12px; color:#cfe3ff; background:#18294d; border:1px solid rgba(255,255,255,.08);
          padding:6px 8px; border-radius:999px; }
  .end { color: var(--ok); font-weight: 600; margin-top: 8px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1 id="title">Сценарий</h1>
    <div class="meta" id="meta"></div>
  </header>

  <div class="card">
    <div class="speaker" id="speaker"></div>
    <div class="text" id="text"></div>
    <div class="audio" id="audio"></div>
    <div class="opts" id="opts"></div>
    <div class="end" id="end"></div>
    <div class="footer">
      <div class="chip" id="chipState"></div>
      <div class="chip" id="chipCoins" style="display:none"></div>
    </div>
    <div class="sys" id="syslog"></div>
  </div>
</div>

<script id="scenario-data" type="application/json">__DATA__</script>
<script>
(function(){
  const scenario = JSON.parse(document.getElementById('scenario-data').textContent);

  const stepsArr = scenario.steps || [];
  const steps = {};
  stepsArr.forEach(s => steps[s.id] = s);

  const vars = Object.assign({}, scenario.vars || {}); // состояние переменных
  const externals = Object.assign({}, (scenario.externals||[]).reduce((a,n)=>{a[n]=true;return a;}, {}));
  const chosen = new Set();
  const history = [];

  function safeEval(expr, vars){
    if (typeof expr !== 'string') return expr;

    // допустимые символы в выражениях (избегаем уязвимостей)
    const allowed = /^[0-9A-Za-z_ \[\]'".,:+*\/()<>!=?&|-]+$/;
    if (!allowed.test(expr)) throw new Error('Недопустимые символы: ' + expr);

    expr = expr.replace(/\b([A-Za-z_]\w*)\b/g, (m, name)=>{
      if (Object.prototype.hasOwnProperty.call(vars, name)) return 'vars["'+name+'"]';
      if (['true','false','null','undefined'].includes(name)) return name;
      return name;
    });

    // eslint-disable-next-line no-new-func
    const fn = new Function('vars', 'return (' + expr + ')');
    return fn(vars);
  }

  function renderInline(raw){
    if (!raw) return '';
    let s = String(raw);

    // {cond ? A | B}
    const ternary = /\{([^{}?:|]+?)\?\s*([^{}|]+?)\|\s*([^{}]+?)\}/g;
    s = s.replace(ternary, (_, cond, yes, no)=>{
      let ok = false;
      try { ok = !!safeEval(cond.trim(), vars); } catch(e){ ok = false; }
      return ok ? yes.trim() : no.trim();
    });

    // {var}
    s = s.replace(/\{([A-Za-z_]\w*)\}/g, (_, name)=>{
      return (name in vars) ? String(vars[name]) : '{'+name+'}';
    });

    // переносы строк
    s = s.replace(/\n/g, '<br>');
    return s;
  }

  function highlight(text){
    const morph = scenario.morphology || {};
    if (!morph || !text) return text;
    return text.split(/(\b)/).map(tok => {
      const key = tok.toLowerCase();
      if (morph[key]){
        const color = morph[key].color || '#3fa3ff';
        return '<span class="morph" style="background:'+color+'10;border:1px solid '+color+'33">'+tok+'</span>';
      }
      return tok;
    }).join('');
  }

  function log(msg){ document.getElementById('syslog').textContent = msg; }

  function runActions(actions){
    if (!actions) return;
    for (const act of actions){
      if (act.type === 'set'){
        try {
          if (!(act.var in vars)) vars[act.var] = 0; // опциональная автоинициализация
          const v = safeEval(act.expr, vars);
          vars[act.var] = v;
          log('~ set '+act.var+' = '+v);
        } catch(e){
          log('! ошибка set: '+e.message);
        }
      } else if (act.type === 'call'){
        // заглушка EXTERNAL-вызовов (можно расширить, напр. playSound)
        log('~ call '+act.fn+'('+ (act.args||'') +')');
      }
    }
  }

  function applyDivert(divert){
    if (!divert) return null;
    if (divert === 'END' || divert === 'DONE') return '__END__';
    return divert;
  }

  const elTitle = document.getElementById('title');
  const elMeta  = document.getElementById('meta');
  const elSpk   = document.getElementById('speaker');
  const elText  = document.getElementById('text');
  const elAudio = document.getElementById('audio');
  const elOpts  = document.getElementById('opts');
  const elEnd   = document.getElementById('end');
  const elChipSt= document.getElementById('chipState');
  const elChipC = document.getElementById('chipCoins');

  function render(stepId){
    if (!stepId) stepId = 'start';
    const step = steps[stepId];
    if (!step){ elText.textContent = '❌ Нет шага: '+stepId; return; }
    history.push(stepId);

    runActions(step.actions);

    elTitle.textContent = scenario.title || (scenario.scenario_id || 'Scenario');
    elMeta.textContent  = 'Шаг: '+stepId + (scenario.language ? (' • '+scenario.language) : '');

    const speaker = step.speaker || 'system';
    elSpk.textContent = speaker;

    const raw = step.text_raw || step.text || '';
    elText.innerHTML  = highlight(renderInline(raw));

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
        btn.textContent = opt.text || ('Вариант '+(idx+1));
        btn.onclick = ()=>{
          if (opt.id) chosen.add(opt.id);
          render(opt.next || stepId);
        };
        elOpts.appendChild(btn);
      });
      elEnd.textContent = '';
    } else {
      const target = applyDivert(step.divert);
      if (target === '__END__' || step.end){
        elEnd.textContent = 'Сценарий завершён';
      } else if (target){
        const btn = document.createElement('button');
        btn.className = 'btn';
        btn.textContent = 'Далее';
        btn.onclick = ()=> render(target);
        elOpts.appendChild(btn);
        elEnd.textContent = '';
      } else {
        elEnd.textContent = 'Нет вариантов. Конец.';
      }
    }

    elChipSt.textContent = 'История: ' + history.join(' → ');
    if ('coins' in vars){
      elChipC.style.display = 'inline-block';
      elChipC.textContent = 'coins=' + vars.coins;
    } else {
      elChipC.style.display = 'none';
    }
  }

  render('start');
})();
</script>
</body>
</html>
"""

def build_html_player(data: dict) -> str:
    """Главная функция: на вход — JSON-объект сценария (dict), на выход — HTML (str)."""
    json_blob = json.dumps(data, ensure_ascii=False, indent=2)
    return TEMPLATE.replace("__DATA__", json_blob)

# --- CLI: читает JSON из stdin, пишет HTML в stdout ---
def _main():
    data = json.loads(sys.stdin.read())
    sys.stdout.write(build_html_player(data))

if __name__ == "__main__":
    _main()
