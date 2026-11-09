from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from datetime import datetime, timedelta
import hashlib, hmac, json, re, secrets, sqlite3, time, uuid
from .config import get_settings
from .database import INTEGRITY_ERRORS, conn, init_db
from .schemas import DecisionRequest, LoginRequest, SignupRequest, SyntheticTextRequest, TextRequest
from .services.ingestion import extract_document_text
from .services.pipeline import CODES, analyze_text
from .services.workflow.graph import run_analysis_workflow
from .services.llm.client import LocalModelClient
from .services.retrieval.embeddings import OllamaEmbeddingAdapter

settings = get_settings()
BASE=Path(__file__).resolve().parent.parent
UPLOADS=settings['uploads_dir']; FRONTEND=BASE/'frontend'
UPLOADS.mkdir(exist_ok=True)
DEFAULT_WORKSPACE={
    'full_name':'',
    'role':'Medical Coding Analyst',
    'team':'Coding Review Unit',
    'review_threshold':85,
    'show_evidence':True,
    'flag_low_confidence':True,
    'review_notifications':True,
}
app=FastAPI(
    title=settings['app_name'],
    version='1.1.0',
    description='Clinical coding workspace for code suggestion, validation, and human review.',
    docs_url='/docs' if settings['app_env']!='production' else None,
    redoc_url='/redoc' if settings['app_env']!='production' else None
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings['allowed_origins'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*']
)

@app.middleware('http')
async def security_headers(request: Request, call_next):
    origin=request.headers.get('origin')
    if request.method in {'POST','PUT','PATCH','DELETE'} and origin:
        same_origin=f'{request.url.scheme}://{request.url.netloc}'
        if origin.rstrip('/')!=same_origin and origin not in settings['allowed_origins']:
            return Response('Request origin is not allowed.',status_code=403)
    response=await call_next(request)
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Permissions-Policy']='camera=(), microphone=(), geolocation=()'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    if settings['app_env']=='production':
        response.headers['Strict-Transport-Security']='max-age=31536000; includeSubDomains'
    return response

SESSION_COOKIE='medibridge_session'
SESSION_LIFETIME=12*60*60
PASSWORD_ITERATIONS=600_000
CASE_DEADLINE_DAYS=3

def read_workspace_state(user_id, full_name):
    c=conn(); payload={**DEFAULT_WORKSPACE,'full_name':full_name}
    for row in c.execute('SELECT key, value FROM settings WHERE user_id=?',(user_id,)):
        try:
            if row['key'] in {'review_threshold'}:
                payload[row['key']] = int(row['value'])
            elif row['key'] in {'show_evidence','flag_low_confidence','review_notifications'}:
                payload[row['key']] = row['value'].lower() == 'true'
            else:
                payload[row['key']] = row['value']
        except (ValueError, TypeError):
            payload[row['key']] = row['value']
    c.close(); return payload

def write_workspace_state(user_id, payload):
    c=conn();
    for key, value in payload.items():
        if isinstance(value, bool): value = str(value).lower()
        if isinstance(value, int): value = str(value)
        c.execute('INSERT INTO settings(user_id,key,value) VALUES (?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value = excluded.value', (user_id,key,str(value)))
    c.commit(); c.close(); return payload

def add_activity(user_id,kind,title,detail):
 c=conn(); c.execute('INSERT INTO activity(user_id,created_at,kind,title,detail) VALUES (?,?,?,?,?)',(user_id,datetime.now().astimezone().isoformat(timespec='seconds'),kind,title,detail)); c.commit(); c.close()
def serialize(row):
 return {'id':row['id'],'created_at':row['created_at'],'assigned_at':row['assigned_at'],'deadline_at':row['deadline_at'],'document_name':row['document_name'],'source':row['source'],'source_locations':json.loads(row['source_locations_json']),'text':row['text'],'status':row['status'],'overall_confidence':row['overall_confidence'],'extracted':json.loads(row['extracted_json']),'recommendations':json.loads(row['recommendations_json']),'gaps':json.loads(row['gaps_json']),'workflow':json.loads(row['workflow_json'])}

def analyze_with_workflow(text):
    baseline=analyze_text(text)
    workflow=run_analysis_workflow(text,baseline)
    model_status=workflow.get('model_status','unknown')
    retrieval_method=workflow.get('retrieval_method','lexical')
    review_reasons=workflow.get('review_reasons',[])
    trace=workflow.get('pipeline_trace',[])
    names={
        'parse':'Context extraction',
        'retrieve':'Catalog retrieval',
        'reason':'Optional model reasoning',
        'validate':'Review validation',
    }

    def node_detail(item):
        if item['error']:
            return item['error']
        outputs=item['outputs']
        if item['node']=='parse':
            return (
                f"{outputs.get('mention_count',0)} clinical mention(s) extracted; "
                f"NLP status: {outputs.get('nlp_status','unknown')}."
            )
        if item['node']=='retrieve':
            return (
                f"{outputs.get('candidate_count',0)} candidate(s) retrieved using "
                f"{outputs.get('retrieval_method','unknown')}."
            )
        if item['node']=='reason':
            return (
                f"{outputs.get('selected_count',0)} candidate code(s) selected by "
                f"{outputs.get('model','local model')}."
            )
        return (
            f"{outputs.get('review_reason_count',0)} review flag(s); "
            "human verification remains required."
        )

    nodes=[
        {
            'id':item['node'],
            'name':names.get(item['node'],item['node']),
            'status':item['status'],
            'detail':node_detail(item),
            'inputs':item['inputs'],
            'outputs':item['outputs'],
            'error':item['error'],
        }
        for item in trace
    ]
    baseline['recommendations']=workflow.get('recommendations',baseline['recommendations'])
    baseline['clinical_context']=workflow.get('context',baseline.get('clinical_context',{}))
    baseline['workflow']={
        'name':'LangGraph analysis workflow',
        'engine':'LangGraph',
        'stages':['parse','retrieve','reason','validate'],
        'nodes':nodes,
        'trace':trace,
        'human_review_required':True,
        'model_status':model_status,
        'model_error':workflow.get('model_error'),
        'model_provenance':workflow.get('model_provenance'),
        'model_rationale':workflow.get('model_rationale',''),
        'retrieval_method':retrieval_method,
        'retrieval_warning':workflow.get('retrieval_warning'),
        'review_required':workflow.get('review_required',True),
        'review_reasons':review_reasons,
        'model_selected_codes':workflow.get('model_selected_codes',[]),
    }
    baseline['gaps']=list(dict.fromkeys(
        baseline.get('gaps',[])+workflow.get('review_reasons',[])
    ))
    baseline['review_required']=True
    return baseline



def case_schedule(now=None):
    assigned_at = now or datetime.now().astimezone()
    return (
        assigned_at.isoformat(timespec='seconds'),
        (assigned_at + timedelta(days=CASE_DEADLINE_DAYS)).isoformat(timespec='seconds'),
    )

def case_review_status(result, workspace):
    below_threshold=result['overall_confidence']<int(workspace.get('review_threshold',85))
    needs_review=bool(result['gaps']) or (
        workspace.get('flag_low_confidence',True) and below_threshold
    )
    return 'Review' if needs_review else 'Pending'

init_db()

def hash_password(password, salt=None):
    salt=salt or secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,PASSWORD_ITERATIONS)
    return f'pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}'

