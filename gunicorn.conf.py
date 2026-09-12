# Private listener. The operator owns proxy/tunnel configuration.
bind = ['127.0.0.1:9130']
workers = 2
threads = 4
worker_class = 'gthread'
timeout = 60
graceful_timeout = 30
keepalive = 2
umask = 0o077
accesslog = None  # Avoid query-string/private-path logging.
errorlog = '-'
loglevel = 'warning'
forwarded_allow_ips = ''
secure_scheme_headers = {}
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4096
