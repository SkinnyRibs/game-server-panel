from test_accounts import setup

def test_login_origin_and_password_rotation(setup):
    app,c,h=setup
    app.config['ALLOWED_ORIGIN']='https://panel.example.com'
    assert c.post('/api/login',json={'username':'owner','password':'test-only-password-123'},headers={'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/login',json={'username':'owner','password':'test-only-password-123'}).status_code==403
    h['Origin']='https://panel.example.com'
    r=c.post('/api/password',json={'current_password':'test-only-password-123','password':'new-test-password-123'},headers=h)
    assert r.status_code==200
    assert c.get('/api/me').status_code==401
    assert c.post('/api/login',json={'username':'owner','password':'new-test-password-123'},headers={'Origin':h['Origin']}).status_code==200

def test_local_bootstrap_cli(tmp_path):
    import os,subprocess
    password=tmp_path/'password'; password.write_text('local-test-password-123\n'); password.chmod(0o600)
    db=tmp_path/'db'
    r=subprocess.run(['.venv/bin/python','cli.py','createadmin','--username','admin','--password-file',str(password)],env={**os.environ,'PANEL_DATABASE':str(db),'PANEL_ORIGIN':'https://panel.example.com'},capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    assert 'local-test-password' not in r.stdout+r.stderr
    from panel import create_app
    app=create_app({'DATABASE':str(db),'ALLOWED_ORIGIN':'https://panel.example.com'})
    assert app.test_client().post('/api/login',json={'username':'admin','password':'local-test-password-123'},headers={'Origin':'https://panel.example.com'}).status_code==200


def test_successful_logins_do_not_exhaust_rate_limit(setup):
    app,c,_=setup
    app.config['ALLOWED_ORIGIN']='https://panel.example.com'
    headers={'Origin':'https://panel.example.com'}
    for _ in range(12):
        assert c.post('/api/login',json={'username':'owner','password':'test-only-password-123'},headers=headers).status_code==200


def test_trusted_cloudflare_client_ips_have_separate_rate_buckets(setup):
    app,c,_=setup
    app.config.update(ALLOWED_ORIGIN='https://panel.example.com',TRUSTED_PROXY_NETWORKS=['127.0.0.0/8'])
    body={'username':'owner','password':'wrong-password'}
    headers={'Origin':'https://panel.example.com','CF-Connecting-IP':'203.0.113.10'}
    for _ in range(10):
        assert c.post('/api/login',json=body,headers=headers).status_code==401
    assert c.post('/api/login',json=body,headers=headers).status_code==429
    other={'Origin':'https://panel.example.com','CF-Connecting-IP':'203.0.113.11'}
    assert c.post('/api/login',json={'username':'owner','password':'test-only-password-123'},headers=other).status_code==200
