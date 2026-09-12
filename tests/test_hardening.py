from test_accounts import setup
import pytest

@pytest.mark.parametrize('path', ['/api/login','/api/users','/api/password','/api/users/1'])
@pytest.mark.parametrize('payload', [[],None,'string',42])
def test_malformed_json_is_rejected(setup,path,payload):
    _,c,h=setup
    method='PATCH' if path=='/api/users/1' else 'POST'
    r=c.open(path,method=method,json=payload,headers=h)
    assert r.status_code in (400,415)
    assert r.is_json

def test_file_size_and_root_symlink(setup,tmp_path):
    app,c,h=setup
    (tmp_path/'mods').mkdir()
    (tmp_path/'mods'/'large.txt').write_bytes(b'x'*(1024*1024+1))
    assert c.get('/api/files/mods/content?path=large.txt&text=1').status_code==413
    assert c.put('/api/files/mods/content?path=too-large.jar',data=b'x'*(8*1024*1024+1),headers=h).status_code==413
    assert not (tmp_path/'mods'/'too-large.jar').exists()
    (tmp_path/'link').symlink_to(tmp_path/'mods',target_is_directory=True)
    app.config['ROOTS']['mods']['path']=str(tmp_path/'link')
    assert c.get('/api/files/mods/list').status_code==403

def test_readonly_containers_even_for_admin(setup):
    app,c,h=setup
    app.config['SERVERS']['infra']={'container':'infra','readonly':True}
    for action in ['start','stop','restart']:
        assert c.post('/api/servers/infra/'+action,headers=h).status_code==403
    assert c.get('/api/servers/infra/logs').status_code==403


def test_control_characters_in_file_paths_are_rejected(setup,tmp_path):
    app,c,_=setup
    root=tmp_path/'mods'; root.mkdir()
    app.config['ROOTS']['mods']['path']=str(root)
    (root/'line\nbreak.txt').write_text('data')
    response=c.get('/api/files/mods/content',query_string={'path':'line\nbreak.txt'})
    assert response.status_code==403
    assert response.is_json


def test_live_database_inode_is_denied_after_local_relocation(setup,tmp_path):
    app,c,_=setup
    root=tmp_path/'mods'; root.mkdir()
    app.config['ROOTS']['mods'].update(path=str(root),extensions=['.db'])
    database=tmp_path/'db'; relocated=root/'leak.db'
    database.rename(relocated); database.symlink_to(relocated)
    response=c.get('/api/files/mods/content',query_string={'path':'leak.db'})
    assert response.status_code==403
    assert response.is_json


def test_retained_backup_inode_is_denied_after_local_relocation(setup,tmp_path):
    app,c,_=setup
    root=tmp_path/'mods'; root.mkdir(); app.config['ROOTS']['mods']['path']=str(root)
    backup=tmp_path/'backups'; backup.mkdir(); app.config['BACKUP_DIR']=str(backup)
    original=backup/'retained.bak'; original.write_text('private backup')
    relocated=root/'leak.txt'; original.rename(relocated); original.symlink_to(relocated)
    listing=c.get('/api/files/mods/list')
    assert listing.status_code==200
    assert 'leak.txt' not in [entry['name'] for entry in listing.json['entries']]
    response=c.get('/api/files/mods/content',query_string={'path':'leak.txt'})
    assert response.status_code==403
    assert response.is_json


def test_head_file_request_uses_read_permission_without_error(setup,tmp_path):
    app,c,_=setup
    root=tmp_path/'mods'; root.mkdir(); (root/'safe.txt').write_text('safe')
    app.config['ROOTS']['mods']['path']=str(root)
    response=c.head('/api/files/mods/content',query_string={'path':'safe.txt'})
    assert response.status_code==200
    assert response.data==b''
