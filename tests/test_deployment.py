import json
import stat
import pytest
from pathlib import Path
from deployment import discovery_document,load_private_json,render_systemd_unit
from cli import main


def test_deployment_artifacts_are_present_and_private_by_default():
    requirements = Path('requirements.txt').read_text()
    assert 'Flask==' in requirements
    assert 'gunicorn==' in requirements
    assert 'psutil==' in requirements
    assert 'pytest' not in requirements.lower()

    development = Path('requirements-dev.txt').read_text()
    assert '-r requirements.txt' in development
    assert 'pytest==' in development
    assert 'playwright==' in development

    unit = Path('deploy/server-panel.service').read_text()
    assert '/opt/game-server-panel/config.json' in unit
    assert '--bind 127.0.0.1:9130' in unit
    assert '0.0.0.0' not in unit
    assert '/srv/game-server/mods' in unit
    assert 'ProtectSystem=strict' in unit
    assert 'NoNewPrivileges=true' in unit
    assert Path('LICENSE').read_text().startswith('MIT License')
    workflow=Path('.github/workflows/ci.yml').read_text()
    assert 'pytest -q' in workflow and 'playwright install --with-deps chromium' in workflow
    ignored=Path('.gitignore').read_text().splitlines()
    for private in ('config.json','state/','.env','docker-discovery*.json','admin-password*'):
        assert private in ignored


def test_example_configuration_is_generic_and_hardened():
    config=json.loads(Path('config.example.json').read_text())
    assert config['ALLOWED_ORIGIN']=='https://panel.example.com'
    assert config['DATABASE']=='/opt/game-server-panel/state/panel.db'
    assert set(config['SERVERS'])=={'game-server','metrics-sidecar'}
    assert config['SERVERS']['metrics-sidecar']['readonly'] is True
    assert set(config['ROOTS'])=={'game-data'}
    for root in config['ROOTS'].values():
        assert root['extensions']!= '*' and root['extensions']
        assert root['deny_paths']
    tracked='\n'.join(Path(path).read_text(errors='ignore') for path in [
        'README.md','API.md','config.example.json','deploy/server-panel.service','static/app.js','static/index.html'
    ])
    for private in ('personal.example.invalid','/home/alice','private-game-name','private-tunnel-name'):
        assert private not in tracked.lower()


def test_local_discovery_is_sanitized_and_does_not_auto_authorize_mounts():
    inventory=[{
        'Id':'a'*64,'Names':['/game-one'],'State':'running','Status':'Up 2 hours',
        'Image':'vendor/game:latest','Labels':{'secret':'do-not-leak'},'Ports':[{'PublicPort':1234}],
        'Mounts':[{'Type':'bind','Source':'/srv/game-one','Destination':'/data','RW':True},
                  {'Type':'volume','Name':'internal','Source':'/var/lib/docker/volumes/internal','Destination':'/cache','RW':True}],
    }]
    result=discovery_document(inventory)
    assert result=={'containers':[{'name':'game-one','state':'running','status':'Up 2 hours','bind_mounts':[{'source':'/srv/game-one','destination':'/data','writable':True}]}]}
    assert 'secret' not in json.dumps(result)
    assert 'SERVERS' not in result and 'ROOTS' not in result


def test_systemd_renderer_uses_only_reviewed_config_paths(tmp_path):
    install=tmp_path/'game-server-panel';install.mkdir()
    state=tmp_path/'state';root=tmp_path/'game data';root.mkdir()
    config={'ALLOWED_ORIGIN':'https://panel.example.com','DATABASE':str(state/'panel.db'),'BACKUP_DIR':str(state/'backups'),'SERVERS':{'game':{'container':'game'}},'ROOTS':{'data':{'server':'game','path':str(root),'deny_paths':['logs']}}}
    rendered=render_systemd_unit(config,str(install),str(tmp_path/'config.json'))
    assert f'WorkingDirectory={install}' in rendered
    assert f'Environment="PANEL_CONFIG={tmp_path / "config.json"}"' in rendered
    read_write=next(line for line in rendered.splitlines() if line.startswith('ReadWritePaths='))
    assert str(state) in read_write
    assert str(root).replace(' ','\\x20') in read_write
    assert '--bind 127.0.0.1:9130' in rendered
    assert '0.0.0.0' not in rendered


def test_systemd_renderer_escapes_percent_specifiers(tmp_path):
    state=tmp_path/'state';root=tmp_path/'mods';install=tmp_path/'install%n'
    state.mkdir();root.mkdir();install.mkdir()
    config={'ALLOWED_ORIGIN':'https://panel.example.com','DATABASE':str(state/'panel.db'),'BACKUP_DIR':str(state/'backups'),'SERVERS':{'game':{'container':'game'}},'ROOTS':{'mods':{'server':'game','path':str(root),'deny_paths':['logs']}}}
    rendered=render_systemd_unit(config,str(install),str(tmp_path/'config%n.json'))
    assert 'install%%n' in rendered
    assert 'config%%n.json' in rendered


def test_discover_cli_writes_private_review_only_inventory(tmp_path):
    output=tmp_path/'discovery.json'
    inventory=[{'Names':['/game'],'State':'running','Status':'Up','Mounts':[{'Type':'bind','Source':'/srv/game','Destination':'/data','RW':True}]}]
    main(['discover','--output',str(output)],inventory_loader=lambda socket: inventory)
    assert stat.S_IMODE(output.stat().st_mode)==0o600
    result=json.loads(output.read_text())
    assert result['containers'][0]['name']=='game'
    assert 'SERVERS' not in result and 'ROOTS' not in result


def test_private_config_loader_rejects_unsafe_files(tmp_path):
    target=tmp_path/'config.json';target.write_text('{"ok":true}')
    with pytest.raises(ValueError): load_private_json(str(target))
    target.chmod(0o600)
    assert load_private_json(str(target))=={'ok':True}
    link=tmp_path/'link.json';link.symlink_to(target)
    with pytest.raises(OSError): load_private_json(str(link))


def test_render_service_cli_requires_private_config(tmp_path):
    state=tmp_path/'state';root=tmp_path/'mods';install=tmp_path/'install'
    state.mkdir();root.mkdir();install.mkdir()
    config=tmp_path/'config.json';output=tmp_path/'panel.service'
    config.write_text(json.dumps({'ALLOWED_ORIGIN':'https://panel.example.com','DATABASE':str(state/'panel.db'),'BACKUP_DIR':str(state/'backups'),'SERVERS':{'game':{'container':'game'}},'ROOTS':{'mods':{'server':'game','path':str(root),'deny_paths':['logs']}}}))
    with pytest.raises(SystemExit): main(['render-service','--config',str(config),'--install-dir',str(install),'--output',str(output)])
    assert not output.exists()
    config.chmod(0o600)
    main(['render-service','--config',str(config),'--install-dir',str(install),'--output',str(output)])
    assert output.stat().st_mode&0o777==0o600
