import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
with open(HERE / 'demo_data.json') as f:
    DATA = json.load(f)
data_js = json.dumps(DATA)

HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Network Investigator — cited RAG + agentic reasoning over real BGP incidents</title>
<style>
:root{
  --bg:#0b0f16; --panel:#121826; --panel2:#0e131e; --line:#20293a;
  --text:#e6edf7; --muted:#8b97ad; --dim:#5c6b85;
  --accent:#5ea1ff; --green:#37d18e; --amber:#f5b942; --red:#ff6b6b; --violet:#b18cff;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.55;
  background-image:radial-gradient(900px 500px at 85% -10%,rgba(94,161,255,.10),transparent 60%),
                   radial-gradient(700px 500px at -10% 10%,rgba(177,140,255,.08),transparent 55%);}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1080px;margin:0 auto;padding:34px 22px 80px}
header .kicker{color:var(--accent);font-weight:600;letter-spacing:.14em;text-transform:uppercase;font-size:12px}
h1{font-size:30px;margin:8px 0 6px;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:16px;max-width:760px}
.links{margin-top:14px;display:flex;gap:10px;flex-wrap:wrap}
.btn{border:1px solid var(--line);background:var(--panel);padding:7px 13px;border-radius:8px;font-size:13px;color:var(--text)}
.btn:hover{border-color:var(--accent);text-decoration:none}
.pipe{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:26px 0 8px}
.stage{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:11px 12px;position:relative}
.stage .n{font-family:var(--mono);font-size:11px;color:var(--accent)}
.stage .t{font-weight:600;font-size:13px;margin-top:3px}
.stage .d{color:var(--muted);font-size:11.5px;margin-top:3px}
.note{color:var(--muted);font-size:12.5px;margin:4px 0 22px}
.note b{color:var(--violet)}
.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 18px}
.tab{border:1px solid var(--line);background:var(--panel2);color:var(--muted);padding:8px 13px;border-radius:999px;
  font-size:13px;cursor:pointer;transition:.15s}
