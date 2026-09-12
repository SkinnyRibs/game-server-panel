import json
import re
import time
from flask import request, g, abort, jsonify
from werkzeug.security import generate_password_hash

SERVER_PERMS=('view','logs','start','stop','restart')
FILE_PERMS=('view','read','upload','edit','delete')

def register_accounts(app,connect):
    def admin():
        if not g.user['admin']: abort(403)

    def grants(value):
        if not isinstance(value,dict): abort(400)
        for server,grant in value.items():
            if server not in app.config['SERVERS'] or not isinstance(grant,dict): abort(400)
            if app.config['SERVERS'][server].get('readonly'): abort(400)
            if set(grant)-set(SERVER_PERMS)-{'folders'}: abort(400)
            if any(type(v) is not bool for k,v in grant.items() if k!='folders'): abort(400)
            folders=grant.get('folders',{})
            if not isinstance(folders,dict): abort(400)
            for alias,permissions in folders.items():
                if alias not in app.config['ROOTS'] or app.config['ROOTS'][alias]['server']!=server: abort(400)
                if not isinstance(permissions,list) or any(p not in FILE_PERMS for p in permissions): abort(400)
        return json.dumps(value)

    def audit(db,action,target):
        db.execute('INSERT INTO audit(at,actor,action,target) VALUES(?,?,?,?)',(time.time(),g.user['username'],action,str(target)))

    @app.route('/api/users',methods=['GET','POST'])
    def users():
        admin()
        if request.method=='GET':
            with connect(app) as db:
                return jsonify([dict(r)|{'grants':json.loads(r['grants'])} for r in db.execute('SELECT id,username,admin,disabled,grants FROM users ORDER BY id')])
        d=request.get_json(); username=d.get('username',''); password=d.get('password','')
        if not isinstance(username,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',username) or not isinstance(password,str) or not 14<=len(password)<=1024 or type(d.get('admin',False)) is not bool: abort(400)
        permissions=grants(d.get('grants',{}))
        import sqlite3
        try:
            with connect(app) as db:
                uid=db.execute('INSERT INTO users(username,password,admin,grants) VALUES(?,?,?,?)',(username,generate_password_hash(password),d.get('admin',False),permissions)).lastrowid
                audit(db,'user.create',uid)
        except sqlite3.IntegrityError: abort(409)
        return jsonify(id=uid),201

    @app.route('/api/users/<int:uid>',methods=['PATCH','DELETE'])
    def change_user(uid):
        admin(); d=request.get_json() if request.method=='PATCH' else {}
        if set(d)-{'disabled','admin','grants','password'}: abort(400)
        for key in ('admin','disabled'):
            if key in d and type(d[key]) is not bool: abort(400)
        if 'grants' in d: d['grants']=grants(d['grants'])
        if 'password' in d:
            if not isinstance(d['password'],str) or not 14<=len(d['password'])<=1024: abort(400)
            d['password']=generate_password_hash(d['password'])
        with connect(app) as db:
            db.execute('BEGIN IMMEDIATE')
            user=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            if not user: abort(404)
            if user['admin'] and not user['disabled'] and (request.method=='DELETE' or d.get('disabled') or d.get('admin') is False):
                if db.execute('SELECT count(*) FROM users WHERE admin=1 AND disabled=0').fetchone()[0]<=1: abort(409)
            if request.method=='DELETE': db.execute('DELETE FROM users WHERE id=?',(uid,))
            else:
                statements={
                    'disabled':'UPDATE users SET disabled=? WHERE id=?',
                    'admin':'UPDATE users SET admin=? WHERE id=?',
                    'grants':'UPDATE users SET grants=? WHERE id=?',
                    'password':'UPDATE users SET password=? WHERE id=?',
                }
                for key,value in d.items(): db.execute(statements[key],(value,uid))
                if d.get('disabled') or 'password' in d or 'admin' in d: db.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            audit(db,'user.delete' if request.method=='DELETE' else 'user.update',uid)
        return jsonify(ok=True)

    @app.get('/api/audit')
    def events():
        admin()
        with connect(app) as db: return jsonify([dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200')])
    app.extensions['audit']=audit
