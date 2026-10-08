import hashlib,hmac,secrets,re,time
ITERATIONS=600000

def set_pin(db,pin):
 if not re.fullmatch(r'\d{6,12}',pin):raise ValueError('Choose a PIN of 6–12 digits')
 salt=secrets.token_hex(16);hashed=hashlib.pbkdf2_hmac('sha256',pin.encode(),bytes.fromhex(salt),ITERATIONS).hex()
 with db:db.execute('INSERT INTO auth VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET salt=excluded.salt,pin_hash=excluded.pin_hash',(salt,hashed));db.execute('DELETE FROM sessions')

def login(db,pin,ip):
 stamp=time.time()
 with db:
  db.execute('DELETE FROM login_attempts WHERE time<?',(stamp-900,));db.execute('DELETE FROM sessions WHERE expires<?',(stamp,))
  if db.execute('SELECT count(*) FROM login_attempts WHERE ip=?',(ip,)).fetchone()[0]>=8:return None,'Too many attempts. Try again in 15 minutes.'
  db.execute('INSERT INTO login_attempts VALUES(?,?)',(ip,stamp))
 row=db.execute('SELECT * FROM auth WHERE id=1').fetchone()
 if not row:return None,'PIN has not been configured in Terminal.'
 if not isinstance(pin,str) or not re.fullmatch(r'\d{6,12}',pin):return None,'Incorrect PIN.'
 hashed=hashlib.pbkdf2_hmac('sha256',pin.encode(),bytes.fromhex(row['salt']),ITERATIONS).hex()
 if not hmac.compare_digest(hashed,row['pin_hash']):return None,'Incorrect PIN.'
 token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
 with db:
  db.execute('DELETE FROM login_attempts WHERE ip=?',(ip,));db.execute('INSERT INTO sessions VALUES(?,?,?)',(digest(token),csrf,stamp+12*3600))
 return {'token':token,'csrf':csrf},None

def digest(token):return hashlib.sha256(token.encode()).hexdigest()
def session(db,token):
 if not token:return None
 row=db.execute('SELECT * FROM sessions WHERE token_hash=? AND expires>?',(digest(token),time.time())).fetchone()
 return dict(row) if row else None