.tab:hover{color:var(--text)}
.tab.active{border-color:var(--accent);color:var(--text);background:rgba(94,161,255,.10)}
.tab .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px;vertical-align:middle}
.dot.assert{background:var(--green)}.dot.abstain{background:var(--amber)}.dot.none{background:var(--muted)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-bottom:16px}
.meta{display:flex;flex-wrap:wrap;gap:18px;color:var(--muted);font-size:13px;margin-top:6px}
.meta code{font-family:var(--mono);color:var(--text);background:var(--panel2);padding:2px 6px;border-radius:5px}
.verdict{border-radius:12px;padding:15px 17px;margin:16px 0 4px;border:1px solid}
.verdict.assert{background:rgba(55,209,142,.08);border-color:rgba(55,209,142,.4)}
.verdict.abstain{background:rgba(245,185,66,.08);border-color:rgba(245,185,66,.4)}
.verdict .vh{font-weight:700;font-size:14px;letter-spacing:.02em}
.verdict.assert .vh{color:var(--green)}.verdict.abstain .vh{color:var(--amber)}
.verdict .vb{font-size:13.5px;color:var(--text);margin-top:4px}
.verdict .counts{font-family:var(--mono);font-size:12px;color:var(--muted);margin-top:8px}
.sec-h{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:22px 0 10px}
.obs{border-left:3px solid var(--line);padding:2px 0 2px 14px;margin-bottom:14px}
.obs.critical{border-color:var(--red)}.obs.warning{border-color:var(--amber)}.obs.info{border-color:var(--accent)}
.obs .oh{font-weight:600;font-size:14px}
.obs .sev{font-family:var(--mono);font-size:10.5px;padding:1px 6px;border-radius:4px;margin-right:8px;vertical-align:middle}
.sev.critical{background:rgba(255,107,107,.16);color:var(--red)}
.sev.warning{background:rgba(245,185,66,.16);color:var(--amber)}
.sev.info{background:rgba(94,161,255,.16);color:var(--accent)}
.obs ul{margin:7px 0 0;padding-left:18px}
.obs li{font-size:13.5px;color:#cdd6e6;margin-bottom:3px}
.hint{color:var(--violet);font-size:12px}
.ev{font-family:var(--mono);font-size:11px;color:var(--muted);background:var(--panel2);border:1px solid var(--line);
  border-radius:6px;padding:6px 8px;margin-top:6px;overflow-x:auto;white-space:pre}
.hyp{border:1px solid var(--line);border-radius:11px;padding:14px 16px;margin-bottom:12px;background:var(--panel2)}
.hyp .hk{font-weight:600;font-size:14px}
.badge{font-family:var(--mono);font-size:10.5px;padding:1px 7px;border-radius:5px;margin-left:6px}
.badge.k{background:rgba(177,140,255,.16);color:var(--violet)}
.hyp .st{color:var(--muted);font-size:13px;margin:4px 0 10px}
.pgroup{margin-top:8px}
.plabel{font-size:11.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;margin-bottom:4px}
.plabel.sup{color:var(--green)}.plabel.con{color:var(--red)}.plabel.rel{color:var(--muted)}
.passage{border-left:3px solid var(--line);padding:6px 0 6px 11px;margin-bottom:7px}
.passage.sup{border-color:var(--green)}.passage.con{border-color:var(--red)}.passage.rel{border-color:var(--muted)}
.passage .src{font-family:var(--mono);font-size:11px;color:var(--accent)}
.passage .txt{font-size:12.5px;color:#cdd6e6;margin-top:2px}
.empty{color:var(--muted);font-size:12.5px;font-style:italic}
.checker{font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:8px}
footer{color:var(--muted);font-size:12.5px;margin-top:36px;border-top:1px solid var(--line);padding-top:16px}
.toggle{cursor:pointer;color:var(--accent);font-size:12px;user-select:none}
.gt{font-size:12px;color:var(--muted)}
.gt b{color:var(--green)}
@media(max-width:820px){.pipe{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="kicker">Retrieval-grounded · agentic · abstains when it can't prove it</div>
  <h1>Network Investigator</h1>
  <div class="sub">A citation-grounded RAG + agentic system that explains real BGP routing
  incidents using cited passages from IETF RFCs — and <b>refuses to answer</b> when it can't
  ground a claim in a source. Every result below is produced by the actual pipeline over real
  RIPE RIS / RouteViews data, not mocked.</div>
  <div class="links">
    <a class="btn" id="repo" href="#">★ View source on GitHub</a>
    <a class="btn" href="#how">How it works</a>
  </div>
</header>

<div class="pipe">
  <div class="stage"><div class="n">01</div><div class="t">Deterministic detection</div><div class="d">Analyzers compute anomalies from raw updates. No LLM in the detection path.</div></div>
  <div class="stage"><div class="n">02</div><div class="t">Agentic RFC retrieval</div><div class="d">Multi-round search loop grounds each finding in cited RFC passages.</div></div>
  <div class="stage"><div class="n">03</div><div class="t">Adversarial counter-evidence</div><div class="d">Actively searches for passages that <i>contradict</i> each hypothesis.</div></div>
  <div class="stage"><div class="n">04</div><div class="t">ACH ranking</div><div class="d">Analysis of Competing Hypotheses ranks by evidence, not model opinion.</div></div>
  <div class="stage"><div class="n">05</div><div class="t">Assert or abstain</div><div class="d">A computed decision from evidence counts — never a model judging itself.</div></div>
</div>
<div class="note">The differentiator is <b>measured abstention</b>: an entailment checker gates every
claim, so the system reports “insufficient grounded evidence” instead of hallucinating a
plausible-sounding answer. Two incidents below deliberately show it declining to assert.</div>

<div class="tabs" id="tabs"></div>
<div id="view"></div>

<footer id="how">
  Deterministic analyzers (MOAS, AS-path loop, route leak, RPKI/ROA) → agentic RFC retrieval
  (dense + BM25 hybrid available) → adversarial contradiction search gated by an entailment
  checker → Analysis of Competing Hypotheses with a two-tier evidence bar. Ground-truth labels
  are held out of the analyzers and shown here only to let you check the verdict.
</footer>
</div>

<script>
const DATA = __DATA__;
const REPO_URL = "__REPO__";
document.getElementById('repo').href = REPO_URL;

const esc = s => (s==null?'':String(s)).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

function verdictKind(inc){
  const v=inc.verdict; if(!v) return 'none';
  if(v.abstained) return 'abstain';
  if(v.leading) return 'assert';
  return 'none';
}

function renderPassages(list,cls,label){
  if(!list.length) return `<div class="pgroup"><div class="plabel ${cls}">${label}</div><div class="empty">none found</div></div>`;
  const items=list.map(s=>`<div class="passage ${cls}"><div class="src">[${esc(s.source_id)}]</div><div class="txt">${esc(s.text.slice(0,300))}${s.text.length>300?'…':''}</div></div>`).join('');
  return `<div class="pgroup"><div class="plabel ${cls}">${label} (${list.length})</div>${items}</div>`;
}

function renderIncident(inc){
  const vk=verdictKind(inc);
  const v=inc.verdict||{};
  let verdictHtml='';
  if(vk==='assert'){
    const L=v.leading;
    verdictHtml=`<div class="verdict assert"><div class="vh">✓ ASSERTS — leading hypothesis: [${esc(L.kind)}]</div>
      <div class="vb">${esc(L.statement)}</div>
      <div class="counts">relevance-tier evidence ${L.relevant_count} vs ${L.contradicting_count} contradicting · strict-entailment count ${L.supporting_count}</div></div>`;
  } else if(vk==='abstain'){
    verdictHtml=`<div class="verdict abstain"><div class="vh">⊘ ABSTAINS — insufficient grounded evidence</div>
      <div class="vb">${esc(v.abstain_reason)}</div></div>`;
  } else {
    verdictHtml=`<div class="verdict abstain"><div class="vh">— no anomaly asserted</div></div>`;
  }

  const obs=inc.observations.map(o=>{
    const findings=o.findings.map(f=>`<li>${esc(f.text)}${f.rfc_hint?` <span class="hint">↳ ground in: ${esc(f.rfc_hint)}</span>`:''}</li>`).join('');
    const ev=o.evidence.length?`<div class="ev">${o.evidence.map(esc).join('\n')}${o.evidence_extra?`\n…and ${o.evidence_extra} more`:''}</div>`:'';
    return `<div class="obs ${o.severity}"><div class="oh"><span class="sev ${o.severity}">${o.severity.toUpperCase()}</span>${esc(o.kind)} — <code>${esc(o.name)}</code></div><ul>${findings}</ul>${ev}</div>`;
  }).join('') || '<div class="empty">No anomalies detected by the deterministic analyzers.</div>';

  const hyps=inc.hypotheses.map(h=>`
    <div class="hyp">
      <div class="hk">${esc(h.kind)}<span class="badge k">hypothesis</span></div>
      <div class="st">${esc(h.statement)}</div>
      ${renderPassages(h.supporting,'sup','Supporting (entailed)')}
      ${renderPassages(h.contradicting,'con','Contradicting')}
      ${renderPassages(h.topically_relevant,'rel','Topically relevant')}
      <div class="checker">entailment checker: ${esc(h.checker_name||'lexical_overlap')}</div>
    </div>`).join('') || '<div class="empty">No hypotheses to weigh.</div>';

  const gt=inc.ground_truth?`<div class="gt">Held-out ground truth: <b>${esc(inc.ground_truth)}</b> — used only to check the verdict, never seen by the analyzers.</div>`:'';

  return `<div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
      <div style="font-size:19px;font-weight:700">${esc(inc.incident_id)}</div>
      <button class="btn" style="font-size:12px;padding:5px 11px" onclick="runLive('${esc(inc.incident_id)}',this)">↻ Run live</button>
    </div>
    <div style="color:var(--muted);font-size:13.5px;margin-top:3px">${esc(inc.description)}</div>
    <div class="meta"><span>prefix <code>${esc(inc.prefix)}</code></span><span>source <code>${esc(inc.source)}</code></span><span><code>${inc.update_count}</code> BGP updates</span></div>
    ${verdictHtml}
    ${gt}
    <div class="sec-h">Observations — computed from evidence (no LLM)</div>
    ${obs}
    <div class="sec-h">Competing hypotheses — with adversarial counter-evidence</div>
    ${hyps}
  </div>`;
}

async function runLive(id,btn){
  const orig=btn.textContent; btn.textContent='running…'; btn.disabled=true;
  try{
    const r=await fetch('/api/investigate?incident='+encodeURIComponent(id));
    if(!r.ok) throw new Error('HTTP '+r.status);
    const fresh=await r.json();
    const i=DATA.findIndex(x=>x.incident_id===id);
    if(i>=0) DATA[i]=fresh;
    view.innerHTML=renderIncident(fresh);
    const b=document.createElement('div');
    b.style.cssText='color:var(--green);font-size:12px;margin-bottom:10px';
    b.textContent='● Live result — just computed by the real pipeline on the server';
    view.prepend(b);
  }catch(e){
    btn.textContent='snapshot (no live server)'; btn.disabled=false;
    setTimeout(()=>{btn.textContent=orig;},2200);
    return;
  }
}
const tabs=document.getElementById('tabs');
const view=document.getElementById('view');
DATA.forEach((inc,i)=>{
  const vk=verdictKind(inc);
  const b=document.createElement('button');
  b.className='tab'+(i===0?' active':'');
  b.innerHTML=`<span class="dot ${vk}"></span>${esc(inc.incident_id)}`;
  b.onclick=()=>{document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));b.classList.add('active');view.innerHTML=renderIncident(inc);window.scrollTo({top:tabs.offsetTop-20,behavior:'smooth'});};
  tabs.appendChild(b);
});
view.innerHTML=renderIncident(DATA[0]);
</script>
</body>
</html>'''

REPO_URL = "https://github.com/dim-tsoukalas/RouteCause"
out = HTML.replace('__DATA__', data_js).replace('__REPO__', REPO_URL)
(HERE / 'index.html').write_text(out)
print("wrote index.html", len(out), "bytes")
