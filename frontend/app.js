const meta={dashboard:['WORKSPACE','Dashboard'],analysis:['CLASSROOM REVIEW','Review Workspace'],cases:['CASE MANAGEMENT','Cases'],knowledge:['KNOWLEDGE LAYER','Code Knowledge'],agents:['LANGGRAPH PIPELINE','Review Workflow'],activity:['AUDIT TRAIL','Activity'],settings:['WORKSPACE','Settings'],result:['ANALYSIS RESULT','Recommendation Review']};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let currentCase=null, caseStatus='All', casePage=1;
let caseRecords=[];
const casePageSize=5;
const codePageSize=40;
let codeSearchOffset=0, codeSearchTerm='';
let authenticatedUser=null;
let workspaceSettings=null;
let demoMode=false;
let classroomModeEnabled=false;
let fictionalOnlyAnalysis=false;

function setAuthenticationMessage(message=''){
  const status=$('#authMessage');
  status.textContent=message;
  status.hidden=!message;
}
function escapeHtml(value){
  return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}
function showAuthentication(message=''){
  $('#appShell').hidden=true;
  $('#authScreen').hidden=false;
  setAuthenticationMessage(message);
}
function switchAuthMode(mode){
  const signup=mode==='signup';
  $('#loginPanel').hidden=signup;
  $('#signupPanel').hidden=!signup;
  $('#loginTab').classList.toggle('active',!signup);
  $('#signupTab').classList.toggle('active',signup);
  $('#loginTab').setAttribute('aria-selected',String(!signup));
  $('#signupTab').setAttribute('aria-selected',String(signup));
  setAuthenticationMessage();
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
  fictionalOnlyAnalysis=true;
  $('#appShell').classList.add('public-demo');
  $('#analysis .heading p').textContent='Research demo only — not clinically validated or for clinical use.';
  authenticatedUser={full_name:'Guest demonstrator'};
  workspaceSettings={show_evidence:true,review_notifications:false};
  $('#authScreen').hidden=true;
  $('#appShell').hidden=false;
  $('#sidebar').hidden=true;
  $('.notification-wrap').hidden=true;
  $('#help').hidden=true;
  $('.user').hidden=true;
  $('#analysisAvailability').textContent="Guest results aren't saved. Sign in to save cases.";
  $('#analysisSaveNote').textContent='Sign in to save cases.';
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
  setAuthenticationMessage('Please wait…');
  const data=endpoint.endsWith('signup')
    ?{full_name:$('#signupName').value.trim(),email:$('#signupEmail').value.trim(),password:$('#signupPassword').value}
    :{email:$('#loginEmail').value.trim(),password:$('#loginPassword').value};
  try{
    const result=await api(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    form.reset();
    await enterWorkspace(result.user);
  }catch(error){
    setAuthenticationMessage(error.message);
  }finally{
    button.disabled=false;
  }
}

async function loadAnalysisGate(){
  if(demoMode){
    fictionalOnlyAnalysis=true;
    $('#analysisAvailability').textContent="Guest results aren't saved. Sign in to save cases.";
    $('#analysisSaveNote').textContent='Sign in to save cases.';
    $('#analyze').disabled=false;
    return;
  }
  fictionalOnlyAnalysis=false;
  $('#analyze').disabled=true;
  $('#analysisAvailability').textContent='Checking analysis availability…';
  try{
    const health=await api('/api/health');
    fictionalOnlyAnalysis=!health.clinical_data_enabled&&classroomModeEnabled;
    $('#analyze').disabled=!health.clinical_data_enabled&&!fictionalOnlyAnalysis;
    $('#analysisAvailability').textContent=health.clinical_data_enabled
      ?'Clinical-document analysis is enabled by recorded deployment approval. Use fictional examples for this class demo.'
      :fictionalOnlyAnalysis
        ?'Clinical analysis is disabled. Fictional practice cases are saved to your Cases workspace.'
        :'Analysis is unavailable until deployment approval is recorded.';
    $('#analysisSaveNote').textContent=fictionalOnlyAnalysis
      ?'Fictional practice cases are saved to your Cases workspace.'
      :'Analysis results are saved to your signed-in Cases workspace.';
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
function apiErrorMessage(detail,fallback='Request failed'){
  if(typeof detail==='string'&&detail.trim())return detail;
  if(Array.isArray(detail)){
    const messages=detail.map(item=>{
      if(typeof item==='string')return item;
      if(!item||typeof item!=='object')return '';
      const message=typeof item.msg==='string'?item.msg:'';
      const location=Array.isArray(item.loc)?item.loc.filter(part=>typeof part==='string'||typeof part==='number').join('.'):'';
      return message&&location?`${location}: ${message}`:message||location;
    }).filter(Boolean);
    if(messages.length)return messages.join('; ');
  }
  if(detail&&typeof detail==='object'){
    for(const key of ['message','detail','error']){
      if(typeof detail[key]==='string'&&detail[key].trim())return detail[key];
    }
  }
  return fallback;
}
async function api(url,opt){
  const response=await fetch(url,opt);
  const data=await response.json().catch(()=>({detail:'Server returned an invalid response'}));
  if(!response.ok){
    const message=apiErrorMessage(data?.detail,'Request failed');
    if(response.status===401&&$('#appShell')&&!$('#appShell').hidden)showAuthentication(message||'Please sign in again.');
    throw new Error(message);
  }
  return data;
}
function metric(icon,cl,label,value,small){return `<div class="metric"><div class="metric-icon ${cl}">${icon}</div><div><span>${label}</span><strong>${value}</strong><small>${small}</small></div></div>`}
function documentLabel(value){return String(value||'Clinical text').replace(/\bsynthetic\b/ig,'').replace(/\s{2,}/g,' ').trim()||'Clinical text'}
function caseStatusLabel(status){
  return ({Review:'Needs coder review',Pending:'Pending',Validated:'Completed'})[status]||status;
}
function recommendationCounts(recommendations=[]){
  return recommendations.reduce((counts,recommendation)=>{
    const type=String(recommendation.type||'').toUpperCase();
    if(type.includes('ICD'))counts.icd++;
    else if(type.includes('HCPCS'))counts.hcpcs++;
    return counts;
  },{icd:0,hcpcs:0});
}
async function loadDashboard(){
  try{
    const d=await api('/api/dashboard');
    $('#metrics').innerHTML=
      metric('✦','mi-blue','Documents analyzed',d.metrics.documents_analyzed,'In your workspace')+
      metric('◎','mi-purple','Code matches',d.metrics.recommendations,'From installed catalogs')+
      metric('!','mi-amber','Needs coder review',d.metrics.needs_validation,'Cases marked for review')+
      metric('✓','mi-green','Avg. text-match score',d.metrics.avg_confidence+'%','Keyword overlap only');
    $('#recent').innerHTML=d.cases.length?d.cases.map(item=>{
      const counts=recommendationCounts(item.recommendations);
      return `<tr><td><button class="case-id-link case-open" type="button" data-id="${escapeHtml(item.id)}">${escapeHtml(item.id)}</button><span class="sub">${escapeHtml(new Date(item.created_at).toLocaleString())}</span></td><td>${escapeHtml(documentLabel(item.document_name))}</td><td><span class="code-counts"><b>ICD ${counts.icd}</b><b>HCPCS ${counts.hcpcs}</b></span></td><td><span class="confidence ${item.overall_confidence>=90?'high':'medium'}">${escapeHtml(item.overall_confidence)}%</span></td><td><span class="status ${item.status==='Validated'?'approved':item.status==='Pending'?'pending':'review'}">${escapeHtml(caseStatusLabel(item.status))}</span></td></tr>`;
    }).join(''):'<tr><td colspan="5" class="case-state"><b>No cases to display</b><span>Start a new analysis to create a case for review.</span></td></tr>';
    loadAgentsMini();
  }catch(error){toast('Dashboard error',error.message)}
}
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
function renderCaseSummary(){
  const counts={
    total:caseRecords.length,
    review:caseRecords.filter(item=>item.status==='Review').length,
    pending:caseRecords.filter(item=>item.status==='Pending').length,
    validated:caseRecords.filter(item=>item.status==='Validated').length
  };
  $('#caseSummary').innerHTML=[
    ['All cases',counts.total,'Total in your workspace'],
    ['Needs coder review',counts.review,'Requires coder attention'],
    ['Pending',counts.pending,'Awaiting review'],
    ['Completed',counts.validated,'Coder review completed']
  ].map(([label,count,description])=>`<div class="case-stat"><span>${label}</span><b>${count}</b><small>${description}</small></div>`).join('');
}
function renderCaseList(){
  const table=$('#caseRows');
  const query=$('#caseSearch').value.trim().toLowerCase();
  const filtered=caseRecords.filter(item=>{
    const matchesStatus=caseStatus==='All'||item.status===caseStatus;
    const searchable=`${item.id} ${item.document_name||'Clinical text'} ${item.status}`.toLowerCase();
    return matchesStatus&&(!query||searchable.includes(query));
  });
  const pageCount=Math.max(1,Math.ceil(filtered.length/casePageSize));
  casePage=Math.min(casePage,pageCount);
  const first=(casePage-1)*casePageSize;
  const visible=filtered.slice(first,first+casePageSize);
  $('#caseCount').textContent=filtered.length
    ?`Showing ${first+1}-${Math.min(first+casePageSize,filtered.length)} of ${filtered.length} case${filtered.length===1?'':'s'}`
    :`Showing 0 of ${filtered.length} cases`;
  $('#clearCaseSearch').hidden=!query;
  if(visible.length){
    table.innerHTML=visible.map(item=>{
      const statusClass=item.status==='Validated'?'approved':item.status==='Pending'?'pending':'review';
      const date=Number.isNaN(Date.parse(item.created_at))?'Date unavailable':new Date(item.created_at).toLocaleString();
      const counts=recommendationCounts(item.recommendations);
      const docName=documentLabel(item.document_name);
      const extension=docName.match(/\.([a-z0-9]{2,5})$/i)?.[1]?.toUpperCase()||'TEXT';
      return `<tr><td><button class="case-id-link case-open" type="button" data-id="${escapeHtml(item.id)}">${escapeHtml(item.id)}</button><span class="sub">Coding review</span></td><td><span class="document-name">${escapeHtml(docName)}</span><span class="document-type">${escapeHtml(extension)} document</span></td><td>${escapeHtml(date)}</td><td><span class="code-count">${counts.icd}</span></td><td><span class="code-count">${counts.hcpcs}</span></td><td><span class="confidence ${item.overall_confidence>=90?'high':'medium'}">${escapeHtml(item.overall_confidence)}%</span></td><td><span class="status ${statusClass}">${escapeHtml(caseStatusLabel(item.status))}</span></td><td><details class="case-actions"><summary aria-label="Actions for ${escapeHtml(item.id)}">•••</summary><div class="case-actions-menu"><button type="button" data-action="open-case" data-case-id="${escapeHtml(item.id)}">Open review</button><button type="button" data-action="export-case" data-case-id="${escapeHtml(item.id)}">Export PDF</button></div></details></td></tr>`;
    }).join('');
  }else{
    const isEmpty=caseRecords.length===0;
    const title=isEmpty?'No cases yet':'No cases match these filters';
    const detail=isEmpty
      ?'Start an analysis to create a case for coder review.'
      :'Try a different search or clear the selected status filter.';
    table.innerHTML=`<tr><td colspan="8" class="case-state"><b>${title}</b><span>${detail}</span>${isEmpty?'<button class="primary" data-page="analysis" type="button">Start an analysis</button>':'<button class="secondary" data-case-action="clear-filters" type="button">Clear filters</button>'}</td></tr>`;
  }
  const pagination=$('#casePagination');
  pagination.hidden=pageCount===1;
  pagination.innerHTML=pageCount===1?'':`<button type="button" data-case-page="${casePage-1}" ${casePage===1?'disabled':''}>Previous</button><span>Page ${casePage} of ${pageCount}</span><button type="button" data-case-page="${casePage+1}" ${casePage===pageCount?'disabled':''}>Next</button>`;
}
async function loadCases(){
  const table=$('#caseRows');
  const message=$('#caseListMessage');
  const refresh=$('#refreshCases');
  message.hidden=true;
  table.innerHTML='<tr><td colspan="8" class="case-state">Loading cases…</td></tr>';
  refresh.disabled=true;
  try{
    caseRecords=await api('/api/cases');
    casePage=1;
    renderCaseSummary();
    renderCaseList();
  }catch(error){
    table.replaceChildren();
    message.textContent=`Cases could not be loaded: ${error.message}`;
    message.hidden=false;
    $('#caseCount').textContent='';
    $('#clearCaseSearch').hidden=true;
  }finally{
    refresh.disabled=false;
  }
}
$('#caseSearch').addEventListener('input',()=>{casePage=1;renderCaseList()});
$('#clearCaseSearch').addEventListener('click',()=>{$('#caseSearch').value='';casePage=1;renderCaseList();$('#caseSearch').focus()});
$('#refreshCases').addEventListener('click',()=>loadCases());
$('#casePagination').addEventListener('click',event=>{
  const button=event.target.closest('[data-case-page]');
  if(!button||button.disabled)return;
  casePage=Number(button.dataset.casePage);
  renderCaseList();
});
$$('.filter').forEach(button=>button.addEventListener('click',()=>{
  $$('.filter').forEach(item=>{
    const active=item===button;
    item.classList.toggle('active',active);
    item.setAttribute('aria-pressed',String(active));
  });
  caseStatus=button.dataset.status;
  casePage=1;
  renderCaseList();
}));
document.addEventListener('click',event=>{
  if(event.target.closest('[data-case-action="clear-filters"]')){
    caseStatus='All';
    casePage=1;
    $('#caseSearch').value='';
    $$('.filter').forEach(item=>{
      const active=item.dataset.status==='All';
      item.classList.toggle('active',active);
      item.setAttribute('aria-pressed',String(active));
    });
    renderCaseList();
  }
});
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
async function loadCodes(q=$('#codeSearch').value,append=false){
  if(!append)codeSearchTerm=q.trim();
  if(codeSearchTerm.length<2){
    codeSearchOffset=0;
    showCodeEmpty('Search the reference catalog','Enter at least two characters to find a code or description.');
    $('#codeCount').textContent='';
    $('#codeMore').hidden=true;
    return;
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
$('#analyze').onclick=async()=>{
  const button=$('#analyze');
  const status=$('#analysisAvailability');
  const text=$('#text').value.trim();
  const selectedFile=file.files[0];
  if(!text&&!selectedFile){
    status.textContent=fictionalOnlyAnalysis
      ?'Analysis not started. Paste fictional text or choose a fictional document first.'
      :'Analysis not started. Add text or choose a document first.';
    toast(fictionalOnlyAnalysis?'Add a fictional example':'Add documentation',fictionalOnlyAnalysis?'Upload a fictional document or paste fictional text first.':'Upload a file or paste clinical text first.');
    return;
  }
  const wasDisabled=button.disabled;
  button.disabled=true;
  button.setAttribute('aria-busy','true');
  status.textContent='Analysis is running. Please wait while the workflow reviews your input.';
  try{
    let res;
    if(fictionalOnlyAnalysis&&demoMode){
      if(text){
        res=await api('/api/demo/analyze/text',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text,synthetic_only:true})
        });
      }else{
        const fd=new FormData();
        fd.append('file',selectedFile);
        fd.append('synthetic_only','true');
        res=await api('/api/demo/analyze/file',{method:'POST',body:fd});
      }
    }else if(fictionalOnlyAnalysis){
      if(text){
        res=await api('/api/practice/analyze/text',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({text,synthetic_only:true})
        });
      }else{
        const fd=new FormData();
        fd.append('file',selectedFile);
        fd.append('synthetic_only','true');
        res=await api('/api/practice/analyze/file',{method:'POST',body:fd});
      }
    }else if(text){
      res=await api('/api/analyze/text',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({text})
      });
    }else{
      const fd=new FormData();
      fd.append('file',selectedFile);
      res=await api('/api/analyze/file',{method:'POST',body:fd});
    }
    status.textContent='Analysis complete.';
    renderResult(res.case);
    showPage('result');
    if(!res.case.demo_only){
      loadNotifications();
      loadDashboard();
      toast('Case saved for review',`${res.case.id} · ${caseStatusLabel(res.case.status)}`);
    }else{
      toast('Analysis complete',res.case.id);
    }
  }catch(error){
    status.textContent=`Analysis failed: ${error.message}`;
    toast('Analysis failed',error.message);
  }finally{
    button.removeAttribute('aria-busy');
    button.disabled=wasDisabled;
  }
};
function renderResult(c){
  currentCase=c;
  const recommendations=Array.isArray(c.recommendations)?c.recommendations:[];
  const counts=recommendationCounts(recommendations);
  $('#resultSub').textContent=`Case ${c.id} · ${c.status}`;
  $('#resultStatus').textContent=`Case status: ${caseStatusLabel(c.status)}`;
  const locations=(c.source_locations||[]).map(location=>location.page?`PDF page ${location.page}`:location.paragraph?`DOCX paragraph ${location.paragraph}`:'Document text');
  const sourceSummary=locations.length?` Source: ${[...new Set(locations)].join(', ')}.`:'';
  const workflow=c.workflow||{};
  const gaps=Array.isArray(c.gaps)?c.gaps:[];
  $('#resultSummary').textContent=`${recommendations.length} candidate(s) · ${gaps.length} review flag(s). Text-match scores are not clinical accuracy.${sourceSummary}`;
  $('#overall').textContent=`${c.overall_confidence??0}% text-match score`;
  $('#resultSummaryCards').innerHTML=[
    ['ICD-10-CM candidates',counts.icd],
    ['HCPCS candidates',counts.hcpcs],
    ['Human review','Required']
  ].map(([label,value])=>`<div class="result-summary-card"><small>${escapeHtml(label)}</small><b>${escapeHtml(value)}</b></div>`).join('');
  $('#workflowInfo').hidden=false;
  $('#workflowInfo').innerHTML=`<div class="workflow-info-heading"><b>${escapeHtml(workflow.engine||'Analysis workflow')} execution</b><small>${escapeHtml(workflow.name||'Review pipeline')} · Retrieval: ${escapeHtml(workflow.retrieval_method||'lexical')} · Optional model: ${escapeHtml(workflow.model_status||'not reported')}${workflow.model_rationale?` · ${escapeHtml(workflow.model_rationale)}`:''}</small></div><div class="workflow result-workflow">${workflowGraphMarkup(workflow)}</div>`;
  renderWorkflowGraph(workflow);
  $('#reviewFlags').hidden=gaps.length===0;
  $('#reviewFlags').innerHTML=gaps.length?`<b>Coder review flags</b><ul>${gaps.map(flag=>`<li>${escapeHtml(flag)}</li>`).join('')}</ul>`:'';
  const extracted=c.extracted||{};
  $('#extracted').innerHTML=Object.entries(extracted).filter(([key])=>key!=='context').map(([key,values])=>`<div class="entity"><label>${escapeHtml(key)}</label><div class="pills">${(Array.isArray(values)&&values.length?values:['None detected']).map(value=>`<span>${escapeHtml(value)}</span>`).join('')}</div></div>`).join('');
  const mentions=(c.clinical_context?.mentions||extracted.context||[]).filter(item=>item&&typeof item==='object');
  $('#clinicalMentions').innerHTML=mentions.length?`<div class="clinical-mentions"><b>Clinical mentions and evidence spans</b>${mentions.map(item=>`<div class="clinical-mention"><span class="type">${escapeHtml(item.category||'Clinical mention')} · ${escapeHtml(item.assertion||'unclassified')}</span><b>${escapeHtml(item.text||'')}</b><small>${escapeHtml(item.experiencer||'Patient')} · source characters ${escapeHtml(item.start??'?')}-${escapeHtml(item.end??'?')}</small></div>`).join('')}</div>`:'';
  const groupLabel=type=>String(type||'Other').toUpperCase().includes('ICD')
    ?'ICD-10-CM'
    :String(type||'').toUpperCase().includes('HCPCS')?'HCPCS':'Other candidates';
  const groups=new Map();
  for(const recommendation of recommendations){
    const label=groupLabel(recommendation.type);
    if(!groups.has(label))groups.set(label,[]);
    groups.get(label).push(recommendation);
  }
  $('#recommendations').innerHTML=recommendations.length?Array.from(groups.entries()).map(([label,items])=>`<section class="recommendation-group"><div class="recommendation-group-heading"><h3>${escapeHtml(label)}</h3><span>${items.length} candidate${items.length===1?'':'s'}</span></div>${items.map(recommendation=>{
    const score=Math.max(0,Math.min(1,Number(recommendation.confidence??recommendation.retrieval_score??0)));
    const flagged=recommendation.review_required||score<.85;
    const source=recommendation.source||{};
    const validation=recommendation.validation;
    const instructionList=Array.isArray(recommendation.instructions)?recommendation.instructions:[];
    const citation=`${source.catalog_type||recommendation.type||'Catalog'} ${source.catalog_version||recommendation.catalog_version||''} · ${source.source_file||recommendation.source_file||'codes.json'} · ${source.source_location||recommendation.source_location||`code:${recommendation.code}`}`;
    return `<div class="rec ${flagged?'flag':''}"><div class="rec-head"><div><span class="type">${escapeHtml(recommendation.type)}</span><h3>${escapeHtml(recommendation.code)}</h3><p>${escapeHtml(recommendation.description)}</p></div><span class="confidence ${score>=.9?'high':'medium'}" title="Match score; not coding accuracy">${Math.round(score*100)}% match</span></div><div class="evidence"><b>${flagged?'Coder review required':'Matched documentation'}</b><span>${escapeHtml(recommendation.evidence||c.text||'')}</span><small class="source-citation">Source: ${escapeHtml(citation)}</small>${instructionList.length?`<div class="source-instructions"><b>Tabular instructions</b>${instructionList.slice(0,8).map(item=>`<small>${escapeHtml(item.type)}: ${escapeHtml(item.text)}</small>`).join('')}</div>`:''}${validation?`<div class="source-instructions"><b>HCPCS rule validation: ${escapeHtml(validation.status)}</b>${(validation.flags||[]).map(flag=>`<small>${escapeHtml(flag)}</small>`).join('')}</div>`:''}</div><div class="rec-actions"><button class="${flagged?'review-btn':'approve'}" data-action="decision" data-decision="${flagged?'Review':'Validated'}" data-case-id="${escapeHtml(c.id)}">${flagged?'Send to coder review':'Mark case reviewed'}</button><button class="ghost" data-action="explanation">View explanation</button></div></div>`;
  }).join('')}</section>`).join(''):'<div class="entity"><p>No supported code candidates were found in the active knowledge base. Review the installed catalogs and complete coding manually where required.</p></div>';
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
function printReport(record){
  if(!record)return;
  const recommendations=Array.isArray(record.recommendations)?record.recommendations:[];
  const extracted=record.extracted&&typeof record.extracted==='object'?record.extracted:{};
  const mentions=(record.clinical_context?.mentions||extracted.context||[]).filter(item=>item&&typeof item==='object');
  const list=values=>Array.isArray(values)?values.map(value=>`<li>${escapeHtml(value)}</li>`).join(''):'';
  const extractedHtml=Object.entries(extracted).filter(([key])=>key!=='context').map(([key,values])=>`<section><h3>${escapeHtml(key)}</h3><ul>${list(values)}</ul></section>`).join('');
  const mentionHtml=mentions.length?`<section><h2>Clinical mentions</h2>${mentions.map(item=>`<p><b>${escapeHtml(item.text||'')}</b> · ${escapeHtml(item.category||'Clinical mention')} · ${escapeHtml(item.assertion||'unclassified')} · ${escapeHtml(item.experiencer||'Patient')}<br><small>${escapeHtml(item.evidence||'')}</small></p>`).join('')}</section>`:'';
  const recHtml=recommendations.length?recommendations.map(item=>{
    const source=item.source||{};
    const score=Math.round(Math.max(0,Math.min(1,Number(item.confidence??item.retrieval_score??0)))*100);
    return `<article><div><span>${escapeHtml(item.type||'Catalog')}</span><b>${escapeHtml(item.code||'')}</b><strong>${score}% match</strong></div><h3>${escapeHtml(item.description||'')}</h3><p><b>Evidence:</b> ${escapeHtml(item.evidence||'Not provided')}</p><p><b>Source:</b> ${escapeHtml([source.catalog_type||item.type,source.catalog_version||item.catalog_version,source.source_file||item.source_file,source.source_location||item.source_location].filter(Boolean).join(' · ')||'Catalog reference')}</p>${(Array.isArray(item.instructions)?item.instructions:[]).length?`<p><b>Tabular instructions:</b> ${escapeHtml(item.instructions.map(instruction=>`${instruction.type}: ${instruction.text}`).join(' · '))}</p>`:''}</article>`;
  }).join(''):'<p>No supported code candidates were found.</p>';
  document.querySelector('#pdfReport')?.remove();
  document.querySelector('#pdfReportStyles')?.remove();
  const report=document.createElement('section');
  report.id='pdfReport';
  report.className='print-report';
  report.innerHTML=`<header><h1>MediBridge · Coding review report</h1><div class="muted">Case ${escapeHtml(record.id||'')} · ${escapeHtml(record.status||'Pending')} · ${escapeHtml(documentLabel(record.document_name))}</div><div class="muted">${escapeHtml(record.created_at?new Date(record.created_at).toLocaleString():'')}</div></header><div class="summary"><span><b>${recommendationCounts(recommendations).icd}</b> ICD-10-CM</span><span><b>${recommendationCounts(recommendations).hcpcs}</b> HCPCS</span><span><b>${escapeHtml(record.overall_confidence??0)}%</b> text-match score</span><span><b>Required</b> human review</span></div><p class="notice"><b>Research prototype.</b> Recommendations and text-match scores are not clinical accuracy. A qualified coder must independently verify every recommendation. This report does not represent clinical approval.</p><section><h2>Extracted information</h2>${extractedHtml||'<p>No extracted information.</p>'}</section>${mentionHtml}<section><h2>Code recommendations</h2>${recHtml}</section><p class="muted">In the print dialog, choose Save as PDF. This report is generated locally and is not saved by MediBridge.</p>`;
  const style=document.createElement('style');
  style.id='pdfReportStyles';
  style.textContent=`.print-report{display:none}@media print{body{margin:0!important;background:#fff!important}.print-report{display:block!important;max-width:900px;margin:0 auto;padding:24px;font:14px Arial,sans-serif;color:#20302c}.print-report header{border-bottom:2px solid #287267;padding-bottom:16px}.print-report h1{margin:0 0 6px}.print-report h2{font-size:17px;margin-top:24px}.print-report h3{font-size:14px}.print-report small,.print-report .muted{color:#64736c}.print-report .summary{display:flex;gap:24px;padding:14px;background:#f2f5f2;margin:16px 0}.print-report .notice{border:1px solid #99601d;background:#fbf1df;padding:12px}.print-report article,.print-report section{break-inside:avoid}.print-report article{border:1px solid #dce4df;border-radius:6px;padding:14px;margin:10px 0}.print-report article>div{display:flex;gap:12px;align-items:center}.print-report article>div strong{margin-left:auto}.print-report article>div b{font:600 16px monospace}.print-report li{margin:4px 0}body>*:not(#pdfReport){display:none!important}.print-report .notice{print-color-adjust:exact}}`;
  document.head.append(style);
  document.body.append(report);
  const cleanup=()=>{
    report.remove();
    style.remove();
  };
  window.addEventListener('afterprint',cleanup,{once:true});
  window.print();
}
$('#exportResult').addEventListener('click',()=>printReport(currentCase));
  async function decide(id,status){  if(currentCase?.demo_only&&currentCase.id===id){currentCase.status=status;renderResult(currentCase);toast('Review updated','This decision exists only in the current browser session.');return}try{await api('/api/cases/'+id+'/decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({decision:status,note:'Coder action from MediBridge frontend.'})});const c=await api('/api/cases/'+id);renderResult(c);loadNotifications();if(status==='Validated')toast('Case updated','Coder review completed.');else if(status==='Review')toast('Case updated','Needs coder review.');else toast('Case updated','Returned to pending.')}catch(e){toast('Update failed',e.message)}}
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
    const card=action.closest('.rec');
    const code=card?.querySelector('h3')?.textContent||'Recommendation';
    const evidence=card?.querySelector('.evidence')?.innerText||'No evidence details are available.';
    modal(`${code} · evidence and source`,evidence);
    return;
  }
  if(action?.dataset.action==='open-case'){
    action.closest('details')?.removeAttribute('open');
    try{
      const record=await api('/api/cases/'+encodeURIComponent(action.dataset.caseId));
      renderResult(record);
      showPage('result');
    }catch(error){toast('Case error',error.message)}
    return;
  }
  if(action?.dataset.action==='export-case'){
    action.closest('details')?.removeAttribute('open');
    const record=caseRecords.find(item=>item.id===action.dataset.caseId);
    if(record)printReport(record);
    else toast('Export unavailable','Refresh the case list and try again.');
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
const publicDemoButton=$('#enterPublicDemo');
if(publicDemoButton)publicDemoButton.onclick=enterPublicDemo;
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

document.addEventListener('keydown',e=>{if(e.target.matches('input,textarea'))return;if(e.key==='/'){e.preventDefault();showPage('cases');$('#caseSearch').focus()}if(e.key.toLowerCase()==='n')showPage('analysis');if(e.key.toLowerCase()==='r'){caseStatus='Review';$$('.filter').forEach(item=>{const active=item.dataset.status==='Review';item.classList.toggle('active',active);item.setAttribute('aria-pressed',String(active))});showPage('cases')}});
async function restoreSession(){
  try{
    const demo=await api('/api/demo/config');
    classroomModeEnabled=demo.enabled;
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
