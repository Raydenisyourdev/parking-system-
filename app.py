from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import sqlite3, os, math, uuid
from datetime import datetime
BASE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(BASE,'parking.db')
app=Flask(__name__); app.secret_key='parkflow-local-demo-secret'
DEMO_MODE=True; GRACE_SECONDS=10 if DEMO_MODE else 120; FIRST_HOUR_RATE=50; EXTRA_HOUR_RATE=30

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def now(): return datetime.now().isoformat(timespec='seconds')
def log(msg):
 c=db(); c.execute('INSERT INTO activity_log(message,created_at) VALUES(?,?)',(msg,now())); c.commit(); c.close()
def init():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS parking_slots(id INTEGER PRIMARY KEY AUTOINCREMENT,slot_number TEXT UNIQUE,status TEXT NOT NULL DEFAULT "available"); CREATE TABLE IF NOT EXISTS vehicles(id INTEGER PRIMARY KEY AUTOINCREMENT,plate_number TEXT NOT NULL,slot_id INTEGER NOT NULL,entry_time TEXT,exit_time TEXT,status TEXT NOT NULL DEFAULT "pending",qr_token TEXT,FOREIGN KEY(slot_id) REFERENCES parking_slots(id)); CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT,vehicle_id INTEGER NOT NULL,amount REAL NOT NULL,payment_method TEXT NOT NULL,payment_time TEXT NOT NULL,status TEXT NOT NULL DEFAULT "paid",FOREIGN KEY(vehicle_id) REFERENCES vehicles(id)); CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY AUTOINCREMENT,message TEXT NOT NULL,created_at TEXT NOT NULL);''')
 if c.execute('SELECT COUNT(*) n FROM parking_slots').fetchone()['n']==0:
  for i in range(24): c.execute('INSERT INTO parking_slots(slot_number,status) VALUES(?,"available")',(f'{chr(65+i//12)}{i%12+1:02d}',))
 c.commit(); c.close()
def logged(): return 'admin' in session
@app.route('/')
def home(): return redirect(url_for('dashboard' if logged() else 'login'))
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  if request.form.get('username')=='admin' and request.form.get('password')=='parkflow': session['admin']='admin'; return redirect(url_for('dashboard'))
  flash('Invalid username or password.')
 return render_template('login.html')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))
@app.route('/dashboard')
def dashboard(): return render_template('dashboard.html') if logged() else redirect(url_for('login'))
@app.route('/api/state')
def state():
 if not logged(): return jsonify(error='unauthorized'),401
 c=db(); slots=[dict(x) for x in c.execute('SELECT * FROM parking_slots ORDER BY id')]; vehicles=[dict(x) for x in c.execute('SELECT v.*,s.slot_number FROM vehicles v JOIN parking_slots s ON s.id=v.slot_id WHERE v.status IN ("pending","entering","parked","exiting")')]; activity=[dict(x) for x in c.execute('SELECT * FROM activity_log ORDER BY id DESC LIMIT 8')]; revenue=c.execute('SELECT COALESCE(SUM(amount),0) n FROM payments').fetchone()['n']; c.close(); return jsonify(slots=slots,vehicles=vehicles,activity=activity,stats={'total':len(slots),'available':sum(x['status']=='available' for x in slots),'occupied':sum(x['status'] in ('reserved','occupied') for x in slots),'revenue':revenue})
@app.route('/api/register',methods=['POST'])
def register():
 if not logged(): return jsonify(error='unauthorized'),401
 d=request.get_json(); plate=d.get('plate','').strip().upper().replace(' ',''); slot=d.get('slot',''); c=db(); s=c.execute('SELECT * FROM parking_slots WHERE slot_number=?',(slot,)).fetchone()
 if len(plate)<4: c.close(); return jsonify(error='Enter a valid plate number.'),400
 if not s or s['status']!='available': c.close(); return jsonify(error='That slot is not available.'),400
 if c.execute('SELECT id FROM vehicles WHERE UPPER(plate_number)=UPPER(?) AND status IN ("pending","entering","parked","exiting")',(plate,)).fetchone(): c.close(); return jsonify(error='This vehicle is already active.'),400
 token=str(uuid.uuid4()); cur=c.execute('INSERT INTO vehicles(plate_number,slot_id,status,qr_token) VALUES(?,?,"pending",?)',(plate,s['id'],token)); vid=cur.lastrowid; c.execute('UPDATE parking_slots SET status="reserved" WHERE id=?',(s['id'],)); c.commit(); c.close(); log(f'🚗 {plate} assigned to {slot}'); return jsonify(id=vid,plate=plate,slot=slot,token=token)
def getv(vid):
 c=db(); v=c.execute('SELECT v.*,s.slot_number FROM vehicles v JOIN parking_slots s ON s.id=v.slot_id WHERE v.id=?',(vid,)).fetchone(); c.close(); return v
@app.route('/api/entry/<int:vid>',methods=['POST'])
def entry(vid):
 if not logged(): return jsonify(error='unauthorized'),401
 v=getv(vid)
 if not v:return jsonify(error='Vehicle not found.'),404
 c=db(); c.execute('UPDATE vehicles SET status="entering",entry_time=? WHERE id=?',(now(),vid)); c.commit(); c.close(); log(f'✓ Entry QR verified for {v["plate_number"]}'); return jsonify(ok=True)
@app.route('/api/park/<int:vid>',methods=['POST'])
def park(vid):
 if not logged(): return jsonify(error='unauthorized'),401
 v=getv(vid); c=db(); c.execute('UPDATE vehicles SET status="parked" WHERE id=?',(vid,)); c.execute('UPDATE parking_slots SET status="occupied" WHERE id=?',(v['slot_id'],)); c.commit(); c.close(); log(f'🅿 {v["plate_number"]} parked in {v["slot_number"]}'); return jsonify(ok=True)
@app.route('/api/exit/<int:vid>',methods=['POST'])
def exit_scan(vid):
 if not logged(): return jsonify(error='unauthorized'),401
 v=getv(vid)
 if not v or v['status']!='parked': return jsonify(error='Vehicle is not currently parked.'),400
 c=db(); c.execute('UPDATE vehicles SET status="exiting",exit_time=? WHERE id=?',(now(),vid)); c.commit(); c.close(); log(f'↗ Exit QR verified for {v["plate_number"]}'); return jsonify(ok=True)
def calc(vid):
 v=getv(vid); a=datetime.fromisoformat(v['entry_time']); b=datetime.fromisoformat(v['exit_time']) if v['exit_time'] else datetime.now(); total=max(0,int((b-a).total_seconds())); bill=max(0,total-GRACE_SECONDS); amount=0 if bill==0 else FIRST_HOUR_RATE+max(0,math.ceil(bill/3600)-1)*EXTRA_HOUR_RATE; return v,total,bill,amount
@app.route('/api/bill/<int:vid>')
def bill(vid):
 if not logged(): return jsonify(error='unauthorized'),401
 v,t,b,a=calc(vid); return jsonify(id=vid,plate=v['plate_number'],slot=v['slot_number'],total=t,billable=b,grace=GRACE_SECONDS,amount=a)
@app.route('/api/pay/<int:vid>',methods=['POST'])
def pay(vid):
 if not logged(): return jsonify(error='unauthorized'),401
 d=request.get_json(); v,t,b,a=calc(vid); method=d.get('method','M-PESA'); c=db(); c.execute('INSERT INTO payments(vehicle_id,amount,payment_method,payment_time) VALUES(?,?,?,?)',(vid,a,method,now())); c.execute('UPDATE vehicles SET status="completed" WHERE id=?',(vid,)); c.execute('UPDATE parking_slots SET status="available" WHERE id=?',(v['slot_id'],)); c.commit(); c.close(); log(f'💰 {v["plate_number"]} paid KSh {a:,.0f} via {method}'); return jsonify(ok=True,amount=a)
init()
if __name__=='__main__': app.run(host='127.0.0.1',port=5000,debug=True)
