import os
from test_accounts import setup

def test_files_safe_crud(setup,tmp_path):
    app,c,h=setup
    root=tmp_path/'mods';root.mkdir()
    app.config['BACKUP_DIR']=str(tmp_path/'backups')
    assert c.put('/api/files/mods/content?path=sample.txt',data=b'first',headers=h).status_code==201
    assert c.get('/api/files/mods/list').json['entries'][0]['name']=='sample.txt'
    assert c.get('/api/files/mods/content?path=sample.txt').data==b'first'
    assert c.patch('/api/files/mods/content?path=sample.txt',data=b'second',headers=h).status_code==200
    assert c.delete('/api/files/mods/content?path=sample.txt',headers=h).status_code==200
    assert sorted(p.read_bytes() for p in (tmp_path/'backups').iterdir())==[b'first',b'second']
    (root/'ok.txt').write_text('safe'); (root/'link').symlink_to(tmp_path,target_is_directory=True)
    os.link(root/'ok.txt',root/'hard.txt')
    (root/'.env').write_text('secret'); (root/'server.properties').write_text('secret')
    for path in ['../db','/etc/passwd','link/db','hard.txt','.env','server.properties','a/../ok.txt']:
        assert c.get('/api/files/mods/content',query_string={'path':path}).status_code==403
    assert c.put('/api/files/mods/content?path=link/new',data=b'bad',headers=h).status_code==403
    assert c.get('/api/files/unknown/list').status_code==404
    assert c.get('/api/files/mods/list').json['entries']==[]

def test_files_permissions_independent(setup,tmp_path):
    app,c,h=setup; root=tmp_path/'mods';root.mkdir(); (root/'x.txt').write_text('x')
    app.config['BACKUP_DIR']=str(tmp_path/'backups')
    d={'username':'u','password':'test-password-files','grants':{'game':{'folders':{'mods':['upload']}}}}
    c.post('/api/users',json=d,headers=h)
    guest=app.test_client(); r=guest.post('/api/login',json={'username':'u','password':d['password']}); gh={'X-CSRF-Token':r.json['csrf']}
    assert guest.get('/api/files/mods/list').status_code==403
    assert guest.get('/api/files/mods/content?path=x.txt').status_code==403
    assert guest.put('/api/files/mods/content?path=new.jar',data=b'new',headers=gh).status_code==201
    assert guest.put('/api/files/mods/content?path=x.txt',data=b'overwrite',headers=gh).status_code==409
    assert guest.patch('/api/files/mods/content?path=x.txt',data=b'edit',headers=gh).status_code==403
    assert guest.delete('/api/files/mods/content?path=x.txt',headers=gh).status_code==403


def test_upload_permission_can_create_folder_and_upload_inside_it(setup,tmp_path):
    app,c,h=setup
    root=tmp_path/'mods';root.mkdir()
    assert c.put('/api/files/mods/directory?path=NewMod',headers=h).status_code==201
    assert (root/'NewMod').is_dir()
    assert c.put('/api/files/mods/content?path=NewMod/mod.jar',data=b'mod',headers=h).status_code==201
    assert (root/'NewMod'/'mod.jar').read_bytes()==b'mod'
    assert c.put('/api/files/mods/directory?path=NewMod',headers=h).status_code==409
    for path in ('../escape','.hidden','server.properties','nested/../../escape'):
        assert c.put('/api/files/mods/directory',query_string={'path':path},headers=h).status_code==403


def test_delete_permission_removes_only_empty_folders(setup,tmp_path):
    app,c,h=setup
    root=tmp_path/'mods';root.mkdir();(root/'empty').mkdir();(root/'used').mkdir();(root/'used'/'mod.jar').write_bytes(b'mod')
    assert c.delete('/api/files/mods/directory?path=empty',headers=h).status_code==200
    assert not (root/'empty').exists()
    assert c.delete('/api/files/mods/directory?path=used',headers=h).status_code==409
    assert (root/'used'/'mod.jar').read_bytes()==b'mod'
    assert c.delete('/api/files/mods/directory?path=',headers=h).status_code==403
    outside=tmp_path/'outside';outside.mkdir();(root/'linked').symlink_to(outside,target_is_directory=True)
    assert c.delete('/api/files/mods/directory?path=linked',headers=h).status_code==403
    assert outside.is_dir()