def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, expected=encoded.split('$')
        if algorithm!='pbkdf2_sha256':
            return False
        actual=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),int(iterations)).hex()
        return hmac.compare_digest(actual,expected)
    except (ValueError, TypeError):
        return False

def public_user(row):
    return {'id':row['id'],'email':row['email'],'full_name':row['full_name']}

def set_session_cookie(response, token):
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_LIFETIME, httponly=True,
        secure=settings['app_env']=='production', samesite='strict', path='/'
    )

def current_user(request: Request):
    token=request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401,'Sign in to continue.')
    c=conn()
    row=c.execute(
        'SELECT users.id,users.email,users.full_name FROM auth_sessions '
        'JOIN users ON users.id=auth_sessions.user_id '
        'WHERE auth_sessions.token_hash=? AND auth_sessions.expires_at>?',
        (hashlib.sha256(token.encode('utf-8')).hexdigest(),time.time())
    ).fetchone()
    c.close()
    if not row:
        raise HTTPException(401,'Your session has expired. Please sign in again.')
    return public_user(row)

@app.get('/api/health')
def health():
    c=conn()
    c.execute('SELECT 1').fetchone()
    c.close()
    catalogs={}
    for code_type, _, _, _ in CODES:
        catalogs[code_type]=catalogs.get(code_type,0)+1
    return {
        'status':'ok',
        'service': settings['app_name'],
        'environment': settings['app_env'],
        'clinical_data_enabled': settings['clinical_data_approved'],
        'synthetic_demo_enabled': settings['synthetic_demo_enabled'],
        'analysis_gate_reasons': settings['analysis_gate_reasons'],
        'time': datetime.now().isoformat(timespec='seconds'),
        'catalogs':catalogs,
    }

