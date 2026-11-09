const meta={dashboard:['WORKSPACE','Dashboard'],analysis:['SYNTHETIC CODING REVIEW','Review Workspace'],cases:['CASE MANAGEMENT','Cases'],knowledge:['KNOWLEDGE LAYER','Code Knowledge'],agents:['LANGGRAPH PIPELINE','Review Workflow'],activity:['AUDIT TRAIL','Activity'],settings:['WORKSPACE','Settings'],result:['ANALYSIS RESULT','Recommendation Review']};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let currentCase=null, caseStatus='All';
const codePageSize=40;
let codeSearchOffset=0, codeSearchTerm='';
let authenticatedUser=null;
let workspaceSettings=null;
let demoMode=false;

function escapeHtml(value){
  return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function showAuthentication(message=''){
  $('#appShell').hidden=true;
  $('#authScreen').hidden=false;
  $('#authMessage').textContent=message;
}
function switchAuthMode(mode){
  const signup=mode==='signup';
  $('#loginPanel').hidden=signup;
  $('#signupPanel').hidden=!signup;
  $('#loginTab').classList.toggle('active',!signup);
  $('#signupTab').classList.toggle('active',signup);
  $('#loginTab').setAttribute('aria-selected',String(!signup));
  $('#signupTab').setAttribute('aria-selected',String(signup));
  $('#authMessage').textContent='';
}
function initials(name){
  return name.trim().split(/\s+/).slice(0,2).map(part=>part[0]).join('').toUpperCase()||'MB';
}
async function enterWorkspace(user){
  demoMode=false;
  $('#appShell').classList.remove('public-demo');
  $('#sidebar').hidden=false;
  $('#sidebar nav').hidden=false;
  $('.notification-wrap').hidden=false;
  $('#help').hidden=false;
  $('.user').hidden=false;
  authenticatedUser=user;
  $('#authScreen').hidden=true;
  $('#appShell').hidden=false;
  $('#accountName').textContent=user.full_name;
  $('#accountRole').textContent='Medical Coding Analyst';
  $('#accountAvatar').textContent=initials(user.full_name);
  $('#headerAvatar').textContent=initials(user.full_name);
  $$('th').forEach(cell=>{if(cell.textContent==='Confidence')cell.textContent='Match score'});
  await Promise.all([loadWorkspace(),loadDashboard(),loadNotifications(),loadAnalysisGate()]);
}
function enterPublicDemo(){
  demoMode=true;
  $('#appShell').classList.add('public-demo');
  $('#analysis .heading p').textContent='Research prototype: clinical accuracy has not been established through coder-adjudicated evaluation. Not for clinical use.';
  authenticatedUser={full_name:'Guest demonstrator'};
  workspaceSettings={show_evidence:true,review_notifications:false};
  $('#authScreen').hidden=true;
  $('#appShell').hidden=false;
  $('#sidebar').hidden=true;
  $('.notification-wrap').hidden=true;
  $('#help').hidden=true;
  $('.user').hidden=true;
  $('#analysisAvailability').textContent='Public synthetic-only demo. Inputs are analyzed temporarily, never saved, and must not contain real patient information.';
  $('#analyze').disabled=false;
  showPage('analysis');
}
const graphNodeDefaults=[
  {id:'parse',name:'Context extraction',detail:'Extract clinical mentions and context.'},
  {id:'retrieve',name:'Catalog retrieval',detail:'Search configured coding references.'},
  {id:'reason',name:'Optional model reasoning',status:'skipped',detail:'No local model ranking has been performed yet.'},
  {id:'validate',name:'Review validation',detail:'Apply review rules and preserve human oversight.'}
];
function workflowGraphMarkup(workflow={}){
  const nodes=Array.isArray(workflow.nodes)&&workflow.nodes.length?workflow.nodes:graphNodeDefaults;
  return nodes.map((node,index)=>{
    const status=node.status||'ready';
    const label=status==='complete'?'Complete':status==='skipped'?'Not configured':status==='warning'?'Attention':'Ready';
    return `<div class="graph-node ${escapeHtml(status)}"><span class="graph-node-number">${String(index+1).padStart(2,'0')}</span><div class="graph-node-copy"><div><b>${escapeHtml(node.name)}</b><span class="graph-node-status">${escapeHtml(label)}</span></div><small>${escapeHtml(node.detail||graphNodeDefaults[index]?.detail||'Workflow node')}</small></div></div>${index<nodes.length-1?'<div class="graph-edge" aria-hidden="true"></div>':''}`;
  }).join('')+`<div class="graph-handoff"><span class="graph-handoff-icon">↗</span><div><b>Required human review</b><small>Outside the automated graph. Verify every recommendation; none is approved automatically.</small></div></div>`;
}
function renderWorkflowGraph(workflow={}){
  const graph=$('#analysis .workflow');
  if(graph)graph.innerHTML=workflowGraphMarkup(workflow);
}
async function submitAuth(event,endpoint){
  event.preventDefault();
  const form=event.currentTarget;
  const button=form.querySelector('button[type="submit"]');
  button.disabled=true;
  $('#authMessage').textContent='Please wait…';
  const data=endpoint.endsWith('signup')
    ?{full_name:$('#signupName').value.trim(),email:$('#signupEmail').value.trim(),password:$('#signupPassword').value}
    :{email:$('#loginEmail').value.trim(),password:$('#loginPassword').value};
  try{
    const result=await api(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    form.reset();
    await enterWorkspace(result.user);
  }catch(error){
    $('#authMessage').textContent=error.message;
  }finally{
    button.disabled=false;
  }
}

async function loadAnalysisGate(){
  if(demoMode){
    $('#analysisAvailability').textContent='Public synthetic-only demo. Enter fictional text or upload a synthetic document. Inputs and review decisions are not saved.';
    $('#analyze').disabled=false;
    return;
  }
  try{
    const health=await api('/api/health');
    $('#analyze').disabled=!health.clinical_data_enabled;
    $('#analysisAvailability').textContent=health.clinical_data_enabled
      ?'Clinical-document analysis is enabled by recorded deployment approval. Use synthetic data for this class demo.'
      :'Clinical-document analysis is locked. Use synthetic-only text or documents; submissions are not saved.';
  }catch(error){
    $('#analysisAvailability').textContent=`Analysis gate status unavailable: ${error.message}`;
    $('#analyze').disabled=true;
  }
}
async function loadWorkspace(){
  try {
    const settings = await api('/api/workspace');
    workspaceSettings=settings;
    $('#profileName').value = settings.full_name || authenticatedUser.full_name;
    $('#profileRole').value = settings.role || 'Medical Coding Analyst';
    $('#profileTeam').value = settings.team || 'Coding Review Unit';
    $('#thresholdSelect').value = String(settings.review_threshold || 85);
    $('#thresholdSelect').closest('.toggle-row').querySelector('small').textContent='Mark cases for coder review when the score falls below this threshold.';
    const toggles = {
      evidence: $('#toggleEvidence'),
      flag: $('#toggleFlag'),
      notifications: $('#toggleNotifications')
    };
    for(const [key,toggle] of Object.entries(toggles)){
      const property={evidence:'show_evidence',flag:'flag_low_confidence',notifications:'review_notifications'}[key];
      toggle.classList.toggle('on',settings[property]!==false);
      toggle.setAttribute('aria-pressed',String(settings[property]!==false));
    }
    const name = $('#profileName').value || 'Medical Coding Analyst';
    const role = $('#profileRole').value || 'Coding Review';
    $('#accountName').textContent = name;
    $('#accountRole').textContent = role;
  } catch (err) {
    toast('Workspace load failed', err.message);
  }
}

async function saveWorkspaceFromUI(){
  const payload = {
    full_name: $('#profileName').value.trim() || authenticatedUser.full_name,
    role: $('#profileRole').value.trim() || 'Medical Coding Analyst',
    team: $('#profileTeam').value.trim() || 'Coding Review Unit',
    review_threshold: Number($('#thresholdSelect').value || 85),
    show_evidence: $('#toggleEvidence').classList.contains('on'),
    flag_low_confidence: $('#toggleFlag').classList.contains('on'),
    review_notifications: $('#toggleNotifications').classList.contains('on')
  };
  try {
    const saved=await api('/api/workspace', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    workspaceSettings=saved;
    authenticatedUser.full_name=payload.full_name;
    $('#accountName').textContent = payload.full_name;
    $('#accountRole').textContent = payload.role;
    $('#accountAvatar').textContent=initials(payload.full_name);
    $('#headerAvatar').textContent=initials(payload.full_name);
    toast('Workspace saved', 'Review settings updated.');
  } catch (err) {
    toast('Save failed', err.message);
  }
}
function toast(t,m){if(workspaceSettings?.review_notifications===false&&!/failed|error|unavailable/i.test(t))return;const el=$('#toast');el.textContent=t+(m?' — '+m:'');el.classList.add('show');setTimeout(()=>el.classList.remove('show'),2600)}
function modal(t,m){$('#modalTitle').textContent=t;$('#modalText').textContent=m;$('#modal').classList.add('show')}
function showPage(name){if(demoMode&&!['analysis','result'].includes(name))name='analysis';$$('.page').forEach(x=>x.classList.remove('active'));$('#'+name).classList.add('active');$$('.nav').forEach(x=>x.classList.toggle('active',x.dataset.page===name));if(meta[name]){$('#kicker').textContent=meta[name][0];$('#title').textContent=meta[name][1]}$('#sidebar').classList.remove('open'); if(name==='dashboard')loadDashboard();if(name==='cases')loadCases();if(name==='knowledge'){loadCodes();loadCatalogStatus()}if(name==='agents')loadAgents();if(name==='activity')loadActivity();}
document.addEventListener('click',e=>{const b=e.target.closest('[data-page]');if(b){showPage(b.dataset.page)}});$('#hamb').onclick=()=>{const open=$('#sidebar').classList.toggle('open');$('#hamb').setAttribute('aria-expanded',String(open))};
async function api(url,opt){const r=await fetch(url,opt);const data=await r.json().catch(()=>({detail:'Server returned an invalid response'}));if(!r.ok){if(r.status===401&&$('#appShell')&&!$('#appShell').hidden)showAuthentication(data.detail||'Please sign in again.');throw new Error(data.detail||'Request failed')}return data}
function metric(icon,cl,label,value,small){return `<div class="metric"><div class="metric-icon ${cl}">${icon}</div><div><span>${label}</span><strong>${value}</strong><small>${small}</small></div></div>`}
async function loadDashboard(){try{const d=await api('/api/dashboard');$('#metrics').innerHTML=metric('✦','mi-blue','Documents analyzed',d.metrics.documents_analyzed,'In your workspace')+metric('◎','mi-purple','Code matches',d.metrics.recommendations,'From installed catalogs')+metric('!','mi-amber','Needs coder review',d.metrics.needs_validation,'Cases marked for review')+metric('✓','mi-green','Avg. text-match score',d.metrics.avg_confidence+'%','Keyword overlap only');$('#recent').innerHTML=d.cases.map(c=>`<tr class="case-open" data-id="${escapeHtml(c.id)}"><td><b>${escapeHtml(c.id)}</b><span class="sub">${escapeHtml(new Date(c.created_at).toLocaleString())}</span></td><td>${escapeHtml(c.document_name||'Clinical text')}</td><td>${c.recommendations.length}</td><td><span class="confidence ${c.overall_confidence>=90?'high':'medium'}">${escapeHtml(c.overall_confidence)}%</span></td><td><span class="status ${c.status==='Validated'?'approved':'review'}">${escapeHtml(c.status)}</span></td></tr>`).join('');loadAgentsMini()}catch(e){toast('Dashboard error',e.message)}}
async function loadNotifications(){
  try{
    const data=await api('/api/notifications');
    const summary=data.summary;
    const actionable=summary.due_today+summary.overdue;
    $('#notificationBadge').textContent=actionable>99?'99+':String(actionable);
    $('#notificationBadge').hidden=actionable===0;
    $('#notificationSubtitle').textContent=`${summary.assigned_today} case(s) assigned today`;
    $('#notificationSummary').innerHTML=
      `<div><b>${summary.assigned_today}</b><small>Assigned today</small></div>`+
      `<div><b>${summary.open_cases}</b><small>Open cases</small></div>`+
      `<div><b>${summary.due_today}</b><small>Due today</small></div>`+
      `<div><b>${summary.overdue}</b><small>Overdue</small></div>`;
    $('#notificationList').innerHTML=data.notifications.length
      ?data.notifications.map(item=>`<button class="notification-item ${escapeHtml(item.category)}" data-case-id="${escapeHtml(item.case_id)}"><span><b>${escapeHtml(item.case_id)}</b><small>${escapeHtml(item.document_name)} · ${escapeHtml(item.status)}</small></span><span class="notification-deadline"><b>${item.category==='overdue'?'Overdue':item.category==='due_today'?'Due today':'Due'}</b><small>${escapeHtml(new Date(item.deadline_at).toLocaleString())}</small></span></button>`).join('')
      :'<p class="notification-empty">No open cases assigned to you.</p>';
  }catch(error){toast('Notifications unavailable',error.message)}
}
async function loadAgentsMini(){try{const stages=await api('/api/agents');$('#agentMini').innerHTML=stages.map((stage,index)=>`<div class="agent-mini"><span class="n">${String(index+1).padStart(2,'0')}</span><span class="a ${index===0?'blue':index===stages.length-1?'green':'purple'}">${escapeHtml(stage.id)}</span><div><b>${escapeHtml(stage.name)}</b><small>${escapeHtml(stage.role)}</small></div></div>`).join('')}catch(error){toast('Workflow error',error.message)}}
async function loadCases(q=''){try{const a=await api('/api/cases'+(q?'?q='+encodeURIComponent(q):''));const visible=caseStatus==='All'?a:a.filter(c=>c.status===caseStatus);$('#caseRows').innerHTML=visible.map(c=>`<tr><td><b>${escapeHtml(c.id)}</b></td><td>${escapeHtml(c.document_name||'Clinical text')}</td><td>${escapeHtml(new Date(c.created_at).toLocaleString())}</td><td>${c.recommendations.length}</td><td><span class="confidence ${c.overall_confidence>=90?'high':'medium'}">${escapeHtml(c.overall_confidence)}%</span></td><td><span class="status ${c.status==='Validated'?'approved':'review'}">${escapeHtml(c.status)}</span></td><td><button class="link case-open" data-id="${escapeHtml(c.id)}">Review →</button></td></tr>`).join('')||'<tr><td colspan="7" style="text-align:center;padding:30px;color:#9aa3b2">No matching cases.</td></tr>'}catch(e){toast('Cases error',e.message)}}
$('#caseSearch').addEventListener('input',e=>loadCases(e.target.value));
$$('.filter').forEach(button=>button.addEventListener('click',()=>{$$('.filter').forEach(item=>item.classList.remove('active'));button.classList.add('active');caseStatus=button.dataset.status;loadCases($('#caseSearch').value)}));
function showCodeEmpty(title,detail){
  const state=document.createElement('div');
  state.className='catalog-empty';
  const heading=document.createElement('b');
  heading.textContent=title;
  const description=document.createElement('p');
  description.textContent=detail;
  state.append(heading,description);
  $('#codes').replaceChildren(state);
}
function appendCodeCards(records){
  for(const record of records){
    const card=document.createElement('article');
    card.className='code-card';
    const type=document.createElement('span');
    type.className='type';
    type.textContent=record.type;
    const code=document.createElement('h3');
    code.textContent=record.code;
    const description=document.createElement('p');
    description.textContent=record.description;
    card.append(type,code,description);
    $('#codes').append(card);
  }
}
async function loadCodes(q=$('#codeSearch').value,append=false){
  if(!append)codeSearchTerm=q.trim();
  if(codeSearchTerm.length<2){
    codeSearchOffset=0;
    showCodeEmpty('Search the reference catalog','Enter at least two characters to find a code or description.');
    $('#codeCount').textContent='';
    $('#codeMore').hidden=true;
    return;
  }
  async function loadCatalogStatus(){
    try{
      const result=await api('/api/catalogs');
      $('#catalogStatus').textContent=result.catalogs.length
        ?`Installed references: ${result.catalogs.map(catalog=>`${catalog.type} (${catalog.records.toLocaleString()} codes)`).join(', ')}. Search results are limited to these catalogs.`
        :'No coding reference catalogs are installed. Add licensed reference data before using code lookup.';
    }catch(error){
      $('#catalogStatus').textContent=`Catalog status unavailable: ${error.message}`;
    }
  }
  try{
    const page=await api(`/api/codes?q=${encodeURIComponent(codeSearchTerm)}&limit=${codePageSize+1}&offset=${codeSearchOffset}`);
    const visible=page.slice(0,codePageSize);
    if(!append)$('#codes').replaceChildren();
    appendCodeCards(visible);
    if(!append&&!visible.length)showCodeEmpty('No matching codes','Try a different code, description, or clinical term.');
    codeSearchOffset+=visible.length;
    $('#codeCount').textContent=codeSearchOffset?`${codeSearchOffset} matching code${codeSearchOffset===1?'':'s'}`:'';
    $('#codeMore').hidden=page.length<=codePageSize;
  }catch(error){
    if(!append)showCodeEmpty('Catalog unavailable',error.message);
    $('#codeMore').hidden=true;
    toast('Knowledge error',error.message);
  }
}
$('#codeBtn').onclick=()=>loadCodes($('#codeSearch').value);
$('#codeMore').onclick=()=>loadCodes(codeSearchTerm,true);
$('#codeSearch').addEventListener('input',event=>{
  $('#codeBtn').disabled=event.target.value.trim().length<2;
  if($('#codeBtn').disabled)loadCodes('');
});
$('#codeSearch').addEventListener('keydown',event=>{if(event.key==='Enter')loadCodes(event.target.value)});
async function loadAgents(){try{const stages=await api('/api/agents');$('#agentsGrid').innerHTML=stages.map((stage,index)=>`<div class="agent-card"><div class="agent-top"><div class="big ${index===0?'mi-blue':index===stages.length-1?'mi-green':'mi-purple'}">${String(index+1).padStart(2,'0')}</div></div><span class="id">${escapeHtml(stage.role)}</span><h2>${escapeHtml(stage.name)}</h2><p>${escapeHtml(stage.description)}</p><div class="chips">${stage.tools.map(tool=>`<span>${escapeHtml(tool)}</span>`).join('')}</div></div>`).join('')}catch(error){toast('Workflow error',error.message)}}
async function loadActivity(){try{const a=await api('/api/activity');$('#activityList').innerHTML=a.map(x=>`<div class="activity-row"><span class="act ${x.kind==='decision'?'mi-green':x.kind==='analysis'?'mi-blue':'mi-purple'}">${x.kind==='decision'?'✓':x.kind==='analysis'?'✦':'R'}</span><div><b>${escapeHtml(x.title)}</b><small>${escapeHtml(x.detail)}</small></div><time>${escapeHtml(new Date(x.created_at).toLocaleString())}</time></div>`).join('')}catch(e){toast('Activity error',e.message)}}
const file=$('#file');$('#choose').onclick=()=>file.click();file.onchange=()=>{if(file.files[0])$('#filename').textContent='✓ '+file.files[0].name};$('#drop').ondragover=e=>{e.preventDefault()};$('#drop').ondrop=e=>{e.preventDefault();if(e.dataTransfer.files[0]){file.files=e.dataTransfer.files;$('#filename').textContent='✓ '+file.files[0].name}};
$('#analyze').onclick=async()=>{try{const text=$('#text').value.trim();let res;if(demoMode){if(!$('#syntheticAck').checked){toast('Synthetic confirmation required','Confirm the input contains no real patient information.');return}if(text){res=await api('/api/demo/analyze/text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,synthetic_only:true})})}else if(file.files[0]){const fd=new FormData();fd.append('file',file.files[0]);fd.append('synthetic_only','true');res=await api('/api/demo/analyze/file',{method:'POST',body:fd})}else{toast('Add a synthetic example','Upload a synthetic document or paste synthetic text first.');return}}else if(text){res=await api('/api/analyze/text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})})}else if(file.files[0]){const fd=new FormData();fd.append('file',file.files[0]);res=await api('/api/analyze/file',{method:'POST',body:fd})}else{toast('Add documentation','Upload a file or paste clinical text first.');return}renderResult(res.case);showPage('result');if(!demoMode)loadNotifications();toast('Analysis complete',res.case.id)}catch(e){toast('Analysis failed',e.message)}};
function renderResult(c){
  currentCase=c;
  $('#resultSub').textContent=`Case ${c.id} ? ${c.status}`;
  $('#resultStatus').textContent=`Case status: ${c.status}`;
  const locations=(c.source_locations||[]).map(location=>location.page?`PDF page ${location.page}`:location.paragraph?`DOCX paragraph ${location.paragraph}`:'Document text');
  const sourceSummary=locations.length?` Source: ${[...new Set(locations)].join(', ')}.`:'';
  const workflow=c.workflow||{};
  $('#resultSummary').textContent=`${c.recommendations.length} candidate(s) · ${c.gaps.length} review flag(s). Text-match scores are not clinical accuracy.${sourceSummary}`;
  $('#overall').textContent=`${c.overall_confidence}% text-match score`;
  $('#workflowInfo').hidden=false;
  $('#workflowInfo').innerHTML=`<div class="workflow-info-heading"><b>${escapeHtml(workflow.engine||'Analysis workflow')} execution</b><small>${escapeHtml(workflow.name||'Review pipeline')} · Retrieval: ${escapeHtml(workflow.retrieval_method||'lexical')} · Optional model: ${escapeHtml(workflow.model_status||'not reported')}${workflow.model_rationale?` · ${escapeHtml(workflow.model_rationale)}`:''}</small></div><div class="workflow result-workflow">${workflowGraphMarkup(workflow)}</div>`;
  renderWorkflowGraph(workflow);
  const flags=Array.isArray(c.gaps)?c.gaps:[];
  $('#reviewFlags').hidden=flags.length===0;
  $('#reviewFlags').innerHTML=flags.length?`<b>Coder review flags</b><ul>${flags.map(flag=>`<li>${escapeHtml(flag)}</li>`).join('')}</ul>`:'';
  const extracted=c.extracted||{};
  $('#extracted').innerHTML=Object.entries(extracted).filter(([key])=>key!=='context').map(([key,values])=>`<div class="entity"><label>${escapeHtml(key)}</label><div class="pills">${(Array.isArray(values)&&values.length?values:['None detected']).map(value=>`<span>${escapeHtml(value)}</span>`).join('')}</div></div>`).join('');
  const mentions=(c.clinical_context?.mentions||extracted.context||[]).filter(item=>item&&typeof item==='object');
  $('#clinicalMentions').innerHTML=mentions.length?`<div class="clinical-mentions"><b>Clinical mentions and evidence spans</b>${mentions.map(item=>`<div class="clinical-mention"><span class="type">${escapeHtml(item.category)} - ${escapeHtml(item.assertion)}</span><b>${escapeHtml(item.text)}</b><small>${escapeHtml(item.evidence)} - ${escapeHtml(item.experiencer)} ? chars ${item.start}-${item.end}</small></div>`).join('')}</div>`:'';
  $('#recommendations').innerHTML=c.recommendations.length?c.recommendations.map(recommendation=>{
    const score=Math.max(0,Math.min(1,Number(recommendation.confidence??recommendation.retrieval_score??0)));
    const flagged=recommendation.review_required||score<.85;
    const source=recommendation.source||{};
    const validation=recommendation.validation;
    const instructionList=Array.isArray(recommendation.instructions)?recommendation.instructions:[];
    const citation=`${source.catalog_type||recommendation.type||'Catalog'} ${source.catalog_version||recommendation.catalog_version||''} ? ${source.source_file||recommendation.source_file||'codes.json'} ? ${source.source_location||recommendation.source_location||`code:${recommendation.code}`}`;
    return `<div class="rec ${flagged?'flag':''}"><div class="rec-head"><div><span class="type">${escapeHtml(recommendation.type)}</span><h3>${escapeHtml(recommendation.code)}</h3><p>${escapeHtml(recommendation.description)}</p></div><span class="confidence ${score>=.9?'high':'medium'}" title="Demo match score; not coding accuracy">${Math.round(score*100)}% match</span></div><div class="evidence"><b>${flagged?'Coder review required':'Matched documentation'}</b><span>${escapeHtml(recommendation.evidence||c.text||'')}</span><small class="source-citation">Source: ${escapeHtml(citation)}</small>${instructionList.length?`<div class="source-instructions"><b>Tabular instructions</b>${instructionList.slice(0,8).map(item=>`<small>${escapeHtml(item.type)}: ${escapeHtml(item.text)}</small>`).join('')}</div>`:''}${validation?`<div class="source-instructions"><b>HCPCS rule validation: ${escapeHtml(validation.status)}</b>${validation.flags.map(flag=>`<small>${escapeHtml(flag)}</small>`).join('')}</div>`:''}</div><div class="rec-actions"><button class="${flagged?'review-btn':'approve'}" data-action="decision" data-decision="${flagged?'Review':'Validated'}" data-case-id="${escapeHtml(c.id)}">${flagged?'Send to coder review':'Mark case reviewed'}</button><button class="ghost" data-action="explanation">View explanation</button></div></div>`;
  }).join(''):'<div class="entity"><p>No supported code candidates were found in the active knowledge base. Review the installed catalogs and complete coding manually where required.</p></div>';
  $$('.evidence').forEach(evidence=>evidence.hidden=workspaceSettings?.show_evidence===false);
  const decisionActions=$('#caseDecisionActions');
  decisionActions.replaceChildren();
  if(c.demo_only){
    const decision=document.createElement('button');
    decision.className=c.status==='Validated'?'secondary':'approve';
    decision.dataset.action='decision';
    decision.dataset.decision=c.status==='Validated'?'Review':'Validated';
    decision.dataset.caseId=c.id;
    decision.textContent=c.status==='Validated'?'Reset demo review':'Mark demo example reviewed';
    decisionActions.append(decision);
  }else if(c.status!=='Validated'){
    const validate=document.createElement('button');
    validate.className='approve';
    validate.dataset.action='decision';
    validate.dataset.decision='Validated';
    validate.dataset.caseId=c.id;
    validate.textContent='Mark case reviewed';
    validate.setAttribute('aria-label','Mark this case reviewed after checking all recommendations');
    decisionActions.append(validate);
  }
  if(!c.demo_only&&c.status!=='Review'){
    const review=document.createElement('button');
    review.className='review-btn';
    review.dataset.action='decision';
    review.dataset.decision='Review';
    review.dataset.caseId=c.id;
    review.textContent='Needs further review';
    decisionActions.append(review);
  }
}
  async function decide(id,status){if(demoMode&&currentCase?.demo_only&&currentCase.id===id){currentCase.status=status;renderResult(currentCase);toast('Demo review updated','This decision exists only in this browser session.');return}try{await api('/api/cases/'+id+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:status,note:'Coder action from MediBridge frontend.'})});const c=await api('/api/cases/'+id);renderResult(c);loadNotifications();if(status==='Validated')toast('Case updated','Marked validated.');else toast('Case updated','Returned for coder review.')}catch(e){toast('Update failed',e.message)}}
