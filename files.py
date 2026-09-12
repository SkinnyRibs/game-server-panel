"""Descriptor-relative file access. Never resolve user paths via pathlib."""
import contextlib
import errno
import fcntl
import json
import os
import secrets
import stat
from flask import abort, g, request, jsonify, Response

FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
DENY=('secret','password','credential','token','private','rcon','server.properties','gameusersettings','game.ini','palworldsettings','key.pem','ops.json','whitelist','banned-','usercache')
DENY_EXACT={'backup','backups','log','logs','crash-reports','permissions.yml','key.pem','environment','crontab','running-instances','arkmanager'}
EXTENSIONS={'.txt','.json','.yaml','.yml','.toml','.cfg','.ini','.jar','.pak','.zip','.mod','.md','.js','.snbt'}
LIMIT=8*1024*1024


def parts(path,empty=False):
    if not isinstance(path,str) or '\x00' in path or '\\' in path or path.startswith('/') or len(path)>1024: raise PermissionError()
    result=path.split('/') if path else []
    if (not result and not empty) or any(not x or x in ('.','..') or x.startswith('.') or x.casefold() in DENY_EXACT or any(ord(c)<32 or ord(c)==127 for c in x) or any(t in x.lower() for t in DENY) for x in result): raise PermissionError()
    return result

@contextlib.contextmanager
def directory(root,segments=()):
    if not os.path.isabs(root): raise PermissionError()
    fd=os.open('/',FLAGS)
    try:
        for component in root.split('/')[1:]+list(segments):
            if not component or component in ('.','..'): raise PermissionError()
            child=os.open(component,FLAGS,dir_fd=fd); os.close(fd); fd=child
        yield fd
    finally: os.close(fd)


def regular(fd,denied=()):
    s=os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise PermissionError()
    if (s.st_dev,s.st_ino) in denied: raise PermissionError()
    if s.st_size>LIMIT: raise OverflowError()
    return s


def read_file_at(parent,name,denied=()):
    fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=parent)
    try:
        regular(fd,denied)
        chunks=[];total=0
        while True:
            data=os.read(fd,65536)
            if not data: break
            total+=len(data)
            if total>LIMIT: raise OverflowError()
            chunks.append(data)
        regular(fd,denied)
        return b''.join(chunks)
    finally: os.close(fd)


def write_at(parent,name,data,mode=0o600):
    fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
    try:
        with os.fdopen(fd,'wb',closefd=False) as f: f.write(data); f.flush(); os.fchmod(fd,mode & 0o666); os.fsync(fd)
    finally: os.close(fd)


