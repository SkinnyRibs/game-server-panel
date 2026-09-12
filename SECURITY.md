# Security Policy

## Supported versions

Security fixes are applied to the latest release on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature when enabled, or contact the repository owner privately. Do not open a public issue containing credentials, host paths, exploit details, or personal infrastructure data.

Include the affected revision, deployment model, reproduction steps using disposable data, impact, and any proposed mitigation. Maintainers should acknowledge a report before requesting additional sensitive evidence.

## Deployment warning

This application controls explicitly allowlisted Docker containers and writes to explicitly allowlisted host directories. Docker-socket access is highly privileged, and writable game content may execute code later. Operators must review every configured container, root, extension policy, denied path, reverse-proxy network, and generated systemd unit before deployment.

Never attach an unrestricted public listener directly, expose the Docker socket over TCP, commit `config.json`, or use production game data in tests.