def test_folder_create_and_delete_follow_independent_permissions(setup,tmp_path):
    app,c,h=setup
    root=tmp_path/'mods';root.mkdir();(root/'removable').mkdir()
    upload={'username':'uploader','password':'test-password-upload','grants':{'game':{'folders':{'mods':['upload']}}}}
    delete={'username':'deleter','password':'test-password-delete','grants':{'game':{'folders':{'mods':['delete']}}}}
    assert c.post('/api/users',json=upload,headers=h).status_code==201
    assert c.post('/api/users',json=delete,headers=h).status_code==201
    uploader=app.test_client();login=uploader.post('/api/login',json={'username':upload['username'],'password':upload['password']});uh={'X-CSRF-Token':login.json['csrf']}
    assert uploader.put('/api/files/mods/directory?path=created',headers=uh).status_code==201
    assert uploader.delete('/api/files/mods/directory?path=created',headers=uh).status_code==403
    deleter=app.test_client();login=deleter.post('/api/login',json={'username':delete['username'],'password':delete['password']});dh={'X-CSRF-Token':login.json['csrf']}
    assert deleter.put('/api/files/mods/directory?path=blocked',headers=dh).status_code==403
    assert deleter.delete('/api/files/mods/directory?path=removable',headers=dh).status_code==200


def test_full_root_lists_all_extensions_but_hides_sensitive_paths(setup,tmp_path):
    app,c,h=setup
    root=tmp_path/'data';root.mkdir();(root/'asset.uasset').write_bytes(b'asset');(root/'README').write_text('readme')
    (root/'logs').mkdir();(root/'logs'/'latest.txt').write_text('sensitive log')
    (root/'PalWorldSettings.ini').write_text('AdminPassword=secret')
    (root/'permissions.yml').write_text('sensitive permissions')
    (root/'saves'/'backup').mkdir(parents=True);(root/'saves'/'backup'/'world.ark').write_bytes(b'world')
    (root/'allowed').mkdir();(root/'allowed'/'original.txt').write_text('safe')
    (root/'allowed'/'link.txt').symlink_to(root/'README');os.link(root/'allowed'/'original.txt',root/'allowed'/'hard.txt')
    app.config['ROOTS']['mods'].update(path=str(root),extensions='*',deny_paths=['logs'])
    listing=c.get('/api/files/mods/list')
    assert listing.status_code==200
    assert [entry['name'] for entry in listing.json['entries']]==['README','allowed','asset.uasset','saves']
    assert c.get('/api/files/mods/content?path=README').data==b'readme'
    assert c.get('/api/files/mods/list?path=logs').status_code==403
    assert c.get('/api/files/mods/content?path=logs/latest.txt').status_code==403
    assert c.put('/api/files/mods/content?path=logs/new.txt',data=b'blocked',headers=h).status_code==403
    assert c.patch('/api/files/mods/content?path=logs/latest.txt',data=b'blocked',headers=h).status_code==403
    assert c.delete('/api/files/mods/content?path=logs/latest.txt',headers=h).status_code==403
    assert c.put('/api/files/mods/directory?path=logs/new-folder',headers=h).status_code==403
    assert c.delete('/api/files/mods/directory?path=logs',headers=h).status_code==403
    assert c.get('/api/files/mods/content?path=PalWorldSettings.ini').status_code==403
    assert c.get('/api/files/mods/content?path=permissions.yml').status_code==403
    assert c.get('/api/files/mods/list?path=saves').json['entries']==[]
    assert c.get('/api/files/mods/content?path=saves/backup/world.ark').status_code==403
    assert c.get('/api/files/mods/content?path=allowed/link.txt').status_code==403
    assert c.get('/api/files/mods/content?path=allowed/hard.txt').status_code==403
