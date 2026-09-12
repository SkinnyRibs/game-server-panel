import json
import socketserver
import threading
from monitor import Docker
import pytest


def test_unix_docker_transport_fixed_endpoints(tmp_path):
    calls=[]
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            line=self.rfile.readline().decode().strip();calls.append(line)
            while self.rfile.readline() not in (b'\r\n',b''): pass
            if '/containers/json' in line: body=b'[]'
            elif '/logs?' in line: body=b'\x01\x00\x00\x00\x00\x00\x00\x04test'
            else: body=b''
            self.wfile.write(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(body)).encode()+b'\r\nConnection: close\r\n\r\n'+body)
    server=socketserver.UnixStreamServer(str(tmp_path/'docker.sock'),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        docker=Docker(str(tmp_path/'docker.sock'),['game'])
        assert docker.inventory()==[]
        assert docker.logs('game')=='test'
        docker.action('game','start')
        with pytest.raises(ValueError): docker.action('game','exec')
        with pytest.raises(ValueError): docker.logs('other')
        with pytest.raises(ValueError): docker.action('../game','stop')
        assert calls==['GET /v1.41/containers/json?all=1 HTTP/1.1','GET /v1.41/containers/game/logs?stdout=1&stderr=1&tail=200&timestamps=1 HTTP/1.1','POST /v1.41/containers/game/start?t=20 HTTP/1.1']
    finally: server.shutdown();server.server_close();thread.join()