@app.get('/api/model-status')
def model_status():
    try:
        reasoner=LocalModelClient().check_status()
    except ValueError as error:
        reasoner={
            'configured':bool(settings['local_model_name']),
            'connected':False,
            'model_available':False,
            'model':settings['local_model_name'] or None,
            'model_digest':None,
            'error':str(error),
        }
    embedding_name=settings['local_embedding_model_name']
    if embedding_name:
        try:
            embedding_client=OllamaEmbeddingAdapter(
                embedding_name,
                base_url=settings['local_model_url'],
                timeout=settings['local_model_timeout'],
            ).client
            embedding=embedding_client.check_status()
        except ValueError as error:
            embedding={
                'configured':True,
                'connected':False,
                'model_available':False,
                'model':embedding_name,
                'model_digest':None,
                'error':str(error),
            }
    else:
        embedding={
            'configured':False,
            'connected':False,
            'model_available':False,
            'model':None,
            'model_digest':None,
            'error':'Set OLLAMA_EMBEDDING_MODEL to enable semantic retrieval.',
        }
    clinical_model=settings['clinical_nlp_model']
    return {
        'reasoner':reasoner,
        'embeddings':embedding,
        'clinical_nlp':{
            'configured':bool(clinical_model),
            'model':Path(clinical_model).name if clinical_model else None,
            'status':(
                'configured_local_only; availability is checked when first loaded'
                if clinical_model else 'not_configured'
            ),
            'external_data_transfer':False,
        },
        'external_data_transfer':False,
    }

@app.post('/api/auth/signup')
def signup(payload: SignupRequest, response: Response):
    email=payload.email.strip().lower()
    full_name=payload.full_name.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email) or len(full_name)<2:
        raise HTTPException(400,'Enter a valid email address and full name.')
    user_id=uuid.uuid4().hex
    c=conn()
    try:
        c.execute(
            'INSERT INTO users(id,email,full_name,password_hash,created_at) VALUES (?,?,?,?,?)',
            (user_id,email,full_name,hash_password(payload.password),datetime.now().astimezone().isoformat(timespec='seconds'))
        )
        token=secrets.token_urlsafe(32)
        c.execute('INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES (?,?,?)',
                  (hashlib.sha256(token.encode('utf-8')).hexdigest(),user_id,time.time()+SESSION_LIFETIME))
        c.commit()
        user=c.execute('SELECT id,email,full_name FROM users WHERE id=?',(user_id,)).fetchone()
    except INTEGRITY_ERRORS as error:
        c.rollback()
        if (
            'UNIQUE constraint failed: users.email' in str(error)
            or 'uq_users_email' in str(error)
        ):
            raise HTTPException(409,'An account with this email already exists.') from error
        raise
    finally:
        c.close()
    set_session_cookie(response,token)
    return {'user':public_user(user)}

@app.post('/api/auth/login')
def login(payload: LoginRequest, response: Response):
    email=payload.email.strip().lower()
    c=conn()
    row=c.execute('SELECT id,email,full_name,password_hash FROM users WHERE email=?',(email,)).fetchone()
    if not row or not verify_password(payload.password,row['password_hash']):
        c.close()
        raise HTTPException(401,'Email or password is incorrect.')
    token=secrets.token_urlsafe(32)
    c.execute('DELETE FROM auth_sessions WHERE expires_at<=?',(time.time(),))
    c.execute('INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES (?,?,?)',
              (hashlib.sha256(token.encode('utf-8')).hexdigest(),row['id'],time.time()+SESSION_LIFETIME))
    c.commit(); c.close()
    set_session_cookie(response,token)
    return {'user':public_user(row)}

