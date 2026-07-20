# ADR-005: POSIX sh for Scripts

**Status:** Accepted
**Date:** 2026-07-20

## Context

We need shell scripts for bootstrapping, backups, cleanup, and deployment. The target server is Ubuntu 22.04 where `/bin/sh` is `dash` (not `bash`).

## Decision

All shell scripts must be **POSIX-compliant `sh`** scripts, not `bash` scripts.

## Reason

The folder structure script originally used bash-specific brace expansion:

```bash
# WRONG — bash only
mkdir -p "$ROOT"/{config,docker,services}
```

This fails silently on Ubuntu with `dash`:
```
config,: command not found
```

The correct POSIX form:
```sh
#!/bin/sh
mkdir -p "$ROOT/config"
mkdir -p "$ROOT/docker"
mkdir -p "$ROOT/services"
```

## Rules

1. All scripts start with `#!/bin/sh` (not `#!/bin/bash`)
2. No brace expansion `{a,b,c}`
3. No `[[` double brackets — use `[` single bracket
4. No `local` keyword in functions — use subshells instead
5. No arrays — use space-separated strings with `for x in $LIST`
6. Test with `sh script.sh`, not `bash script.sh`

## Consequences

- Scripts work on any POSIX system (Ubuntu, Alpine containers, macOS)
- Less expressive than bash, but more portable
- Tested scripts: `bootstrap.sh`, `backup.sh`, `restore.sh`, `update.sh`, `cleanup.sh`
