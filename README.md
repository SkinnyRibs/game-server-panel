# Game Server Panel

A self-hosted, permission-scoped dashboard for monitoring Docker game servers, controlling approved containers, and managing files inside explicitly approved persistent-data roots.

The panel has no public registration, shell, arbitrary Docker API, container inspection, environment-variable display, or unrestricted host filesystem browser. Administrators create accounts and grant server and folder permissions individually.

## Features

- Host CPU, memory, disk, network, load, uptime, and issue monitoring
- Dynamic state for configured Docker containers
- Independent `view`, `logs`, `start`, `stop`, and `restart` permissions
- Independent folder `view`, `read`, `upload`, `edit`, and `delete` permissions
- Container-first file trees reached from the Services page
- Multi-file upload, text editing, download, folder creation, and empty-folder deletion
- Password hashing, persistent revocable sessions, CSRF protection, exact-origin checks, login throttling, and audit events
- Descriptor-relative Linux file operations with traversal, symlink, hardlink, hidden-name, sensitive-name, and protected-inode defenses

## Security boundary

The project intentionally does **not** auto-authorize every Docker container or mount. A local operator reviews Docker discovery output and explicitly configures only the containers and persistent roots that web users may access.

Mounting or granting access to the Docker socket gives the panel process powerful host capabilities. The HTTP API constrains users to configured containers, but a compromised panel process could abuse a raw Docker socket. Prefer a restricted socket proxy or separate privileged broker where practical. Never expose the Docker socket over TCP.

File write access is trusted access: uploaded mods, plugins, or game assets may later execute inside a game server. Review each root and its sensitive paths before granting permissions.

## Requirements

- Linux with Python 3.11 or newer
- Docker Engine with a local UNIX socket
- systemd user services for the included deployment workflow, or another process supervisor
- An HTTPS reverse proxy or private HTTPS tunnel

The file manager uses Linux descriptor-relative flags and is not supported on Windows or macOS hosts. Containerizing the panel is possible, but host-health metrics would describe the panel container unless host namespaces/filesystems are deliberately exposed. The recommended deployment is a dedicated unprivileged host account.

## Installation

Clone or download this repository using the URL provided by its host, then open a terminal in the repository root as the dedicated unprivileged service account. Keep the checkout in that account's writable home directory, or use another absolute directory that is created and owned by the service account first.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp config.example.json config.json
chmod 600 config.json
```

Do not commit `config.json`; it is ignored because it describes private host paths and infrastructure.

## Discover local containers safely

Run the local-only discovery command as the future service account:

```sh
.venv/bin/python cli.py discover --output docker-discovery.json
```

The mode-0600 output contains only:

- container name
- current state/status text
- host source and container destination for bind mounts
- whether each bind mount is writable

It excludes environment variables, labels, ports, images, raw inspect data, and named-volume storage paths. Discovery does not write `config.json`, grant permissions, alter containers, or create directories. Review the output, copy only selected resources into `config.json`, then remove the discovery file.

If Docker returns permission denied, give the service account access through your approved Docker-socket method. Membership in the `docker` group is effectively root-equivalent.

## Configure the panel

`config.example.json` is intentionally generic and fail-closed. Replace every placeholder.

### Top-level settings

- `ALLOWED_ORIGIN`: exact public HTTPS origin, with no path or trailing slash. Production startup fails if this is absent or invalid. Plain HTTP is accepted only for loopback test origins.
- `DATABASE`: absolute SQLite file path outside every approved game root.
- `BACKUP_DIR`: absolute directory outside the database and approved game roots.
- `DOCKER_SOCKET`: local Docker UNIX socket path.
- `TRUSTED_PROXY_NETWORKS`: proxy peer CIDRs allowed to supply `CF-Connecting-IP`. Leave empty unless using a trusted Cloudflare Tunnel/reverse-proxy hop that sets this header.
- `SERVERS`: explicit panel IDs mapped to real container names.
- `ROOTS`: explicit file aliases mapped to a configured server and absolute persistent-data path.

### Server entries

```json
"game-server": {
  "container": "actual-docker-container-name",
  "label": "My Game Server",
  "expected": "running"
}
```

Set `"readonly": true` for infrastructure containers that administrators may monitor but nobody may control or browse. Container mappings must be unique.

### Root entries

```json
"game-data": {
  "server": "game-server",
  "label": "Game mods",
  "path": "/srv/my-game/mods",
  "extensions": [".jar", ".zip", ".json", ".toml", ".cfg", ".txt"],
  "deny_paths": ["logs", "backups", "crash-reports", "saves/private"]
}
```

Prefer the narrowest useful subdirectory and a conservative extension allowlist. `"extensions": "*"` is supported only for roots whose contents and sensitive subtrees have been reviewed carefully. `deny_paths` entries are case-insensitive relative path prefixes. Global sensitive-name rules additionally block hidden names, access lists, RCON/server settings, private keys, logs, backups, crash reports, and credential-like filenames.

Roots must be absolute, mutually disjoint, and outside `DATABASE` and `BACKUP_DIR`. Startup fails closed on unsafe topology, duplicate container mappings, unknown servers, malformed origins, extension policies, or denied paths. The panel never creates missing game roots.

## Create the first administrator

Create a unique 14–1024 character password in a mode-0600 regular file owned by the service account. Do not pass passwords on the command line.

```sh
install -m 600 /dev/null ./admin-password
# Put the password in ./admin-password using a local editor or password manager.
PANEL_CONFIG="$PWD/config.json" .venv/bin/python cli.py createadmin \
  --username owner --password-file "$PWD/admin-password"