def register_files(app,connect):
    def protected_inodes():
        result=set()
        try:
            info=os.stat(app.config['DATABASE'])
            result.add((info.st_dev,info.st_ino))
        except FileNotFoundError: pass
        backup=app.config['BACKUP_DIR']
        try:
            with os.scandir(backup) as entries:
                for entry in entries:
                    try:
                        info=entry.stat()
                        if stat.S_ISREG(info.st_mode): result.add((info.st_dev,info.st_ino))
                    except OSError: pass
        except FileNotFoundError: pass
        return result

    @app.route('/api/files/<alias>/<operation>',methods=['GET','PUT','PATCH','DELETE'])
    def files(alias,operation):
        root=app.config['ROOTS'].get(alias)
        if root is None: abort(404)
        if operation=='list':
            if request.method!='GET': abort(405)
            permission='view'
        elif operation=='content':
            permission={'GET':'read','HEAD':'read','PUT':'upload','PATCH':'edit','DELETE':'delete'}.get(request.method)
            if permission is None: abort(405)
        elif operation=='directory':
            permission={'PUT':'upload','DELETE':'delete'}.get(request.method)
            if permission is None: abort(405)
        else: abort(405)
        if not g.user['admin'] and permission not in json.loads(g.user['grants']).get(root['server'],{}).get('folders',{}).get(alias,[]): abort(403)
        path=request.args.get('path','')
        try:
            components=parts(path,empty=operation=='list')
            denied=protected_inodes()
            denied_prefixes=[]
            for configured in root.get('deny_paths',()):
                if not isinstance(configured,str) or configured.startswith('/') or '\\' in configured: raise PermissionError()
                denied_prefixes.append(tuple(component.casefold() for component in configured.split('/') if component))
            def denied_path(candidate):
                lowered=tuple(component.casefold() for component in candidate)
                return any(prefix and lowered[:len(prefix)]==prefix for prefix in denied_prefixes)
            if denied_path(components): raise PermissionError()
            extensions=root.get('extensions',EXTENSIONS)
            allow_all=extensions=='*'
            allowed_ext=set() if allow_all else set(extensions)
            def safe_name(name):
                parts(name)
                if not allow_all and os.path.splitext(name)[1].lower() not in allowed_ext: raise PermissionError()
            if operation=='list':
                with directory(root['path'],components) as parent:
                    entries=[]
                    for name in sorted(os.listdir(parent)):
                        try:
                            parts(name)
                            if denied_path(components+[name]): raise PermissionError()
                            info=os.stat(name,dir_fd=parent,follow_symlinks=False)
                            isdir=stat.S_ISDIR(info.st_mode)
                            if not isdir:
                                safe_name(name)
                                if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or (info.st_dev,info.st_ino) in denied: continue
                            entries.append({'name':name,'directory':isdir,'size':info.st_size,'modified':info.st_mtime})
                        except (OSError,ValueError): continue
                        if len(entries)>=2000: break
                return jsonify(entries=entries,path=path,limit=2000)
            if operation=='directory':
                with directory(root['path'],components[:-1]) as parent:
                    fcntl.flock(parent,fcntl.LOCK_EX)
                    name=components[-1]
                    if request.method=='PUT':
                        os.mkdir(name,root.get('directory_mode',0o700) & 0o777,dir_fd=parent)
                        action='folder.create'; status_code=201
                    else:
                        info=os.stat(name,dir_fd=parent,follow_symlinks=False)
                        if not stat.S_ISDIR(info.st_mode): raise PermissionError()
                        try: os.rmdir(name,dir_fd=parent)
                        except OSError as error:
                            if error.errno in (errno.ENOTEMPTY,errno.EEXIST): abort(409)
                            raise
                        action='folder.delete'; status_code=200
                    os.fsync(parent)
                with connect(app) as db: app.extensions['audit'](db,action,alias+'/'+path)
                return jsonify(ok=True),status_code
            safe_name(components[-1])
            with directory(root['path'],components[:-1]) as parent:
                name=components[-1]
                if request.method in ('GET','HEAD'):
                    data=read_file_at(parent,name,denied)
                    with connect(app) as db: app.extensions['audit'](db,'file.read',alias+'/'+path)
                    if request.args.get('text')=='1':
                        if len(data)>1024*1024 or b'\x00' in data: abort(413)
                        try: text=data.decode('utf-8')
                        except UnicodeDecodeError: abort(400)
                        return jsonify(text=text)
                    response=Response(data,mimetype='application/octet-stream')
                    response.headers.set('Content-Disposition','attachment',filename=name)
                    return response
                fcntl.flock(parent,fcntl.LOCK_EX)
                if request.method=='PUT':
                    write_at(parent,name,request.get_data(),root.get('file_mode',0o600))
                else:
                    original=read_file_at(parent,name,denied)
                    original_mode=os.stat(name,dir_fd=parent,follow_symlinks=False).st_mode & 0o666
                    if request.method=='PATCH':
                        if len(original)>1024*1024: abort(413)
                        if b'\x00' in original: abort(400)
                        try: original.decode('utf-8')
                        except UnicodeDecodeError: abort(400)
                    backup=app.config.get('BACKUP_DIR',os.path.join(os.path.dirname(app.config['DATABASE']),'backups'))
                    # Backup directory is trusted local config, never a grant target.
                    if os.path.commonpath([os.path.abspath(backup),os.path.abspath(root['path'])])==os.path.abspath(root['path']): raise PermissionError()
                    os.makedirs(backup,mode=0o700,exist_ok=True)
                    backup_name=secrets.token_hex(24)+'.bak'
                    with directory(backup) as backup_fd: write_at(backup_fd,backup_name,original)
                    with connect(app) as db: app.extensions['audit'](db,'file.backup',alias+'/'+path+' -> '+backup_name)
                    if request.method=='DELETE': os.unlink(name,dir_fd=parent)
                    else:
                        data=request.get_data()
                        if len(data)>1024*1024 or b'\x00' in data: abort(413)
                        try: data.decode('utf-8')
                        except UnicodeDecodeError: abort(400)
                        temporary='.panel-'+secrets.token_hex(16)
                        try:
                            write_at(parent,temporary,data,original_mode)
                            os.replace(temporary,name,src_dir_fd=parent,dst_dir_fd=parent)
                        finally:
                            try: os.unlink(temporary,dir_fd=parent)
                            except FileNotFoundError: pass
                os.fsync(parent)
                with connect(app) as db: app.extensions['audit'](db,'file.'+permission,alias+'/'+path)
                return jsonify(ok=True),201 if request.method=='PUT' else 200
        except FileExistsError: abort(409)
        except FileNotFoundError: abort(404)
        except OverflowError: abort(413)
        except OSError as e:
            if e.errno in (errno.ELOOP,errno.ENOTDIR,errno.EACCES,errno.EPERM) or isinstance(e,PermissionError): abort(403)
            return jsonify(error='File operation unavailable'),503
