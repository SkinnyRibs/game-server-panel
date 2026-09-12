import pytest
from panel import create_app, create_admin

@pytest.fixture
def setup(tmp_path):
    app=create_app({'DATABASE':str(tmp_path/'db'),'TESTING':True, 'ALLOWED_ORIGIN':None,'SERVERS':{'game':{'container':'game'}},'ROOTS':{'mods':{'server':'game','path':str(tmp_path/'mods')}}})
    create_admin(app,'owner','test-only-password-123')
    c=app.test_client(); r=c.post('/api/login',json={'username':'owner','password':'test-only-password-123'})
    return app,c,{'X-CSRF-Token':r.json['csrf']}

def test_account_grants_lifecycle(setup):
    app,c,h=setup
    payload={'username':'guest','password':'guest-password-for-test','admin':False,'grants':{'game':{'view':True,'logs':False,'start':True,'stop':False,'restart':False,'folders':{'mods':['read','upload']}}}}
    r=c.post('/api/users',json=payload,headers=h)
    assert r.status_code==201
    uid=r.json['id']
    guest=app.test_client(); assert guest.post('/api/login',json={'username':'guest','password':payload['password']}).status_code==200
    assert guest.get('/api/users').status_code==403
    assert c.patch(f'/api/users/{uid}',json={'grants':{'game':{'folders':{'arbitrary':['read']}}}},headers=h).status_code==400
    assert c.patch(f'/api/users/{uid}',json={'grants':{'game':{'view':True,'folders':{'mods':['edit']}}}},headers=h).status_code==200
    assert guest.get('/api/me').json['grants']['game']['folders']['mods']==['edit']
    assert c.patch(f'/api/users/{uid}',json={'disabled':True},headers=h).status_code==200
    assert guest.get('/api/me').status_code==401
    assert c.delete('/api/users/1',headers=h).status_code==409
    assert c.patch('/api/users/1',json={'disabled':True},headers=h).status_code==409
    assert c.delete(f'/api/users/{uid}',headers=h).status_code==200
    assert len(c.get('/api/users').json)==1
    assert any(x['action']=='user.delete' for x in c.get('/api/audit').json)

def test_login_rate_limit(setup):
    _,c,_=setup
    for _ in range(10): assert c.post('/api/login',json={'username':'missing','password':'bad'}).status_code==401
    assert c.post('/api/login',json={'username':'missing','password':'bad'}).status_code==429