@app.post('/api/auth/logout')
def logout(request: Request, response: Response):
    token=request.cookies.get(SESSION_COOKIE)
    if token:
        c=conn()
        c.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(token.encode('utf-8')).hexdigest(),))
        c.commit(); c.close()
    response.delete_cookie(SESSION_COOKIE,path='/',httponly=True,
                           secure=settings['app_env']=='production',samesite='strict')
    return {'ok':True}

@app.get('/api/auth/me')
def auth_me(request: Request):
    try:
        return {'user':current_user(request)}
    except HTTPException as error:
        if error.status_code != 401:
            raise
        return {'user':None}

@app.get('/api/dashboard')
def dashboard(user=Depends(current_user)):
    c=conn(); total=c.execute('SELECT COUNT(*) n FROM cases WHERE user_id=?',(user['id'],)).fetchone()['n']; review=c.execute("SELECT COUNT(*) n FROM cases WHERE user_id=? AND status='Review'",(user['id'],)).fetchone()['n']; avg=c.execute('SELECT AVG(overall_confidence) a FROM cases WHERE user_id=?',(user['id'],)).fetchone()['a'] or 0; activity=c.execute('SELECT * FROM activity WHERE user_id=? ORDER BY id DESC LIMIT 8',(user['id'],)).fetchall(); cases=c.execute('SELECT * FROM cases WHERE user_id=? ORDER BY created_at DESC LIMIT 6',(user['id'],)).fetchall(); c.close()
    rec_count=sum(len(json.loads(r['recommendations_json'])) for r in cases)
    return {'metrics':{'documents_analyzed':total,'recommendations':rec_count,'needs_validation':review,'avg_confidence':round(avg,1)},'cases':[serialize(r) for r in cases],'activity':[dict(x) for x in activity]}

@app.get('/api/cases')
def get_cases(q:str='', user=Depends(current_user)):
    c=conn(); rows=c.execute('SELECT * FROM cases WHERE user_id=? ORDER BY created_at DESC',(user['id'],)).fetchall(); c.close(); items=[serialize(r) for r in rows]
    if q: items=[x for x in items if q.lower() in (x['id']+' '+(x['document_name'] or '')+' '+x['status']).lower()]
    return items

@app.get('/api/notifications')
def notifications(user=Depends(current_user)):
    now=datetime.now().astimezone()
    today=now.date()
    c=conn()
    assigned_today=c.execute(
        'SELECT COUNT(*) AS n FROM cases WHERE user_id=? AND substr(assigned_at,1,10)=?',
        (user['id'],today.isoformat())
    ).fetchone()['n']
    rows=c.execute(
        "SELECT id,document_name,status,deadline_at FROM cases "
        "WHERE user_id=? AND status!='Validated' AND deadline_at IS NOT NULL "
        'ORDER BY deadline_at,created_at',
        (user['id'],)
    ).fetchall()
    c.close()
    items=[]
    due_today=0
    overdue=0
    for row in rows:
        deadline=datetime.fromisoformat(row['deadline_at'])
        if deadline.date()<today:
            category='overdue'
            overdue+=1
        elif deadline.date()==today:
            category='due_today'
            due_today+=1
        else:
            category='upcoming'
        items.append({
            'case_id':row['id'],
            'document_name':row['document_name'] or 'Clinical case',
            'status':row['status'],
            'deadline_at':row['deadline_at'],
            'category':category,
        })
    return {
        'summary':{
            'assigned_today':assigned_today,
            'open_cases':len(items),
            'due_today':due_today,
            'overdue':overdue,
        },
        'notifications':items,
    }

@app.get('/api/cases/{case_id}')
def get_case(case_id:str, user=Depends(current_user)):
    c=conn(); row=c.execute('SELECT * FROM cases WHERE id=? AND user_id=?',(case_id,user['id'])).fetchone(); c.close()
    if not row: raise HTTPException(404,'Case not found')
    return serialize(row)

@app.get('/api/workspace')
def get_workspace(user=Depends(current_user)):
    return read_workspace_state(user['id'],user['full_name'])

