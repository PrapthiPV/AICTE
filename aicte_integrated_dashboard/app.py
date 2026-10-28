from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import sqlite3, os, json, re
from datetime import datetime, date

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    AI_AVAILABLE = True
except Exception:
    AI_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'aicte_cases.db')
app = Flask(__name__)
CORS(app)

STATUSES = ['Pending', 'Under Process', 'Disposed', 'Transferred', 'Escalated']
BUREAUS = ['RB', 'PGRC', 'Academic Bureau', 'Regional Office', 'Other']


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def init_db():
    conn = db()
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS institutions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, permanent_id TEXT UNIQUE NOT NULL,
      name TEXT NOT NULL, region TEXT NOT NULL, state TEXT, city TEXT, address TEXT,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cases (
      id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT UNIQUE NOT NULL,
      institution_id INTEGER NOT NULL REFERENCES institutions(id), received_date TEXT NOT NULL,
      category TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL,
      bureau TEXT NOT NULL, officer TEXT, last_action TEXT, next_action TEXT,
      last_action_date TEXT, due_date TEXT, priority TEXT DEFAULT 'Normal',
      related_case_ids TEXT DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS actions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL REFERENCES cases(case_id),
      action TEXT NOT NULL, bureau TEXT NOT NULL, officer TEXT, remarks TEXT,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS alerts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, alert_type TEXT NOT NULL,
      message TEXT NOT NULL, severity TEXT DEFAULT 'medium', created_at TEXT NOT NULL,
      resolved INTEGER DEFAULT 0
    );
    ''')
    count = conn.execute('SELECT COUNT(*) FROM institutions').fetchone()[0]
    if count == 0:
        now = datetime.now().isoformat(timespec='seconds')
        institutions = [
          ('AICTE-10021','North Valley Institute of Technology','Northern','Uttar Pradesh','Lucknow','Sector 4, Lucknow'),
          ('AICTE-10022','Coastal School of Engineering','Southern','Tamil Nadu','Chennai','OMR, Chennai'),
          ('AICTE-10023','Deccan College of Technical Studies','Western','Maharashtra','Pune','University Road, Pune'),
          ('AICTE-10024','Eastern Institute of Applied Sciences','Eastern','West Bengal','Kolkata','Salt Lake, Kolkata'),
          ('AICTE-10025','Central Polytechnic and Research Institute','Central','Madhya Pradesh','Bhopal','Arera Hills, Bhopal')]
        conn.executemany('INSERT INTO institutions(permanent_id,name,region,state,city,address,created_at) VALUES(?,?,?,?,?,?,?)', [(*x,now) for x in institutions])
        cases = [
          ('RB-2026-001',1,'2026-10-02','Infrastructure','Laboratory equipment and workshop facilities reported as inadequate.','Under Process','RB','A. Sharma','Notice issued to institution','Review institution response','2026-10-08','2026-11-05','High'),
          ('PGRC-2026-014',1,'2026-10-05','Infrastructure','Student grievance about inadequate lab facilities and missing workshop equipment.','Pending','PGRC','M. Verma','Complaint acknowledged','Coordinate with Regulation Bureau','2026-10-06','2026-10-30','High'),
          ('PGRC-2026-018',2,'2026-10-11','Faculty','Complaint regarding delayed faculty salary payments.','Under Process','PGRC','S. Iyer','Documents requested','Verify submitted documents','2026-10-15','2026-11-02','Normal'),
          ('RB-2026-009',3,'2026-09-14','Compliance','Annual compliance documents not submitted within the prescribed period.','Escalated','RB','R. Kulkarni','Escalated to competent authority','Authority review','2026-10-20','2026-10-25','Critical'),
          ('RO-2026-006',4,'2026-10-18','Student Welfare','Hostel and campus safety grievance submitted by students.','Pending','Regional Office','P. Das','Complaint registered','Assign inspection officer','2026-10-18','2026-11-08','Normal'),
          ('PGRC-2026-021',5,'2026-10-21','Examination','Delay in issuing academic transcripts and completion certificates.','Transferred','PGRC','N. Khan','Transferred to Academic Bureau','Await receiving bureau acknowledgement','2026-10-22','2026-11-10','Normal'),
          ('RB-2026-012',2,'2026-10-22','Faculty','Concerns about faculty availability and compliance with staffing norms.','Pending','RB','S. Iyer','Initial scrutiny completed','Request faculty records','2026-10-23','2026-11-12','Normal'),
          ('PGRC-2026-025',1,'2026-10-24','Infrastructure','The institution has insufficient practical laboratory equipment for students.','Pending','PGRC','M. Verma','Complaint acknowledged','Check related RB case','2026-10-24','2026-10-29','High')]
        conn.executemany('''INSERT INTO cases(case_id,institution_id,received_date,category,description,status,bureau,officer,last_action,next_action,last_action_date,due_date,priority,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', [(*c,now,now) for c in cases])
        actions = [
          ('RB-2026-001','Case registered','RB','A. Sharma','Initial complaint recorded.'),
          ('RB-2026-001','Notice issued','RB','A. Sharma','Institution asked to submit a response.'),
          ('PGRC-2026-014','Complaint acknowledged','PGRC','M. Verma','Acknowledgement sent to complainant.'),
          ('RB-2026-009','Escalated','RB','R. Kulkarni','Escalated due to timeline risk.'),
          ('PGRC-2026-021','Transferred','PGRC','N. Khan','Forwarded to Academic Bureau for action.')]
        conn.executemany('INSERT INTO actions(case_id,action,bureau,officer,remarks,created_at) VALUES(?,?,?,?,?,?)', [(*a,now) for a in actions])
    conn.commit(); conn.close()


def rowdict(row):
    return dict(row) if row else None


def get_cases():
    conn = db()
    rows = conn.execute('''SELECT c.*, i.permanent_id, i.name AS institution_name, i.region, i.state, i.city
      FROM cases c JOIN institutions i ON i.id=c.institution_id ORDER BY c.received_date DESC, c.id DESC''').fetchall()
    conn.close()
    return [rowdict(r) for r in rows]


def overlap_pairs(cases):
    """Rule + TF-IDF candidate detector. It flags candidates, never makes a legal/regulatory decision."""
    pairs=[]
    texts=[(c.get('description') or '')+' '+(c.get('category') or '') for c in cases]
    sims={}
    if AI_AVAILABLE and len(texts)>1:
        try:
            matrix=TfidfVectorizer(stop_words='english', ngram_range=(1,2)).fit_transform(texts)
            sims=cosine_similarity(matrix)
        except ValueError:
            sims={}
    for i,a in enumerate(cases):
      for j in range(i+1,len(cases)):
        b=cases[j]
        if a['institution_id'] != b['institution_id']:
            continue
        if a['case_id'] == b['case_id'] or a['status']=='Disposed' and b['status']=='Disposed':
            continue
        score=float(sims[i][j]) if hasattr(sims,'__getitem__') and len(sims) else 0.0
        different_bureaus=a['bureau'] != b['bureau']
        same_category=(a['category'].lower()==b['category'].lower())
        # Exact institution match + different bureau is a coordination candidate;
        # semantic similarity raises confidence and helps match different descriptions.
        if different_bureaus or score >= 0.18:
            confidence=min(0.99, 0.52 + (0.28 if different_bureaus else 0) + (0.20*score) + (0.08 if same_category else 0))
            reason='Same institution is being handled by different Bureaus/Cells' if different_bureaus else 'Descriptions appear semantically similar'
            pairs.append({'case_a':a['case_id'],'case_b':b['case_id'],'institution_id':a['permanent_id'],
              'institution_name':a['institution_name'],'bureau_a':a['bureau'],'bureau_b':b['bureau'],
              'status_a':a['status'],'status_b':b['status'],'category_a':a['category'],'category_b':b['category'],
              'similarity':round(score,3),'confidence':round(confidence,2),'reason':reason,
              'message':'Potential Overlapping Cases – Coordination Required'})
    pairs.sort(key=lambda p:(p['bureau_a']==p['bureau_b'], -p['confidence']))
    return pairs


@app.route('/')
def home():
    return render_template('index.html')

@app.get('/api/health')
def health():
    return jsonify({'ok':True,'service':'AICTE Integrated Institution Complaint Monitoring Dashboard','ai_model':'TF-IDF cosine similarity + rule-based institution/bureau matching','semantic_ai_available':AI_AVAILABLE})

@app.get('/api/dashboard')
def dashboard():
    cases=get_cases(); today=date.today().isoformat()
    by_status={s:sum(c['status']==s for c in cases) for s in STATUSES}
    overdue=[c for c in cases if c['status'] not in ('Disposed',) and c.get('due_date') and c['due_date'] < today]
    due_soon=[c for c in cases if c['status'] not in ('Disposed',) and c.get('due_date') and today <= c['due_date'] <= (date.today()).fromordinal(date.today().toordinal()+3).isoformat()]
    by_bureau={}
    for c in cases: by_bureau[c['bureau']]=by_bureau.get(c['bureau'],0)+1
    return jsonify({'total':len(cases),'pending':by_status['Pending'],'under_process':by_status['Under Process'],'disposed':by_status['Disposed'],
      'transferred':by_status['Transferred'],'escalated':by_status['Escalated'],'overdue':len(overdue),'due_soon':len(due_soon),
      'by_status':by_status,'by_bureau':by_bureau,'overlap_count':len(overlap_pairs(cases)),'recent_cases':cases[:6],'overdue_cases':overdue})

@app.get('/api/cases')
def cases_list():
    cases=get_cases(); q=request.args.get('q','').strip().lower()
    filters={k:request.args.get(k,'').strip() for k in ['status','bureau','region','category','from_date','to_date']}
    result=[]
    for c in cases:
      hay=' '.join(str(c.get(k) or '') for k in ['case_id','permanent_id','institution_name','description','officer']).lower()
      if q and q not in hay: continue
      if filters['status'] and c['status']!=filters['status']: continue
      if filters['bureau'] and c['bureau']!=filters['bureau']: continue
      if filters['region'] and c['region']!=filters['region']: continue
      if filters['category'] and c['category']!=filters['category']: continue
      if filters['from_date'] and c['received_date']<filters['from_date']: continue
      if filters['to_date'] and c['received_date']>filters['to_date']: continue
      result.append(c)
    return jsonify(result)

@app.get('/api/institutions')
def institutions_list():
    conn=db(); rows=conn.execute('''SELECT i.*,COUNT(c.id) AS case_count, SUM(CASE WHEN c.status!='Disposed' THEN 1 ELSE 0 END) AS open_count
      FROM institutions i LEFT JOIN cases c ON c.institution_id=i.id GROUP BY i.id ORDER BY i.name''').fetchall(); conn.close()
    return jsonify([rowdict(r) for r in rows])

@app.get('/api/institutions/<permanent_id>')
def institution_detail(permanent_id):
    conn=db(); inst=conn.execute('SELECT * FROM institutions WHERE permanent_id=?',(permanent_id,)).fetchone(); conn.close()
    if not inst: return jsonify({'error':'Institution not found'}),404
    cases=[c for c in get_cases() if c['permanent_id']==permanent_id]
    return jsonify({'institution':rowdict(inst),'cases':cases,'overlaps':[p for p in overlap_pairs(get_cases()) if p['institution_id']==permanent_id]})

@app.get('/api/overlaps')
def overlaps():
    return jsonify({'model':'TF-IDF cosine similarity + deterministic cross-bureau rules','ai_available':AI_AVAILABLE,'items':overlap_pairs(get_cases())})

@app.get('/api/cases/<case_id>')
def case_detail(case_id):
    cases=get_cases(); case=next((c for c in cases if c['case_id']==case_id),None)
    if not case: return jsonify({'error':'Case not found'}),404
    conn=db(); actions=conn.execute('SELECT * FROM actions WHERE case_id=? ORDER BY created_at DESC,id DESC',(case_id,)).fetchall(); conn.close()
    return jsonify({'case':case,'actions':[rowdict(a) for a in actions]})

@app.post('/api/cases')
def create_case():
    data=request.get_json(silent=True) or {}
    required=['permanent_id','received_date','category','description','status','bureau']
    missing=[k for k in required if not data.get(k)]
    if missing: return jsonify({'error':'Missing required fields','fields':missing}),400
    if data['status'] not in STATUSES: return jsonify({'error':'Invalid status'}),400
    conn=db(); inst=conn.execute('SELECT id FROM institutions WHERE permanent_id=?',(data['permanent_id'],)).fetchone()
    if not inst: conn.close(); return jsonify({'error':'Unknown AICTE Permanent ID. Add institution first.'}),400
    case_id=data.get('case_id') or f"CASE-{datetime.now().strftime('%y%m%d')}-{datetime.now().strftime('%H%M%S')}"
    now=datetime.now().isoformat(timespec='seconds')
    try:
      conn.execute('''INSERT INTO cases(case_id,institution_id,received_date,category,description,status,bureau,officer,last_action,next_action,last_action_date,due_date,priority,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(case_id,inst['id'],data['received_date'],data['category'],data['description'],data['status'],data['bureau'],data.get('officer',''),data.get('last_action','Case registered'),data.get('next_action','Initial review'),data.get('last_action_date',now[:10]),data.get('due_date',''),data.get('priority','Normal'),now,now))
      conn.execute('INSERT INTO actions(case_id,action,bureau,officer,remarks,created_at) VALUES(?,?,?,?,?,?)',(case_id,'Case registered',data['bureau'],data.get('officer',''),data.get('remarks','Case created in dashboard'),now))
      conn.commit()
    except sqlite3.IntegrityError as e:
      conn.close(); return jsonify({'error':f'Could not create case: {e}'}),400
    conn.close()
    return jsonify({'ok':True,'case_id':case_id,'message':'Case created'}),201

@app.patch('/api/cases/<case_id>')
def update_case(case_id):
    data=request.get_json(silent=True) or {}; allowed=['status','bureau','officer','last_action','next_action','last_action_date','due_date','priority','description','category']
    updates={k:v for k,v in data.items() if k in allowed}
    if not updates: return jsonify({'error':'No supported fields supplied'}),400
    if 'status' in updates and updates['status'] not in STATUSES: return jsonify({'error':'Invalid status'}),400
    now=datetime.now().isoformat(timespec='seconds'); conn=db()
    existing=conn.execute('SELECT * FROM cases WHERE case_id=?',(case_id,)).fetchone()
    if not existing: conn.close(); return jsonify({'error':'Case not found'}),404
    updates['updated_at']=now
    sql='UPDATE cases SET '+','.join(f'{k}=?' for k in updates)+' WHERE case_id=?'
    conn.execute(sql,tuple(updates.values())+(case_id,))
    action=data.get('action_note') or ('Status changed to '+updates['status'] if 'status' in updates else 'Case details updated')
    conn.execute('INSERT INTO actions(case_id,action,bureau,officer,remarks,created_at) VALUES(?,?,?,?,?,?)',(case_id,action,updates.get('bureau',existing['bureau']),updates.get('officer',existing['officer']),data.get('remarks',''),now))
    conn.commit(); conn.close()
    return jsonify({'ok':True,'message':'Case updated; action history recorded'})

@app.post('/api/institutions')
def create_institution():
    data=request.get_json(silent=True) or {}
    required=['permanent_id','name','region']
    if any(not data.get(k) for k in required): return jsonify({'error':'permanent_id, name and region are required'}),400
    conn=db()
    try:
      conn.execute('INSERT INTO institutions(permanent_id,name,region,state,city,address,created_at) VALUES(?,?,?,?,?,?,?)',(data['permanent_id'],data['name'],data['region'],data.get('state',''),data.get('city',''),data.get('address',''),datetime.now().isoformat(timespec='seconds'))); conn.commit()
    except sqlite3.IntegrityError: conn.close(); return jsonify({'error':'That AICTE Permanent ID already exists'}),400
    conn.close(); return jsonify({'ok':True}),201

@app.get('/api/reports')
def reports():
    cases=get_cases(); overlaps=overlap_pairs(cases)
    by_region={}; by_category={}; by_bureau={}; by_month={}
    for c in cases:
      by_region[c['region']]=by_region.get(c['region'],0)+1
      by_category[c['category']]=by_category.get(c['category'],0)+1
      by_bureau[c['bureau']]=by_bureau.get(c['bureau'],0)+1
      month=(c['received_date'] or '')[:7]; by_month[month]=by_month.get(month,0)+1
    disposed=sum(c['status']=='Disposed' for c in cases)
    return jsonify({'by_region':by_region,'by_category':by_category,'by_bureau':by_bureau,'by_month':dict(sorted(by_month.items())),'disposal_rate':round(disposed/len(cases)*100,1) if cases else 0,'overlap_pairs':overlaps})

@app.get('/api/export.csv')
def export_csv():
    import csv, io
    rows=get_cases(); output=io.StringIO(); fields=['case_id','permanent_id','institution_name','region','received_date','category','description','status','bureau','officer','last_action','next_action','last_action_date','due_date','priority']
    writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader()
    for r in rows: writer.writerow({k:r.get(k,'') for k in fields})
    from flask import Response
    return Response(output.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=aicte_cases_export.csv'})

if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1',port=5000,debug=True)
