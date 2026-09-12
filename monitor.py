import http.client
import json
import os
import re
import socket
import struct
import time
import psutil
from flask import abort, g, jsonify
from accounts import SERVER_PERMS,FILE_PERMS

class UnixHTTP(http.client.HTTPConnection):
    def __init__(self,path): super().__init__('localhost',timeout=8); self.path=path
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout); self.sock.connect(self.path)

class Docker:
    def __init__(self,path,names): self.path=path; self.names=set(names)
    def _request(self,method,path,limit=2*1024*1024):
        conn=UnixHTTP(self.path)
        try:
            conn.request(method,'/v1.41'+path)
            response=conn.getresponse(); data=response.read(limit+1)
            if response.status>=400 or len(data)>limit: raise OSError('Docker unavailable or response exceeds limit')
            return data
        finally: conn.close()
    def _name(self,name):
        if name not in self.names or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*',name): raise ValueError('Container denied')
        return name
    def inventory(self): return json.loads(self._request('GET','/containers/json?all=1'))
    def action(self,name,action):
        if action not in ('start','stop','restart'): raise ValueError('Action denied')
        self._request('POST',f'/containers/{self._name(name)}/{action}?t=20')
    def logs(self,name):
        data=self._request('GET',f'/containers/{self._name(name)}/logs?stdout=1&stderr=1&tail=200&timestamps=1',262144)
        chunks=[]
        while len(data)>=8 and data[0] in (0,1,2) and data[1:4]==b'\0\0\0':
            size=struct.unpack('>I',data[4:8])[0]
            if size>len(data)-8: break
            chunks.append(data[8:8+size]); data=data[8+size:]
        return (b''.join(chunks)+data).decode('utf-8',errors='replace')

def register_monitor(app,connect):
    app.extensions['docker']=Docker(app.config.get('DOCKER_SOCKET','/var/run/docker.sock'),[s['container'] for s in app.config['SERVERS'].values()])
    def allowed(server,permission):
        if server not in app.config['SERVERS']: abort(404)
        if app.config['SERVERS'][server].get('readonly'):
            return bool(g.user['admin'] and permission=='view')
        return bool(g.user['admin'] or json.loads(g.user['grants']).get(server,{}).get(permission,False))
    app.extensions['allowed']=allowed

    @app.get('/api/catalog')
    def catalog():
        user_grants=json.loads(g.user['grants'])
        servers={k:{'label':v.get('label',k),'readonly':v.get('readonly',False)} for k,v in app.config['SERVERS'].items() if g.user['admin'] or k in user_grants}
        roots={}
        for key,value in app.config['ROOTS'].items():
            folder_grants=user_grants.get(value['server'],{}).get('folders',{}).get(key,[])
            if value['server'] in servers and (g.user['admin'] or folder_grants):
                roots[key]={'server':value['server'],'label':value.get('label',key)}
        return jsonify(servers=servers,roots=roots,server_permissions=SERVER_PERMS,file_permissions=FILE_PERMS)

    @app.get('/api/overview')
    def overview():
        issues=[]; rows=[]
        try: containers=app.extensions['docker'].inventory()
        except (OSError,ValueError,http.client.HTTPException): containers=[]; issues.append('Docker connection unavailable; service status is unknown.')
        for key,config in app.config['SERVERS'].items():
            grant=json.loads(g.user['grants']).get(key,{})
            if not (g.user['admin'] or grant): continue
            # Visibility is independent: controls may be delegated without inventory disclosure.
            if not allowed(key,'view'): continue
            found=next((c for c in containers if '/'+config['container'] in c.get('Names',[]) or c.get('Id')==config['container']),None)
            state=found.get('State','unknown') if found else 'unknown'
            expected=config.get('expected','running'); status=found.get('Status','Not found / unavailable') if found else 'Not found / unavailable'
            if state!=expected or 'unhealthy' in status.lower(): issues.append(f"{config.get('label',key)}: {status}" if state!=expected else f"{config.get('label',key)}: unhealthy")
            rows.append({'id':key,'label':config.get('label',key),'state':state,'status':status,'expected':expected,'readonly':config.get('readonly',False),'permissions':{p:allowed(key,p) for p in SERVER_PERMS},'folders':{a:list(FILE_PERMS) if g.user['admin'] else grant.get('folders',{}).get(a,[]) for a,r in app.config['ROOTS'].items() if r['server']==key and (g.user['admin'] or a in grant.get('folders',{}))}})
        health=None
        if g.user['admin']:
            memory=psutil.virtual_memory(); disk=psutil.disk_usage('/'); net=psutil.net_io_counters(); io=psutil.disk_io_counters()
            health={'cpu_percent':psutil.cpu_percent(interval=0.15),'cpu_count':psutil.cpu_count(),'load':list(os.getloadavg()),'memory':{'total':memory.total,'used':memory.used,'percent':memory.percent,'available':memory.available},'disk':{'total':disk.total,'used':disk.used,'free':disk.free,'percent':disk.percent},'swap':psutil.swap_memory()._asdict(),'network':{'sent':net.bytes_sent,'received':net.bytes_recv},'io':{'read':io.read_bytes,'write':io.write_bytes} if io else None,'uptime':time.time()-psutil.boot_time()}
            if memory.percent>90: issues.append('Host memory utilization exceeds 90%.')
            if disk.percent>90: issues.append('Host root disk utilization exceeds 90%.')
        return jsonify(health=health,servers=rows,issues=issues,sampled_at=time.time())

    @app.route('/api/servers/<server>/<action>',methods=['GET','POST'])
    def service(server,action):
        from flask import request
        if action not in SERVER_PERMS or action=='view' or not allowed(server,action): abort(403)
        if (action=='logs')!=(request.method=='GET'): abort(405)
        name=app.config['SERVERS'][server]['container']
        try:
            if action=='logs':
                text=app.extensions['docker'].logs(name)
                with connect(app) as db: app.extensions['audit'](db,'server.logs',server)
                return jsonify(text=text)
            with connect(app) as db: app.extensions['audit'](db,'server.'+action+'.requested',server)
            app.extensions['docker'].action(name,action)
            with connect(app) as db: app.extensions['audit'](db,'server.'+action+'.accepted',server)
            return jsonify(ok=True)
        except (OSError,ValueError,http.client.HTTPException): return jsonify(error='Docker unavailable or operation failed'),502