@app.post('/api/workspace')
def save_workspace(payload: dict, user=Depends(current_user)):
    cleaned={**DEFAULT_WORKSPACE,'full_name':user['full_name']}
    for key in ('full_name','role','team','review_threshold','show_evidence','flag_low_confidence','review_notifications'):
        if key in payload:
            cleaned[key]=payload[key]
    cleaned['full_name']=str(cleaned['full_name']).strip()
    cleaned['role']=str(cleaned['role']).strip()
    cleaned['team']=str(cleaned['team']).strip()
    try:
        cleaned['review_threshold']=int(cleaned['review_threshold'])
    except (ValueError,TypeError):
        raise HTTPException(400,'Review threshold must be a whole number from 0 to 100.')
    if not 0<=cleaned['review_threshold']<=100 or not 2<=len(cleaned['full_name'])<=100 or len(cleaned['role'])>100 or len(cleaned['team'])>120:
        raise HTTPException(400,'Enter a valid profile and review threshold.')
    if any(not isinstance(cleaned[key],bool) for key in ('show_evidence','flag_low_confidence','review_notifications')):
        raise HTTPException(400,'Review preferences must be boolean values.')
    c=conn()
    c.execute('UPDATE users SET full_name=? WHERE id=?',(cleaned['full_name'],user['id']))
    c.commit(); c.close()
    return write_workspace_state(user['id'],cleaned)