document.addEventListener('click',async e=>{
  const notification=e.target.closest('.notification-item');
  if(notification){
    $('#notificationPanel').hidden=true;
    $('#bell').setAttribute('aria-expanded','false');
    try{
      const c=await api('/api/cases/'+encodeURIComponent(notification.dataset.caseId));
      renderResult(c);
      showPage('result');
    }catch(error){toast('Case error',error.message)}
    return;
  }
  const action=e.target.closest('[data-action]');
  if(action?.dataset.action==='decision'){
    await decide(action.dataset.caseId,action.dataset.decision);
    return;
  }
  if(action?.dataset.action==='explanation'){
    modal('Clinical evidence explanation','Review the documented evidence and independently verify the recommendation before recording a coding decision.');
    return;
  }
  const button=e.target.closest('.case-open');
  if(button){
    try{
      const c=await api('/api/cases/'+button.dataset.id);
      renderResult(c);
      showPage('result');
    }catch(error){toast('Case error',error.message)}
  }
});
$('#help').onclick=()=>modal('MediBridge','A private medical coding workspace with rule-based document analysis, configured coding reference lookup, and human coder review. Recommendations require independent verification.');
$('#bell').onclick=async()=>{
  const panel=$('#notificationPanel');
  const opening=panel.hidden;
  panel.hidden=!opening;
  $('#bell').setAttribute('aria-expanded',String(opening));
  if(opening)await loadNotifications();
};
document.addEventListener('click',event=>{
  if(!event.target.closest('.notification-wrap')){
    $('#notificationPanel').hidden=true;
    $('#bell').setAttribute('aria-expanded','false');
  }
});
document.addEventListener('keydown',event=>{
  if(event.key==='Escape'){
    $('#notificationPanel').hidden=true;
    $('#bell').setAttribute('aria-expanded','false');
  }
});
$('#close').onclick=()=>$('#modal').classList.remove('show');$('#modalOk').onclick=()=>$('#modal').classList.remove('show');$$('.toggle').forEach(t=>t.onclick=()=>{const enabled=t.classList.toggle('on');t.setAttribute('aria-pressed',String(enabled))});
$('#saveProfile').onclick = saveWorkspaceFromUI;
$('#thresholdSelect').onchange = saveWorkspaceFromUI;
$('#loginTab').onclick=()=>switchAuthMode('login');
$('#signupTab').onclick=()=>switchAuthMode('signup');
$('#enterPublicDemo').onclick=enterPublicDemo;
$('#loginForm').addEventListener('submit',event=>submitAuth(event,'/api/auth/login'));
$('#signupForm').addEventListener('submit',event=>submitAuth(event,'/api/auth/signup'));
$('#signOut').onclick=async()=>{
  try{
    const response=await fetch('/api/auth/logout',{method:'POST'});
    if(!response.ok)throw new Error('Sign out request failed.');
    authenticatedUser=null;
    switchAuthMode('login');
    showAuthentication('You have been signed out.');
  }catch{
    toast('Sign out failed','Reconnect and retry to clear your server session.');
  }
};

document.addEventListener('keydown',e=>{if(e.target.matches('input,textarea'))return;if(e.key==='/'){e.preventDefault();showPage('cases');$('#caseSearch').focus()}if(e.key.toLowerCase()==='n')showPage('analysis');if(e.key.toLowerCase()==='r'){caseStatus='Review';$$('.filter').forEach(item=>item.classList.toggle('active',item.dataset.status==='Review'));showPage('cases');loadCases($('#caseSearch').value)}});
async function restoreSession(){
  try{
    const demo=await api('/api/demo/config');
    $('#publicDemoEntry').hidden=!demo.enabled;
    const response=await fetch('/api/auth/me');
    if(!response.ok){
      showAuthentication();
      return;
    }
    const result=await response.json();
    if(!result.user){
      showAuthentication();
      return;
    }
    await enterWorkspace(result.user);
  }catch{
    showAuthentication('Unable to connect to MediBridge. Check the server and try again.');
  }
}
restoreSession();
renderWorkflowGraph();