rm ./admin-password
```

There is no HTTP setup token or public bootstrap endpoint. Additional accounts are created by an administrator in the web interface.

## Generate and install a hardened systemd unit

Generate the unit from the reviewed config so `ReadWritePaths` includes only panel state and approved roots:

```sh
.venv/bin/python cli.py render-service \
  --config "$PWD/config.json" \
  --install-dir "$PWD" \
  --output "$PWD/server-panel.service"

systemd-analyze --user verify "$PWD/server-panel.service"
install -Dm600 "$PWD/server-panel.service" "$HOME/.config/systemd/user/server-panel.service"
# For a dedicated account that must start at boot and survive logout, run once:
sudo loginctl enable-linger "$(id -un)"
loginctl show-user "$(id -un)" -p Linger
systemctl --user daemon-reload
systemctl --user enable --now server-panel.service
systemctl --user status server-panel.service
```

The generated service binds only to `127.0.0.1:9130`, uses `ProtectSystem=strict`, `ProtectHome=read-only`, `NoNewPrivileges=true`, and an explicit writable-path list. Inspect it before installation. The tracked `deploy/server-panel.service` shows the generic example paths only.

## HTTPS reverse proxy

Route your chosen HTTPS hostname to `http://127.0.0.1:9130` using Caddy, nginx, Traefik, Cloudflare Tunnel, or another trusted proxy. `ALLOWED_ORIGIN` must exactly match the browser origin, for example:

```json
"ALLOWED_ORIGIN": "https://panel.example.com"
```

Do not bind the panel directly to `0.0.0.0` by default. Secure cookies are always enabled, so normal non-loopback use requires HTTPS.

## Permissions

Server permissions are independent: `view`, `logs`, `start`, `stop`, `restart`.

Folder permissions are independent: `view`, `read`, `upload`, `edit`, `delete`.

- `view` lists names; `read` downloads/opens content.
- `upload` creates files and folders but does not overwrite existing files.
- `edit` replaces bounded UTF-8 text with a backup first.
- `delete` backs up files before unlinking and removes empty directories only.
- Folder access does not reveal container state unless server `view` is also granted.
- Administrators have full access to all approved, non-readonly resources.

## Limits

- Upload/download/backup: 8 MiB per file
- Text view/edit: 1 MiB UTF-8
- Directory listing: 2,000 entries
- Docker logs: last 200 lines, maximum 256 KiB
- No recursive directory deletion, archive extraction, move operation, antivirus, package signature verification, or automatic backup pruning

Backups and audit records are retained until the operator archives or prunes them. Monitor disk usage and test recovery.

## Development and tests

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python -m playwright install chromium
PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers" .venv/bin/python -m pytest -q
node --check static/app.js
node --check static/files.js
node --check static/services.js
```

All tests use temporary directories, fake Docker backends, or a temporary UNIX socket. Browser tests use isolated fixture servers and do not touch real containers or game data.

See [API.md](API.md) for the HTTP contract.

## License

MIT. See [LICENSE](LICENSE).