@app.post('/api/analyze/text')
def analyze(req:TextRequest, user=Depends(current_user)):
    if not settings['clinical_data_approved']:
        raise HTTPException(
            503,
            'Clinical document analysis is disabled until organizational governance '
            'approves this deployment and all release evidence is recorded. '
            + '; '.join(settings['analysis_gate_reasons']),
        )
    if len(req.text.strip()) < 10: raise HTTPException(400,'Clinical text must contain at least 10 characters.')
    result=analyze_with_workflow(req.text.strip()); workspace = read_workspace_state(user['id'],user['full_name']); cid='MB-'+uuid.uuid4().hex[:8].upper(); now=datetime.now().astimezone(); assigned_at,deadline_at=case_schedule(now)
    status=case_review_status(result,workspace)
    c=conn(); c.execute('INSERT INTO cases(id,user_id,created_at,assigned_at,deadline_at,document_name,source,text,status,overall_confidence,extracted_json,recommendations_json,gaps_json,workflow_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,user['id'],assigned_at,assigned_at,deadline_at,'Pasted Clinical Text','text',req.text.strip(),status,result['overall_confidence'],json.dumps(result['extracted']),json.dumps(result['recommendations']),json.dumps(result['gaps']),json.dumps(result['workflow']))); c.commit(); c.close()
    add_activity(user['id'],'analysis',f'Case {cid} analyzed',f"{len(result['recommendations'])} recommendation(s) generated with {result['overall_confidence']}% overall confidence.")
    return {'case':{'id':cid,**result,'status':status,'created_at':assigned_at,'assigned_at':assigned_at,'deadline_at':deadline_at}}

@app.post('/api/analyze/file')
async def analyze_file(file:UploadFile=File(...), user=Depends(current_user)):
    if not settings['clinical_data_approved']:
        raise HTTPException(
            503,
            'Clinical document analysis is disabled until organizational governance '
            'approves this deployment and all release evidence is recorded. '
            + '; '.join(settings['analysis_gate_reasons']),
        )
    allowed={'.txt','.json','.md','.csv','.log','.pdf','.docx'}
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in allowed: raise HTTPException(400,'Upload TXT, JSON, Markdown, CSV, LOG, PDF, or DOCX files.')
    content=await file.read(10_000_001)
    if len(content)>10_000_000:
        raise HTTPException(413,'Files must be 10 MB or smaller.')
    document_name=(file.filename or 'Clinical document').replace('\\','/').rsplit('/',1)[-1]
    try:
        raw,source_locations=extract_document_text(document_name,content)
    except ValueError as error:
        raise HTTPException(400,str(error)) from error
    result=analyze_with_workflow(raw); workspace = read_workspace_state(user['id'],user['full_name'])
    cid='MB-'+uuid.uuid4().hex[:8].upper(); now=datetime.now().astimezone(); assigned_at,deadline_at=case_schedule(now); status=case_review_status(result,workspace)
    c=conn(); c.execute('INSERT INTO cases(id,user_id,created_at,assigned_at,deadline_at,document_name,source,text,status,overall_confidence,extracted_json,recommendations_json,gaps_json,source_locations_json,workflow_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(cid,user['id'],now.isoformat(timespec='seconds'),assigned_at,deadline_at,document_name,'upload',raw,status,result['overall_confidence'],json.dumps(result['extracted']),json.dumps(result['recommendations']),json.dumps(result['gaps']),json.dumps(source_locations),json.dumps(result['workflow']))); c.commit(); c.close()
    add_activity(user['id'],'analysis',f'Case {cid} analyzed',f'Uploaded {document_name}; {len(result["recommendations"])} recommendation(s) generated.')
    return {'case':{'id':cid,**result,'status':status,'created_at':now.isoformat(timespec='seconds'),'assigned_at':assigned_at,'deadline_at':deadline_at,'document_name':document_name,'source_locations':source_locations}}

def make_demo_case(text, document_name, source_locations):
    result=analyze_with_workflow(text)
    return {
        'id':'DEMO-'+uuid.uuid4().hex[:8].upper(),
        **result,
        'text':text,
        'status':'Review',
        'created_at':datetime.now().astimezone().isoformat(timespec='seconds'),
        'document_name':document_name,
        'source':'synthetic_demo',
        'source_locations':source_locations,
        'demo_only':True,
    }

@app.get('/api/demo/config')
def synthetic_demo_config():
    return {'enabled':settings['synthetic_demo_enabled'],'synthetic_only':True}

@app.post('/api/demo/analyze/text')
def analyze_synthetic_text(payload:SyntheticTextRequest):
    if not settings['synthetic_demo_enabled']:
        raise HTTPException(404,'The synthetic demonstration is disabled.')
    text=payload.text.strip()
    if len(text)<10:
        raise HTTPException(400,'Synthetic text must contain at least 10 non-whitespace characters.')
    return {
        'demo_only':True,
        'case':make_demo_case(text,'Synthetic pasted text',[]),
    }

@app.post('/api/demo/analyze/file')
async def analyze_synthetic_file(
    file:UploadFile=File(...),
    synthetic_only:bool=Form(False),
):
    if not settings['synthetic_demo_enabled']:
        raise HTTPException(404,'The synthetic demonstration is disabled.')
    if not synthetic_only:
        raise HTTPException(400,'Confirm that this document contains synthetic data only.')
    allowed={'.txt','.json','.md','.csv','.log','.pdf','.docx'}
    document_name=(file.filename or 'Synthetic document').replace('\\','/').rsplit('/',1)[-1]
    if Path(document_name).suffix.lower() not in allowed:
        raise HTTPException(400,'Upload TXT, JSON, Markdown, CSV, LOG, PDF, or DOCX files.')
    content=await file.read(10_000_001)
    if len(content)>10_000_000:
        raise HTTPException(413,'Files must be 10 MB or smaller.')
    try:
        text,source_locations=extract_document_text(document_name,content)
    except ValueError as error:
        raise HTTPException(400,str(error)) from error
    return {
        'demo_only':True,
        'case':make_demo_case(text,document_name,source_locations),
    }

@app.post('/api/cases/{case_id}/decision')
def decision(case_id:str, req:DecisionRequest, user=Depends(current_user)):
    if req.decision not in ('Validated','Review','Pending'): raise HTTPException(400,'Invalid decision')
    c=conn(); row=c.execute('SELECT * FROM cases WHERE id=? AND user_id=?',(case_id,user['id'])).fetchone()
    if not row: c.close(); raise HTTPException(404,'Case not found')
    c.execute('UPDATE cases SET status=? WHERE id=? AND user_id=?',(req.decision,case_id,user['id'])); c.commit(); c.close(); add_activity(user['id'],'decision',f'Case {case_id} marked {req.decision}',req.note or 'Coder decision recorded.'); return {'ok':True,'status':req.decision}

@app.get('/api/codes')
def codes(q:str='', limit:int=40, offset:int=0, user=Depends(current_user)):
    items=[{'type':a,'code':b,'description':c,'terms':d} for a,b,c,d in CODES]
    query=q.strip().lower()
    if not query: return []
    items=[x for x in items if query in (x['type']+' '+x['code']+' '+x['description']+' '+x['terms']).lower()]
    start=max(0,offset); page_size=max(1,min(limit,100))
    return items[start:start+page_size]

@app.get('/api/catalogs')
def catalogs(user=Depends(current_user)):
    counts={}
    for code_type, _, _, _ in CODES:
        counts[code_type]=counts.get(code_type,0)+1
    return {'catalogs':[{'type':code_type,'records':count} for code_type,count in sorted(counts.items())]}

@app.get('/api/codes/{code}/instructions')
def code_instructions(code:str, user=Depends(current_user)):
    catalog=BASE/'data'/'coding'/'ICD10CM'/'2027'/'tabular.json'
    if not catalog.is_file():
        raise HTTPException(404,'ICD-10-CM tabular instructions are not installed.')
    try:
        payload=json.loads(catalog.read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as error:
        raise HTTPException(503,'The ICD-10-CM tabular catalog could not be read.') from error
    if isinstance(payload,list):
        record=next((item for item in payload if item.get('code','').casefold()==code.casefold()),None)
    else:
        record=next((item for item in payload.get('codes',[]) if item.get('code','').casefold()==code.casefold()),None)
    if record is None:
        raise HTTPException(404,'Code not found in the installed ICD-10-CM tabular catalog.')
    if isinstance(payload,dict):
        lookup=payload.get('instruction_records',{})
        record['instructions']=[
            lookup[reference] for reference in record.get('instruction_refs',[])
            if reference in lookup
        ]
    return record

@app.get('/api/demo/synthea')
def synthea_demo_status(user=Depends(current_user)):
    path=BASE/'data'/'synthea-demo.sqlite'
    if not path.is_file():
        return {'available':False,'synthetic':True,'dataset_version':None,'counts':{}}
    try:
        demo=sqlite3.connect(path)
        metadata=dict(demo.execute('SELECT key,value FROM metadata'))
        demo.close()
    except sqlite3.Error as error:
        raise HTTPException(503,'Synthetic demo database is unavailable.') from error
    return {
        'available':True,
        'synthetic':metadata.get('synthetic')=='true',
        'dataset_version':metadata.get('dataset_version'),
        'counts':{
            'patients':int(metadata.get('patient_count','0')),
            'encounters':int(metadata.get('encounter_count','0')),
            'conditions':int(metadata.get('condition_count','0')),
        },
    }

@app.get('/api/agents')
def agents(user=Depends(current_user)):
    return [
        {'id':'parse','name':'Context extraction','role':'LangGraph node','description':'Extracts clinical mentions, assertion, temporality, experiencer and review context.','tools':['Evidence spans','Context flags','Review reasons']},
        {'id':'retrieve','name':'Catalog retrieval','role':'LangGraph node','description':'Finds candidate codes from installed references and optional local retrieval indexes.','tools':['ICD-10-CM','HCPCS','Source citations']},
        {'id':'reason','name':'Optional model reasoning','role':'LangGraph node','description':'Optionally ranks retrieved candidates with a loopback-only local model. It cannot invent or approve codes.','tools':['Optional local model','Candidate-only output','No external API']},
        {'id':'validate','name':'Review validation','role':'LangGraph node','description':'Applies review rules, preserves uncertainty flags and requires human verification.','tools':['Catalog validation','Review flags','No automatic approval']},
        {'id':'human','name':'Human review','role':'Required handoff','description':'A qualified reviewer independently checks every candidate against authoritative references. This is not an automated graph node.','tools':['Independent verification','Human decision','No clinical use']}
    ]

@app.get('/api/activity')
def activities(user=Depends(current_user)):
    c=conn(); rows=c.execute('SELECT id,created_at,kind,title,detail FROM activity WHERE user_id=? ORDER BY id DESC LIMIT 50',(user['id'],)).fetchall(); c.close(); return [dict(x) for x in rows]

app.mount('/assets', StaticFiles(directory=FRONTEND/'assets'), name='assets')
app.mount('/static', StaticFiles(directory=FRONTEND), name='static')

@app.get('/{path:path}')
def frontend(path:str):
    if path == 'api' or path.startswith('api/'):
        raise HTTPException(404,'API endpoint not found.')
    return FileResponse(FRONTEND/'index.html')
