"""Local-only administration and deployment helpers; no HTTP bootstrap endpoint."""
import argparse
import json
import os
import re
import sqlite3
import stat
from pathlib import Path

from deployment import discovery_document,load_private_json,render_systemd_unit


def write_private(path, content):
    target=os.path.abspath(path)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try: os.unlink(target)
        except OSError: pass
        raise


def main(argv=None, inventory_loader=None):
    parser=argparse.ArgumentParser(description='Game Server Panel local administration')
    commands=parser.add_subparsers(dest='command',required=True)

    create=commands.add_parser('createadmin',help='create a local administrator')
    create.add_argument('--username',required=True)
    create.add_argument('--password-file',required=True)

    discover=commands.add_parser('discover',help='write sanitized local Docker inventory for review')
    discover.add_argument('--docker-socket',default='/var/run/docker.sock')
    discover.add_argument('--output',required=True)

    service=commands.add_parser('render-service',help='render a hardened systemd user unit from config')
    service.add_argument('--config',required=True)
    service.add_argument('--install-dir',default=str(Path(__file__).resolve().parent))
    service.add_argument('--output',required=True)

    args=parser.parse_args(argv)
    try:
        if args.command=='discover':
            if inventory_loader is None:
                from monitor import Docker
                inventory=Docker(args.docker_socket,()).inventory()
            else:
                inventory=inventory_loader(args.docker_socket)
            write_private(args.output,json.dumps(discovery_document(inventory),indent=2)+'\n')
            print(f'Sanitized discovery written to {os.path.abspath(args.output)}. Review it; no container or mount was authorized.')
            return

        if args.command=='render-service':
            config_path=os.path.abspath(args.config)
            config=load_private_json(config_path)
            rendered=render_systemd_unit(config,os.path.abspath(args.install_dir),config_path)
            write_private(args.output,rendered)
            print(f'Systemd unit written to {os.path.abspath(args.output)}. Review it before installation.')
            return

        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',args.username): raise ValueError('Invalid username')
        fd=os.open(args.password_file,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_mode & 0o077 or info.st_uid!=os.getuid(): raise ValueError('Password file must be owned by current user, regular, unlinked and mode 0600')
            password=stream.read(1026).rstrip('\n')
        if not 14<=len(password)<=1024: raise ValueError('Password length must be 14–1024 characters')
        from panel import create_app,create_admin
        create_admin(create_app(),args.username,password)
        print('Administrator created. Remove the password file after secure handoff.')
    except (OSError,ValueError,sqlite3.Error,json.JSONDecodeError):
        parser.exit(1,'Command failed; verify arguments, permissions and configuration.\n')


if __name__=='__main__': main()
