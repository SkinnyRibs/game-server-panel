# HTTP API contract

All paths are relative to the site root. JSON requests use `Content-Type: application/json`. Every mutation, including login, must send the exact configured `ALLOWED_ORIGIN` (for example, `https://panel.example.com`). Every authenticated mutation additionally requires `X-CSRF-Token` from login or `/api/me`. Authentication uses the host-only `panel_session` cookie. JSON errors use `{"error":"description"}` for normal validation/auth failures. No CORS access is enabled.

| Method / path | Permission | Request | Successful response |
|---|---|---|---|
| `GET /` | Public | — | HTML login / application shell (no private data) |
| `POST /api/login` | Public + exact Origin; rate limited | `{username,password}` | `200 {csrf}`, sets 12h secure session cookie |
| `GET /api/me` | Session | — | `{id,username,admin,csrf,grants}`; admin is SQLite 0/1 |
| `POST /api/logout` | Session + CSRF | `{}` or empty | `200 {ok:true}`, session revoked/cookie removed |
| `POST /api/password` | Session + CSRF | `{current_password,password}` | `200 {ok:true}`, all own sessions revoked |
| `GET /api/catalog` | Session | — | `{servers:{id:{label,readonly}}, roots:{alias:{server,label}},server_permissions:[...],file_permissions:[...]}`; never absolute paths |
| `GET /api/overview` | Session | — | `{health,servers,issues,sampled_at}` (sampled_at Unix seconds); host health only for admin, else null |
| `GET /api/servers/{server}/logs` | Server `logs` | — | `{text}` last 200 stdout/stderr lines with timestamps, bounded to 256 KiB |
| `POST /api/servers/{server}/start` | Server `start` + CSRF | `{}` or empty | `200 {ok:true}` once Docker returns success |
| `POST /api/servers/{server}/stop` | Server `stop` + CSRF | `{}` or empty | As above; Docker receives t=20 |
| `POST /api/servers/{server}/restart` | Server `restart` + CSRF | `{}` or empty | As above; Docker receives t=20 |
| `GET /api/users` | Admin | — | Array `{id,username,admin,disabled,grants}`; no password hashes |
| `POST /api/users` | Admin + CSRF | `{username,password,admin?:false,grants?:{}}` | `201 {id}`; **no grants by default** |
| `PATCH /api/users/{id}` | Admin + CSRF | Any subset `{admin:boolean,disabled:boolean,password:string,grants:object}` | `200 {ok:true}`; grants replaces entire grant object |
| `DELETE /api/users/{id}` | Admin + CSRF | — | `200 {ok:true}`; sessions cascade-delete |
| `GET /api/audit` | Admin | — | Latest 200 `{id,at,actor,action,target}`, descending ID |
| `GET /api/files/{alias}/list?path=subdir` | Alias `view` | Empty path lists root | `{entries:[{name,directory,size,modified}],path,limit:2000}` |
| `GET /api/files/{alias}/content?path=file.jar` | Alias `read` | Relative path required | Binary attachment, max 8 MiB; not JSON |
| `GET /api/files/{alias}/content?path=file.txt&text=1` | Alias `read` | Relative path required | `{text}` UTF-8, no NUL, max 1 MiB |
| `PUT /api/files/{alias}/content?path=new.jar` | Alias `upload` + CSRF | **Raw bytes**, `Content-Type: application/octet-stream`, max 8 MiB | `201 {ok:true}`. Existing target rejected; no overwrite |
| `PATCH /api/files/{alias}/content?path=file.txt` | Alias `edit` + CSRF | **Raw UTF-8 bytes**, max 1 MiB | `200 {ok:true}`; original and new contents must be text, backup before replacement |
| `DELETE /api/files/{alias}/content?path=file.jar` | Alias `delete` + CSRF | — | `200 {ok:true}`, backup before unlink; no directory recursion |
| `PUT /api/files/{alias}/directory?path=NewMod` | Alias `upload` + CSRF | Empty body; relative non-empty path | `201 {ok:true}`; creates one directory inside an existing approved parent |
| `DELETE /api/files/{alias}/directory?path=NewMod` | Alias `delete` + CSRF | — | `200 {ok:true}` for an empty directory; non-empty directories return `409` |

## Grant shape

```json
{
  "game-server": {
    "view": true,
    "logs": false,
    "start": true,
    "stop": false,
    "restart": false,
    "folders": {
      "game-data": ["view", "read", "upload"]
    }
  }
}
```

All omitted permissions deny. Start/stop/restart do not imply one another. `view` does not imply logs, files or controls. Alias `view` means listing only; `read` means download/open. `upload` creates a new filename or subdirectory only; editing an existing target requires `edit`. `delete` removes a file with backup or an empty subdirectory. An alias must belong to that configured server. Infrastructure servers marked `readonly` cannot be delegated; admins see their inventory but cannot access logs or controls. Member endpoints cannot enumerate ungranted server status. Catalog may identify configured aliases for a server the member has been granted, but file operations still require explicit alias permissions.

## Overview shape

`health` is null for members; administrators receive:
- `cpu_percent`, `cpu_count`, `load` (1/5/15 minutes), `uptime` seconds.
- `memory`: total/used/available bytes and percent; `swap`: psutil swap fields.
- `disk`: root filesystem total/used/free bytes and percent.
- `network`: cumulative sent/received bytes; `io`: cumulative read/write bytes or null.

`servers` contains only viewable sanitized records: `{id,label,state,status,expected,readonly,permissions,folders}`. No raw Docker identifiers, environment, inspection, mounts, labels or network data is included. `issues` contains detected mismatched expected state, unhealthy status, unavailable Docker and admin host resource threshold warnings. Docker unavailable yields unknown statuses, not healthy guesses.

## Status codes

- 400 malformed data, invalid grants, binary passed to text editing, invalid password length.
- 401 unauthenticated, expired/revoked session, bad/disabled login.
- 403 origin/CSRF/permission denied or forbidden file path.
- 404 unknown server/alias/user/file or unavailable missing approved root.
- 405 wrong method/unknown operation (framework HTML may be returned for unsupported methods).
- 409 username/upload/folder target already exists, non-empty folder deletion, or final active admin removal/demotion/disable attempted.
- 413 body/file too large or text-view size exceeded.
- 429 login source-IP bucket exhausted (15-minute window).
- 502 Docker action/log request failed or timed out; status may have changed despite a timeout, so refresh before retrying.
- 503 filesystem I/O unavailable; existing files are not intentionally removed if backup fails.

No registration, public setup, arbitrary exec, file move, archive extraction, recursive delete, server configuration, or backup-download HTTP endpoints exist. Backup recovery and approved-root provisioning remain local operator tasks.
