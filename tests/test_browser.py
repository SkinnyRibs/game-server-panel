import threading
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import make_server
from panel import create_app,create_admin
from test_monitor import FakeDocker

def test_browser_full_workflow(tmp_path):
    root=tmp_path/'mods';root.mkdir();(root/'settings.txt').write_text('before')
    app=create_app({'DATABASE':str(tmp_path/'db'),'BACKUP_DIR':str(tmp_path/'backups'),'ALLOWED_ORIGIN':'http://localhost:9139','SERVERS':{'game':{'container':'game','label':'Test game'}},'ROOTS':{'mods':{'server':'game','path':str(root),'label':'Mod files'}}})
    app.extensions['docker']=FakeDocker();create_admin(app,'owner','browser-test-password')
    server=make_server('127.0.0.1',9139,app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://localhost:9139')
            expect(page.get_by_role('heading',name='Sign in')).to_be_visible()
            page.get_by_label('Username',exact=True).fill('owner'); page.get_by_label('Password',exact=True).fill('browser-test-password'); page.get_by_role('button',name='Sign in',exact=True).click()
            expect(page.get_by_role('heading',name='Host overview')).to_be_visible()
            expect(page.get_by_text('Test game',exact=True)).not_to_be_visible()
            page.get_by_role('button',name='Services',exact=True).click();expect(page.get_by_text('Test game',exact=True)).to_be_visible()
            page.get_by_role('button',name='Accounts',exact=True).click()
            page.get_by_role('button',name='Create account',exact=True).click()
            page.get_by_label('Username',exact=True).fill('guest')
            page.get_by_label('Temporary password',exact=True).fill('guest-browser-password')
            page.get_by_label('Test game · view',exact=True).check()
            page.get_by_label('Mod files · view',exact=True).check()
            page.get_by_label('Mod files · read',exact=True).check()
            page.get_by_role('button',name='Save account',exact=True).click()
            expect(page.get_by_text('guest',exact=True)).to_be_visible()
            page.get_by_role('button',name='Edit guest',exact=True).click()
            page.get_by_label('Test game · start',exact=True).check(); page.get_by_role('button',name='Save account',exact=True).click()
            page.get_by_role('button',name='Services',exact=True).click();page.get_by_role('button',name='Open files for Test game').click()
            page.get_by_role('button',name='Open settings.txt',exact=True).click()
            expect(page.get_by_label('File content')).to_have_value('before')
            page.get_by_label('File content').fill('after');page.get_by_role('button',name='Save changes',exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('File saved; backup retained')
            assert (root/'settings.txt').read_text()=='after'
            page.get_by_role('button',name='Close editor',exact=True).click()
            page.get_by_role('button',name='Edit settings.txt',exact=True).click()
            expect(page.get_by_label('File content')).to_have_value('after')
            page.get_by_role('button',name='Close editor',exact=True).click()
            page.get_by_label('Upload files').set_input_files({'name':'new.jar','mimeType':'application/java-archive','buffer':b'fixture'})
            expect(page.get_by_text('new.jar',exact=True)).to_be_visible()
            page.on('dialog',lambda dialog:dialog.accept())
            page.get_by_role('button',name='Delete new.jar',exact=True).click()
            expect(page.get_by_text('new.jar',exact=True)).not_to_be_visible()
            (root/'subdir').mkdir()
            page.get_by_role('button',name='Refresh',exact=True).click();page.locator('#file-entries').get_by_role('button',name='Open folder subdir',exact=True).click()
            page.get_by_label('Upload files').set_input_files({'name':'nested.jar','mimeType':'application/java-archive','buffer':b'nested'})
            expect(page.get_by_text('nested.jar',exact=True)).to_be_visible()
            assert (root/'subdir'/'nested.jar').read_bytes()==b'nested'
            page.get_by_role('button',name='Delete nested.jar',exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('deleted')
            assert not (root/'subdir'/'nested.jar').exists()
            page.get_by_role('button',name='Services',exact=True).click()
            page.get_by_role('button',name='Logs Test game',exact=True).click()
            expect(page.get_by_text('actual fixture log',exact=False)).to_be_visible()
            page.get_by_role('button',name='Close logs').click()
            page.get_by_role('button',name='Restart Test game',exact=True).click()
            expect(page.get_by_role('status')).to_contain_text('accepted')
            assert app.extensions['docker'].actions==[('game','restart')]
            page.get_by_role('button',name='Accounts',exact=True).click()
            page.get_by_role('button',name='Disable guest',exact=True).click();expect(page.get_by_role('button',name='Enable guest')).to_be_visible()
            page.get_by_role('button',name='Delete guest',exact=True).click();expect(page.get_by_text('guest',exact=True)).not_to_be_visible()
            page.get_by_role('button',name='Monitor',exact=True).click()
            expect(page.get_by_role('heading',name='Host overview')).to_be_visible()
            assert page.locator('.topbar').bounding_box()['y'] < 80
            page.screenshot(path='test-results/desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path='test-results/mobile.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.get_by_role('button',name='Password',exact=True).click()
            page.get_by_label('Current password').fill('browser-test-password');page.get_by_label('New password').fill('rotated-browser-password')
            page.get_by_role('button',name='Change password',exact=True).click()
            expect(page.get_by_role('heading',name='Sign in')).to_be_visible()
            assert errors==[]
            browser.close()
    finally: server.shutdown();thread.join();


def test_edit_only_user_must_confirm_explicit_content_replacement(tmp_path):
    root=tmp_path/'mods';root.mkdir();target=root/'settings.txt';target.write_text('private original')
    app=create_app({'DATABASE':str(tmp_path/'db'),'BACKUP_DIR':str(tmp_path/'backups'),'ALLOWED_ORIGIN':'http://localhost:9140','SERVERS':{'game':{'container':'game','label':'Test game'}},'ROOTS':{'mods':{'server':'game','path':str(root),'label':'Mod files'}}})
    create_admin(app,'owner','browser-test-password')
    client=app.test_client();login=client.post('/api/login',json={'username':'owner','password':'browser-test-password'},headers={'Origin':'http://localhost:9140'})
    grants={'game':{'folders':{'mods':['edit']}}}
    assert client.post('/api/users',json={'username':'editor','password':'editor-test-password','grants':grants},headers={'Origin':'http://localhost:9140','X-CSRF-Token':login.json['csrf']}).status_code==201
    server=make_server('127.0.0.1',9140,app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            page=browser.new_page();page.goto('http://localhost:9140')
            page.get_by_label('Username',exact=True).fill('editor');page.get_by_label('Password',exact=True).fill('editor-test-password');page.get_by_role('button',name='Sign in',exact=True).click()
            page.get_by_role('button',name='Services',exact=True).click();expect(page.get_by_text('Status hidden',exact=True)).to_be_visible();page.get_by_role('button',name='Open files for Test game').click();page.get_by_label('Relative file path').fill('settings.txt');page.get_by_role('button',name='Replace file',exact=True).click()
            expect(page.get_by_role('heading',name='Replace contents · settings.txt')).to_be_visible();expect(page.get_by_label('Replacement content')).to_have_value('')
            page.get_by_label('Replacement content').fill('replacement')
            page.once('dialog',lambda dialog:dialog.dismiss());page.get_by_role('button',name='Replace contents',exact=True).click();assert target.read_text()=='private original'
            page.once('dialog',lambda dialog:dialog.accept());page.get_by_role('button',name='Replace contents',exact=True).click();expect(page.get_by_role('status')).to_contain_text('saved');assert target.read_text()=='replacement'
            browser.close()
    finally: server.shutdown();thread.join()


def test_container_first_file_tree_creates_folder_and_uploads_into_selection(tmp_path):
    alpha=tmp_path/'alpha';beta=tmp_path/'beta';alpha.mkdir();beta.mkdir()
    app=create_app({'DATABASE':str(tmp_path/'db'),'BACKUP_DIR':str(tmp_path/'backups'),'ALLOWED_ORIGIN':'http://localhost:9141','SERVERS':{'alpha':{'container':'alpha','label':'Alpha game'},'beta':{'container':'beta','label':'Beta game'}},'ROOTS':{'alpha-mods':{'server':'alpha','path':str(alpha),'label':'Alpha mods'},'beta-mods':{'server':'beta','path':str(beta),'label':'Beta mods'}}})
    app.extensions['docker']=FakeDocker();create_admin(app,'owner','browser-test-password')
    server=make_server('127.0.0.1',9141,app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1280,'height':850});console_errors=[];page.on('console',lambda message:console_errors.append(message.text) if message.type=='error' else None);page.goto('http://localhost:9141')
            page.get_by_label('Username',exact=True).fill('owner');page.get_by_label('Password',exact=True).fill('browser-test-password');page.get_by_role('button',name='Sign in',exact=True).click()
            page.get_by_role('button',name='Services',exact=True).click();page.get_by_role('button',name='Open files for Alpha game').click()
            expect(page.get_by_label('Container',exact=True)).to_be_visible()
            expect(page.get_by_role('navigation',name='Container file tree')).to_be_visible()
            page.get_by_label('Container',exact=True).select_option('beta');expect(page.get_by_role('button',name='Open root Beta mods')).to_be_visible();expect(page.get_by_text('Alpha mods',exact=True)).not_to_be_visible()
            page.get_by_label('Container',exact=True).select_option('alpha');expect(page.get_by_role('button',name='Open root Alpha mods')).to_be_visible()
            page.get_by_role('button',name='New folder',exact=True).click();expect(page.get_by_role('dialog',name='Create folder')).to_be_visible();page.get_by_label('Folder name',exact=True).fill('NewMod');page.get_by_role('button',name='Create folder',exact=True).click()
            expect(page.locator('#file-entries').get_by_role('button',name='Open folder NewMod')).to_be_visible();page.locator('#file-entries').get_by_role('button',name='Open folder NewMod').click()
            expect(page.get_by_text('Alpha mods / NewMod',exact=True)).to_be_visible()
            page.get_by_label('Upload files').set_input_files({'name':'feature.jar','mimeType':'application/java-archive','buffer':b'feature'})
            expect(page.get_by_text('feature.jar',exact=True)).to_be_visible();assert (alpha/'NewMod'/'feature.jar').read_bytes()==b'feature'
            page.screenshot(path='test-results/files-desktop.png',full_page=True)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path='test-results/files-mobile.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            action_box=page.get_by_role('button',name='Open feature.jar').bounding_box()
            assert action_box and action_box['x']+action_box['width']<=390
            assert not any('Refused to apply inline style' in error for error in console_errors)
            browser.close()
    finally: server.shutdown();thread.join()


def test_file_tree_cache_is_cleared_between_accounts(tmp_path):
    root=tmp_path/'mods';root.mkdir();(root/'CachedFolder').mkdir()
    app=create_app({'DATABASE':str(tmp_path/'db'),'BACKUP_DIR':str(tmp_path/'backups'),'ALLOWED_ORIGIN':'http://localhost:9142','SERVERS':{'game':{'container':'game','label':'Test game'}},'ROOTS':{'mods':{'server':'game','path':str(root),'label':'Mod files'}}})
    app.extensions['docker']=FakeDocker();create_admin(app,'owner','browser-test-password')
    client=app.test_client();login=client.post('/api/login',json={'username':'owner','password':'browser-test-password'},headers={'Origin':'http://localhost:9142'})
    assert client.post('/api/users',json={'username':'limited','password':'limited-test-password','grants':{'game':{'folders':{'mods':['edit']}}}},headers={'Origin':'http://localhost:9142','X-CSRF-Token':login.json['csrf']}).status_code==201
    server=make_server('127.0.0.1',9142,app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page();page.goto('http://localhost:9142')
            page.get_by_label('Username',exact=True).fill('owner');page.get_by_label('Password',exact=True).fill('browser-test-password');page.get_by_role('button',name='Sign in',exact=True).click();page.get_by_role('button',name='Services',exact=True).click();page.get_by_role('button',name='Open files for Test game').click();expect(page.get_by_text('CachedFolder',exact=True)).to_have_count(2)
            page.get_by_role('button',name='Sign out',exact=True).click();page.get_by_label('Username',exact=True).fill('limited');page.get_by_label('Password',exact=True).fill('limited-test-password');page.get_by_role('button',name='Sign in',exact=True).click();page.get_by_role('button',name='Services',exact=True).click();page.get_by_role('button',name='Open files for Test game').click()
            expect(page.get_by_text('CachedFolder',exact=True)).to_have_count(0);expect(page.get_by_text('Folder listing is not granted.',exact=False)).to_be_visible();browser.close()
    finally: server.shutdown();thread.join()


def test_dynamic_services_page_opens_game_files_and_keeps_infrastructure_static(tmp_path):
    class DynamicDocker:
        def __init__(self): self.state='running'
        def inventory(self): return [{'Names':['/alpha'],'Id':'a'*64,'State':self.state,'Status':'Up' if self.state=='running' else 'Exited'}, {'Names':['/infra'],'Id':'b'*64,'State':'running','Status':'Up'}]
        def action(self,name,action):
            if name=='alpha' and action=='stop': self.state='exited'
        def logs(self,name): return 'fixture log\n'
    root=tmp_path/'alpha';root.mkdir()
    app=create_app({'DATABASE':str(tmp_path/'db'),'ALLOWED_ORIGIN':'http://localhost:9143','SERVERS':{'alpha':{'container':'alpha','label':'Alpha game'},'infra':{'container':'infra','label':'Infrastructure','readonly':True}},'ROOTS':{'alpha-data':{'server':'alpha','path':str(root),'label':'Alpha data'}}})
    app.extensions['docker']=DynamicDocker();create_admin(app,'owner','browser-test-password')
    server=make_server('127.0.0.1',9143,app);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page();page.goto('http://localhost:9143')
            page.get_by_label('Username',exact=True).fill('owner');page.get_by_label('Password',exact=True).fill('browser-test-password');page.get_by_role('button',name='Sign in',exact=True).click()
            expect(page.get_by_role('heading',name='Host overview')).to_be_visible();expect(page.get_by_role('heading',name='Services')).not_to_be_visible()
            expect(page.locator('nav[aria-label="Main"]').get_by_role('button',name='Files',exact=True)).to_have_count(0)
            page.get_by_role('button',name='Services',exact=True).click();expect(page.get_by_role('heading',name='Services')).to_be_visible();expect(page.get_by_text('Alpha game',exact=True)).to_be_visible();expect(page.get_by_text('Infrastructure',exact=True)).to_be_visible()
            expect(page.get_by_role('button',name='Open files for Alpha game')).to_be_visible();expect(page.get_by_role('button',name='Open files for Infrastructure')).to_have_count(0)
            page.screenshot(path='test-results/services-desktop.png',full_page=True);page.set_viewport_size({'width':390,'height':844});page.screenshot(path='test-results/services-mobile.png',full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            service_box=page.get_by_role('button',name='Open files for Alpha game').bounding_box();assert service_box and service_box['x']+service_box['width']<=390
            page.once('dialog',lambda dialog:dialog.accept());page.get_by_role('button',name='Stop Alpha game',exact=True).click();expect(page.get_by_role('row').filter(has_text='Alpha game').get_by_text('exited',exact=True)).to_be_visible()
            page.get_by_role('button',name='Open files for Alpha game').click();expect(page.get_by_role('heading',name='Container files')).to_be_visible();expect(page.get_by_label('Container',exact=True)).to_have_value('alpha')
            browser.close()
    finally: server.shutdown();thread.join()
