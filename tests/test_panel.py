import importlib.util
import sqlite3
import pytest
import json


def test_login_secure_session(tmp_path):
    assert importlib.util.find_spec('panel'), 'panel application missing'
    from panel import create_app, create_admin
    app = create_app({'DATABASE':str(tmp_path/'db'), 'TESTING':True, 'ALLOWED_ORIGIN':None})
    create_admin(app, 'owner', 'test-only-password-123')
    c=app.test_client()
    assert c.get('/api/me').status_code == 401
    assert c.post('/api/login',json={'username':'owner','password':'wrong'}).status_code==401
    r=c.post('/api/login',json={'username':'owner','password':'test-only-password-123'})
    assert r.status_code==200
    assert all(x in r.headers['Set-Cookie'] for x in ['Secure','HttpOnly','SameSite=Strict'])
    assert c.get('/api/me').json['username']=='owner'
    db=sqlite3.connect(app.config['DATABASE'])
    assert c.get_cookie('panel_session').value not in str(db.execute('select * from sessions').fetchall())
    assert c.post('/api/logout').status_code==403
    assert c.post('/api/logout',headers={'X-CSRF-Token':r.json['csrf']}).status_code==200
    assert c.get('/api/me').status_code==401


def test_production_requires_explicit_safe_origin_before_database_creation(tmp_path):
    from panel import create_app
    database=tmp_path/'state'/'panel.db'
    with pytest.raises(ValueError,match='ALLOWED_ORIGIN'):
        create_app({'DATABASE':str(database)})
    assert not database.exists()
    with pytest.raises(ValueError,match='ALLOWED_ORIGIN'):
        create_app({'DATABASE':str(database),'ALLOWED_ORIGIN':'https://panel.example.com/path'})
    assert not database.exists()
    app=create_app({'DATABASE':str(database),'ALLOWED_ORIGIN':'https://panel.example.com'})
    assert app.config['ALLOWED_ORIGIN']=='https://panel.example.com'


def test_environment_config_must_be_private_before_database_creation(tmp_path,monkeypatch):
    from panel import create_app
    database=tmp_path/'state'/'panel.db';config_path=tmp_path/'config.json'
    config_path.write_text(json.dumps({'ALLOWED_ORIGIN':'https://panel.example.com','DATABASE':str(database),'SERVERS':{},'ROOTS':{}}))
    monkeypatch.setenv('PANEL_CONFIG',str(config_path))
    with pytest.raises(ValueError): create_app()
    assert not database.exists()
    config_path.chmod(0o600)
    assert create_app().config['DATABASE']==str(database)


@pytest.mark.parametrize('bad_config', ['nested','database','backup','database-in-backup','duplicate-container','unknown-server'])
def test_unsafe_resource_configuration_fails_before_database_creation(tmp_path,bad_config):
    from panel import create_app
    parent=tmp_path/'game'; child=parent/'mods'; child.mkdir(parents=True)
    database=tmp_path/'state'/'panel.db'; backup=tmp_path/'state'/'backups'
    servers={'one':{'container':'one'}}
    roots={'mods':{'server':'one','path':str(child)}}
    if bad_config=='nested': roots['game']={'server':'one','path':str(parent)}
    elif bad_config=='database': database=child/'panel.db'
    elif bad_config=='backup': backup=child/'backups'
    elif bad_config=='database-in-backup': database=backup/'panel.db'
    elif bad_config=='duplicate-container': servers['two']={'container':'one'}
    elif bad_config=='unknown-server': roots['mods']['server']='missing'
    with pytest.raises(ValueError):
        create_app({'DATABASE':str(database),'BACKUP_DIR':str(backup),'SERVERS':servers,'ROOTS':roots})
    assert not database.exists()


@pytest.mark.parametrize('deny_paths', [['/logs'],['../logs'],['logs/../private'],['logs',1],'logs'])
def test_invalid_sensitive_path_configuration_fails_before_database_creation(tmp_path,deny_paths):
    from panel import create_app
    root=tmp_path/'game';root.mkdir();database=tmp_path/'state'/'panel.db'
    with pytest.raises(ValueError):
        create_app({'DATABASE':str(database),'SERVERS':{'game':{'container':'game'}},'ROOTS':{'data':{'server':'game','path':str(root),'extensions':'*','deny_paths':deny_paths}}})
    assert not database.exists()
