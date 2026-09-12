from test_accounts import setup

class FakeDocker:
    def __init__(self): self.actions=[]
    def inventory(self): return [{'Names':['/game'],'Id':'a'*64,'State':'running','Status':'Up 2 hours','Image':'safe:1'}, {'Names':['/private'],'Id':'b'*64,'State':'running','Status':'Up','Image':'secret'}]
    def action(self,name,action): self.actions.append((name,action))
    def logs(self,name): return 'actual fixture log\n'

def test_monitor_and_separate_controls(setup):
    app,c,h=setup; docker=FakeDocker(); app.extensions['docker']=docker
    r=c.get('/api/overview')
    assert r.status_code==200
    assert r.json['health']['memory']['total']>0
    assert [s['id'] for s in r.json['servers']]==['game']
    assert 'private' not in r.text
    payload={'username':'operator','password':'operator-test-password','grants':{'game':{'view':True,'start':True}}}
    assert c.post('/api/users',json=payload,headers=h).status_code==201
    guest=app.test_client(); r=guest.post('/api/login',json={'username':'operator','password':payload['password']}); gh={'X-CSRF-Token':r.json['csrf']}
    assert guest.get('/api/overview').json['health'] is None
    assert guest.get('/api/servers/game/logs').status_code==403
    assert guest.post('/api/servers/game/start',headers=gh).status_code==200
    for action in ['stop','restart','exec','inspect']:
        assert guest.post('/api/servers/game/'+action,headers=gh).status_code==403
    assert guest.post('/api/servers/private/start',headers=gh).status_code==404
    assert docker.actions==[('game','start')]
    assert c.get('/api/servers/game/logs').json['text']=='actual fixture log\n'
    assert c.get('/api/catalog').json['roots']['mods']['server']=='game'
    assert str(app.config['ROOTS']['mods']['path']) not in c.get('/api/catalog').text


def test_catalog_hides_ungranted_folder_labels(setup,tmp_path):
    app,c,h=setup
    app.config['ROOTS']['private-mods']={'server':'game','path':str(tmp_path/'private'),'label':'Private folder'}
    response=c.post('/api/users',json={
        'username':'member','password':'member-test-password',
        'grants':{'game':{'folders':{'mods':['read']}}},
    },headers=h)
    assert response.status_code==201
    assert c.post('/api/logout',headers=h).status_code==200
    assert c.post('/api/login',json={'username':'member','password':'member-test-password'}).status_code==200
    catalog=c.get('/api/catalog').get_json()
    assert set(catalog['roots'])=={'mods'}
