import json
import re
from pathlib import Path
from .clinical_nlp.extraction import extract_clinical_context

CODING_DATA_DIR = Path(__file__).resolve().parents[2] / 'data' / 'coding'
def load_reference_codes(coding_dir=None):
    """Load normalized reference codes prepared from the supplied source files."""
    root = Path(coding_dir) if coding_dir is not None else CODING_DATA_DIR
    records = {}
    for catalog in sorted(root.rglob('codes.json')):
        try:
            data = json.loads(catalog.read_text(encoding='utf-8'))
        except OSError as error:
            raise RuntimeError(f'Cannot read coding catalog {catalog}: {error}') from error
        except json.JSONDecodeError as error:
            raise RuntimeError(f'Coding catalog {catalog} contains invalid JSON: {error}') from error
        if not isinstance(data,list):
            raise RuntimeError(f'Coding catalog {catalog} must contain a JSON array.')
        for item in data:
            if not isinstance(item, dict):
                continue
            code_type = str(item.get('type', '')).strip()
            code = str(item.get('code', '')).strip().upper()
            description = str(item.get('description', '')).strip()
            terms = str(item.get('terms', description)).strip()
            if code_type and code and description:
                records[(code_type, code)] = (code_type, code, description, terms)
    return list(records.values())

CODES = load_reference_codes()

def negated(text, phrase):
    for m in re.finditer(re.escape(phrase), text, re.I):
        if re.search(r'\b(no|not|without|denies|denied|negative for)\b', text[max(0,m.start()-45):m.start()].lower()): return True
    return False

def clinical_understanding(text):
    t=text.lower(); out={k:[] for k in ('diagnoses','symptoms','procedures','medications','negations')}
    terms=[('hypertension','diagnoses'),('high blood pressure','diagnoses'),('type 2 diabetes','diagnoses'),('diabetes mellitus','diagnoses'),('hyperlipidemia','diagnoses'),('gerd','diagnoses'),('reflux','diagnoses'),('upper respiratory infection','diagnoses'),('fatigue','symptoms'),('headache','symptoms'),('cough','symptoms'),('fever','symptoms'),('nausea','symptoms'),('blood pressure measurement','procedures'),('venipuncture','procedures'),('blood collection','procedures'),('a1c','procedures'),('metabolic panel','procedures'),('metformin','medications'),('lisinopril','medications'),('atorvastatin','medications')]
    for phrase,bucket in terms:
        if phrase in t:
            if negated(text,phrase): out['negations'].append(phrase)
            elif phrase not in out[bucket]: out[bucket].append(phrase)
    if 'no chest pain' in t or 'denies chest pain' in t: out['negations'].append('chest pain')
    out['negations']=list(dict.fromkeys(out['negations']))
    return out

def coding_retrieval(text, extracted):
    t=text.lower(); recs=[]
    context={item['text'].casefold():item for item in extracted.get('context',[])}
    for typ,code,desc,terms in CODES:
        separators = '|' if '|' in terms else ', '
        candidates=[x.strip() for x in terms.split(separators) if x.strip()]
        hits=[
            x for x in candidates
            if x.lower() in t and not negated(text,x)
            and (x.casefold() not in context or context[x.casefold()]['assertion']=='affirmed')
        ]
        if hits:
            match_score=len(hits)/len(candidates)
            evidence=next((s.strip() for s in re.split(r'(?<=[.!?])\s+',text) if any(h.lower() in s.lower() for h in hits)),text[:180])
            recs.append({'type':typ,'code':code,'description':desc,'confidence':match_score,'evidence':evidence})
    return recs

def validate(recs,text,extracted):
    gaps=[]; t=text.lower()
    if 'procedure' in t and not extracted['procedures']: gaps.append('Procedure mentioned without a clearly identifiable procedure name.')
    if extracted['procedures'] and not any(item['type']=='HCPCS' for item in recs):
        gaps.append('A documented procedure needs coder review against the applicable procedure code set.')
    if 'diabetes' in t and 'complication' not in t: gaps.append('Confirm whether diabetes has documented complications before final coding.')
    if not recs: gaps.append('No supported code candidates were found in the active knowledge base.')
    overall=round(sum(r['confidence'] for r in recs)/len(recs)*100,1) if recs else 0
    if gaps and overall>85: overall=round(overall-2,1)
    return gaps,overall

def analyze_text(text):
    context=extract_clinical_context(text)
    extracted=clinical_understanding(text)
    active_terms={
        mention.text.casefold() for mention in context.mentions
        if mention.assertion == 'affirmed' and mention.experiencer == 'patient'
    }
    if context.mentions:
        extracted['diagnoses']=[term for term in extracted['diagnoses'] if term.casefold() in active_terms]
        extracted['symptoms']=[term for term in extracted['symptoms'] if term.casefold() in active_terms]
        extracted['procedures']=[term for term in extracted['procedures'] if term.casefold() in active_terms]
        extracted['medications']=[term for term in extracted['medications'] if term.casefold() in active_terms]
    extracted['context']=[mention.model_dump() for mention in context.mentions]
    recs=coding_retrieval(text,extracted)
    mention_by_term={mention.text.casefold():mention for mention in context.mentions}
    for recommendation in recs:
        matched=next((mention_by_term[hit] for hit in mention_by_term if hit in recommendation['evidence'].casefold()),None)
        if matched:
            recommendation['evidence_span']={
                'source_file':matched.source_file,
                'start':matched.start,
                'end':matched.end,
                'text':matched.text,
            }
    gaps,overall=validate(recs,text,extracted)
    gaps.extend(context.review_reasons)
    if context.review_required:
        overall=min(overall,70)
    return {
        'extracted':extracted,
        'recommendations':recs,
        'gaps':gaps,
        'overall_confidence':overall,
        'review_required':context.review_required or bool(gaps),
        'clinical_context':{
            'mentions':[mention.model_dump() for mention in context.mentions],
            'conflicts':context.conflicts,
            'review_reasons':context.review_reasons,
        },
    }
