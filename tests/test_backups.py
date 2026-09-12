import os
from test_accounts import setup

def test_edit_preserves_file_mode_and_backup_mapping(setup,tmp_path):
    app,c,h=setup;(tmp_path/'mods').mkdir(); app.config['BACKUP_DIR']=str(tmp_path/'backups')
    path=tmp_path/'mods'/'settings.txt';path.write_text('old');path.chmod(0o644)
    assert c.patch('/api/files/mods/content?path=settings.txt',data=b'new',headers=h).status_code==200
    assert path.stat().st_mode & 0o777 == 0o644
    events=c.get('/api/audit').json
    backup=next(event for event in events if event['action']=='file.backup')
    assert 'mods/settings.txt -> ' in backup['target']
    name=backup['target'].split(' -> ')[1]
    assert (tmp_path/'backups'/name).read_bytes()==b'old'

def test_binary_edit_rejected_without_replacement(setup,tmp_path):
    app,c,h=setup;(tmp_path/'mods').mkdir();app.config['BACKUP_DIR']=str(tmp_path/'backups')
    path=tmp_path/'mods'/'binary.jar';path.write_bytes(b'\x00\xff')
    assert c.patch('/api/files/mods/content?path=binary.jar',data=b'text',headers=h).status_code==400
    assert path.read_bytes()==b'\x00\xff'

def test_configured_upload_mode(setup,tmp_path):
    app,c,h=setup;(tmp_path/'mods').mkdir();app.config['ROOTS']['mods']['file_mode']=0o644
    assert c.put('/api/files/mods/content?path=new.jar',data=b'fixture',headers=h).status_code==201
    assert (tmp_path/'mods'/'new.jar').stat().st_mode & 0o777==0o644
