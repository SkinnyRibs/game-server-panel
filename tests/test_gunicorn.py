import os
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

def test_gunicorn_loopback_serves_real_app(tmp_path):
    assert Path('gunicorn.conf.py').exists(), 'gunicorn deployment config missing'
    env={**os.environ,'PANEL_DATABASE':str(tmp_path/'db'),'PANEL_ORIGIN':'http://127.0.0.1:9140'};env.pop('PANEL_CONFIG',None)
    process=subprocess.Popen(['.venv/bin/gunicorn','--config','gunicorn.conf.py','--bind','127.0.0.1:9140','panel:create_app()'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            if process.poll() is not None: raise AssertionError(process.stderr.read().decode())
            try:
                with urllib.request.urlopen('http://127.0.0.1:9140/',timeout=1) as response:
                    assert response.status==200
                    assert response.headers['Cache-Control']=='no-store'
                    assert b'/static/app.js' in response.read()
                break
            except (OSError,urllib.error.URLError): time.sleep(.05)
        else: raise AssertionError('Gunicorn failed readiness')
        try: urllib.request.urlopen('http://127.0.0.1:9140/api/overview',timeout=1)
        except urllib.error.HTTPError as error: assert error.code==401
        else: raise AssertionError('Unauthenticated overview leaked')
    finally:
        process.terminate();process.communicate(timeout=10)
