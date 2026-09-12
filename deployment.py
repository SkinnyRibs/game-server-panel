"""Local deployment helpers. Nothing in this module is exposed over HTTP."""
from __future__ import annotations

import os
import json
import stat
from pathlib import Path


def _plain(value, limit=256):
    if not isinstance(value, str):
        return ''
    return ''.join(char for char in value if ord(char) >= 32 and ord(char) != 127)[:limit]


def load_private_json(path, limit=1024*1024):
    """Read an owner-only regular JSON file without following symlinks."""
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        metadata=os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink!=1 or metadata.st_uid!=os.getuid() or metadata.st_mode&0o077:
            raise ValueError('Configuration file must be owner-only, regular, singly linked, and owned by the current user')
        chunks=[];size=0
        while True:
            chunk=os.read(descriptor,min(65536,limit+1-size))
            if not chunk: break
            chunks.append(chunk);size+=len(chunk)
            if size>limit: raise ValueError('Configuration file is too large')
    finally:
        os.close(descriptor)
    value=json.loads(b''.join(chunks))
    if not isinstance(value,dict): raise ValueError('Configuration must be a JSON object')
    return value


def discovery_document(inventory):
    """Return only container names/state and bind-mount paths for local review."""
    containers=[]
    for item in inventory if isinstance(inventory, list) else []:
        names=item.get('Names', []) if isinstance(item, dict) else []
        name=next((_plain(value).lstrip('/') for value in names if _plain(value).lstrip('/')), '')
        if not name:
            continue
        mounts=[]
        for mount in item.get('Mounts', []):
            if not isinstance(mount, dict) or mount.get('Type') != 'bind':
                continue
            source=_plain(mount.get('Source', ''), 4096)
            destination=_plain(mount.get('Destination', ''), 4096)
            if not os.path.isabs(source) or not os.path.isabs(destination):
                continue
            mounts.append({'source':source,'destination':destination,'writable':bool(mount.get('RW', False))})
        mounts.sort(key=lambda value:(value['source'],value['destination']))
        containers.append({'name':name,'state':_plain(item.get('State', 'unknown')) or 'unknown','status':_plain(item.get('Status', 'unknown')) or 'unknown','bind_mounts':mounts})
    containers.sort(key=lambda value:value['name'])
    return {'containers':containers}


def _unit_string(value):
    if not isinstance(value, str) or any(ord(char)<32 or ord(char)==127 for char in value):
        raise ValueError('Systemd values must contain no control characters')
    return '"'+value.replace('%','%%').replace('\\','\\\\').replace('"','\\"')+'"'


def _unit_path(value):
    if not isinstance(value, str) or not os.path.isabs(value):
        raise ValueError('Systemd paths must be absolute')
    if any(ord(char)<32 or ord(char)==127 for char in value):
        raise ValueError('Systemd paths must contain no control characters')
    safe=b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/._:-'
    return ''.join('%%' if byte==37 else chr(byte) if byte in safe else f'\\x{byte:02x}' for byte in value.encode())


def _minimal_paths(paths):
    result=[]
    for value in sorted({os.path.realpath(path) for path in paths},key=lambda path:(len(Path(path).parts),path)):
        if not any(os.path.commonpath((value,parent))==parent for parent in result):
            result.append(value)
    return result


def render_systemd_unit(config, install_dir, config_path):
    """Render a hardened user unit from an already reviewed panel config."""
    from panel import validate_config
    validate_config(config)
    install=os.path.realpath(install_dir)
    config_file=os.path.realpath(config_path)
    state_dir=os.path.dirname(os.path.realpath(config['DATABASE']))
    writable=_minimal_paths([state_dir,os.path.realpath(config['BACKUP_DIR']),*(root['path'] for root in config['ROOTS'].values())])
    paths=' '.join(_unit_path(path) for path in writable)
    executable=os.path.join(install,'.venv','bin','gunicorn')
    gunicorn_config=os.path.join(install,'gunicorn.conf.py')
    return f'''[Unit]\nDescription=Game Server Panel\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nType=simple\nWorkingDirectory={_unit_path(install)}\nEnvironment={_unit_string('PANEL_CONFIG='+config_file)}\nExecStart={_unit_path(executable)} --config {_unit_path(gunicorn_config)} --bind 127.0.0.1:9130 panel:create_app()\nRestart=on-failure\nRestartSec=5\nUMask=0077\nNoNewPrivileges=true\nPrivateTmp=true\nProtectSystem=strict\nProtectHome=read-only\nProtectKernelTunables=true\nProtectControlGroups=true\nLockPersonality=true\nRestrictRealtime=true\nRestrictSUIDSGID=true\nSystemCallArchitectures=native\nRestrictAddressFamilies=AF_UNIX AF_INET AF_INET6\nReadWritePaths={paths}\n\n[Install]\nWantedBy=default.target\n'''
