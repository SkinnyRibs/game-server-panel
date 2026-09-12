import hashlib
import ipaddress
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit
from flask import Flask, request, g, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from deployment import load_private_json


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


from contextlib import contextmanager

@contextmanager
def connect(app):
    db=sqlite3.connect(app.config['DATABASE'], timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        with db: yield db
    finally:
        db.close()


def create_admin(app, username, password):
    if len(password)<14: raise ValueError('Password must have at least 14 characters')
    with connect(app) as db:
        db.execute('INSERT INTO users(username,password,admin) VALUES(?,?,1)',(username,generate_password_hash(password)))


def validate_config(config):
    origin=config.get('ALLOWED_ORIGIN')
    if origin is None:
        if not config.get('TESTING'): raise ValueError('ALLOWED_ORIGIN is required outside tests')
    elif not isinstance(origin,str): raise ValueError('Invalid ALLOWED_ORIGIN')
    else:
        parsed=urlsplit(origin)
        loopback=parsed.hostname in ('localhost','127.0.0.1','::1')
        if not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or parsed.scheme not in (('http','https') if loopback else ('https',)) or origin!=f'{parsed.scheme}://{parsed.netloc}':
            raise ValueError('ALLOWED_ORIGIN must be an exact HTTPS origin (HTTP is allowed only for loopback)')
    servers=config.get('SERVERS')
    roots=config.get('ROOTS')
    if not isinstance(servers,dict) or not isinstance(roots,dict): raise ValueError('SERVERS and ROOTS must be objects')
    containers=[]
    for server,value in servers.items():
        if not isinstance(server,str) or not isinstance(value,dict) or not isinstance(value.get('container'),str): raise ValueError('Invalid server configuration')
        containers.append(value['container'])
    if len(containers)!=len(set(containers)): raise ValueError('Container targets must be unique')

    def canonical(value):
        if not isinstance(value,str) or not os.path.isabs(value): raise ValueError('Resource paths must be absolute')
        return os.path.realpath(value)
    def overlaps(left,right):
        try: common=os.path.commonpath((left,right))
        except ValueError: return False
        return common in (left,right)

    database=canonical(config['DATABASE'])
    backup=canonical(config['BACKUP_DIR'])
    if overlaps(database,backup): raise ValueError('Database and backup paths must be disjoint')
    paths=[]
    for alias,value in roots.items():
        if not isinstance(alias,str) or not isinstance(value,dict) or value.get('server') not in servers: raise ValueError('Invalid root server mapping')
        extensions=value.get('extensions')
        if extensions is not None and extensions!='*' and (not isinstance(extensions,list) or not extensions or any(not isinstance(item,str) or not item.startswith('.') or '/' in item or '\\' in item for item in extensions)): raise ValueError('Invalid root extension policy')
        deny_paths=value.get('deny_paths',[])
        if not isinstance(deny_paths,list): raise ValueError('Invalid root deny paths')
        for denied in deny_paths:
            if not isinstance(denied,str) or denied.startswith('/') or '\\' in denied or len(denied)>1024: raise ValueError('Invalid root deny path')
            components=denied.split('/')
            if not components or any(not component or component in ('.','..') or any(ord(char)<32 or ord(char)==127 for char in component) for component in components): raise ValueError('Invalid root deny path')
        root=canonical(value.get('path'))
        for other in paths:
            if overlaps(root,other): raise ValueError('Approved roots must be disjoint')
        if overlaps(root,database) or overlaps(root,backup): raise ValueError('State paths must be outside approved roots')
        paths.append(root)


def create_app(config=None):
    app=Flask(__name__,static_folder='static')
    app.config.update(DATABASE=os.environ.get('PANEL_DATABASE',str(Path(__file__).parent/'state/panel.db')), MAX_CONTENT_LENGTH=8*1024*1024, ALLOWED_ORIGIN=os.environ.get('PANEL_ORIGIN'), TRUSTED_PROXY_NETWORKS=(), SERVERS={}, ROOTS={})
    if os.environ.get('PANEL_CONFIG'):
        app.config.update(load_private_json(os.environ['PANEL_CONFIG']))
    app.config.update(config or {})
    app.config.setdefault('BACKUP_DIR',os.path.join(os.path.dirname(app.config['DATABASE']),'backups'))
    validate_config(app.config)
    Path(app.config['DATABASE']).parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with connect(app) as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE NOT NULL,password TEXT NOT NULL,admin INTEGER NOT NULL DEFAULT 0,disabled INTEGER NOT NULL DEFAULT 0,grants TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,csrf TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY,count INTEGER,expires REAL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at REAL,actor TEXT,action TEXT,target TEXT);
        ''')
    os.chmod(app.config['DATABASE'],0o600)

    @app.before_request
    def authenticate():
        g.user=None
        if request.method in ('POST','PATCH') and (request.path in ('/api/login','/api/users','/api/password') or request.path.startswith('/api/users/')):
            if not request.is_json or not isinstance(request.get_json(),dict): abort(400)
        if request.method not in ('GET','HEAD','OPTIONS') and app.config.get('ALLOWED_ORIGIN') and request.headers.get('Origin')!=app.config['ALLOWED_ORIGIN']: abort(403)
        if request.path.startswith('/api/') and request.path!='/api/login':
            with connect(app) as db:
                row=db.execute('SELECT users.*, sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE token=? AND expires>? AND disabled=0',(digest(request.cookies.get('panel_session','')),time.time())).fetchone()
            if row is None: abort(401)
            g.user=dict(row)
            if request.method not in ('GET','HEAD','OPTIONS') and not secrets.compare_digest(request.headers.get('X-CSRF-Token',''),row['csrf']): abort(403)

    @app.after_request
    def security(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",'Strict-Transport-Security':'max-age=31536000','X-Frame-Options':'DENY'})
        return response

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def error(e): return jsonify(error=e.name),e.code

    @app.post('/api/login')
    def login():
        if not request.is_json: abort(400)
        data=request.get_json(); username=data.get('username',''); password=data.get('password','')
        if not isinstance(username,str) or not isinstance(password,str) or len(username)>64 or len(password)>1024: abort(400)
        try: peer=ipaddress.ip_address(request.remote_addr or '')
        except ValueError: peer=None
        client=peer
        if peer is not None:
            for network in app.config.get('TRUSTED_PROXY_NETWORKS',()):
                try: trusted=peer in ipaddress.ip_network(network)
                except ValueError: trusted=False
                if trusted:
                    try: client=ipaddress.ip_address(request.headers.get('CF-Connecting-IP',''))
                    except ValueError: pass
                    break
        key=digest(str(client or 'unknown'))
        with connect(app) as db:
            row=db.execute('SELECT count FROM attempts WHERE key=? AND expires>?',(key,time.time())).fetchone()
            if row and row['count']>=10: abort(429)
            user=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        valid=check_password_hash(user['password'] if user else app.config['DUMMY_HASH'],password)
        if not valid or not user or user['disabled']:
            now=time.time()
            with connect(app) as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('DELETE FROM attempts WHERE expires<?',(now,))
                db.execute('INSERT INTO attempts VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1,expires=?',(key,now+900,now+900))
            abort(401)
        with connect(app) as db:
            db.execute('DELETE FROM attempts WHERE key=?',(key,))
            token=secrets.token_urlsafe(48); csrf=secrets.token_urlsafe(32)
            db.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),user['id'],csrf,time.time()+43200))
            db.execute('INSERT INTO audit(at,actor,action,target) VALUES(?,?,?,?)',(time.time(),username,'login',username))
        response=jsonify(csrf=csrf)
        response.set_cookie('panel_session',token,max_age=43200,secure=True,httponly=True,samesite='Strict',path='/')
        return response

    @app.get('/')
    def index(): return app.send_static_file('index.html')

    @app.get('/api/me')
    def me(): return jsonify({k:g.user[k] for k in ('id','username','admin','csrf')} | {'grants':json.loads(g.user['grants'])})

    @app.post('/api/password')
    def password_change():
        data=request.get_json()
        current=data.get('current_password',''); password=data.get('password','')
        if not isinstance(current,str) or not isinstance(password,str) or not 14<=len(password)<=1024 or len(current)>1024: abort(400)
        if not check_password_hash(g.user['password'],current): abort(403)
        with connect(app) as db:
            db.execute('UPDATE users SET password=? WHERE id=?',(generate_password_hash(password),g.user['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?',(g.user['id'],))
            app.extensions['audit'](db,'password.change',g.user['id'])
        response=jsonify(ok=True); response.delete_cookie('panel_session',secure=True,httponly=True,samesite='Strict'); return response

    @app.post('/api/logout')
    def logout():
        with connect(app) as db: db.execute('DELETE FROM sessions WHERE token=?',(digest(request.cookies.get('panel_session','')),))
        response=jsonify(ok=True); response.delete_cookie('panel_session',secure=True,httponly=True,samesite='Strict'); return response

    from accounts import register_accounts
    register_accounts(app,connect)
    from monitor import register_monitor
    register_monitor(app,connect)
    from files import register_files
    register_files(app,connect)
    app.config['DUMMY_HASH']=generate_password_hash(secrets.token_urlsafe(32))
    return app
