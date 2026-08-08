#!/bin/sh
set -eu

INSTALLER_URL="${GROKTIMIZED_INSTALLER_URL:-https://raw.githubusercontent.com/braindead-dev/groktimizer/main/groktimizer/integrations/grok_build.py}"

if ! command -v grok >/dev/null 2>&1; then
  printf '%s\n' 'Grok Build is not installed. Install it first:' >&2
  printf '%s\n' '  curl -fsSL https://x.ai/cli/install.sh | bash' >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import tomllib' >/dev/null 2>&1; then
  printf '%s\n' 'Groktimized 2 requires Python 3.11 or newer for safe TOML updates.' >&2
  exit 1
fi

installer_file="$(mktemp "${TMPDIR:-/tmp}/groktimized-install.XXXXXX")"
trap 'rm -f "$installer_file"' EXIT HUP INT TERM

curl -fsSL "$INSTALLER_URL" -o "$installer_file"
python3 "$installer_file" "$@"
