#!/bin/bash
# Run from a source checkout or extracted source zip; never pipe a remote script here.
# Official release checksums verified against the individual .sha256 assets:
# https://github.com/astral-sh/uv/releases/tag/0.13.7
set -eu
umask 077

fail() { printf 'AdCode installation stopped: %s\n' "$1" >&2; exit 1; }
[ "$(uname -s)" = Darwin ] || fail 'This installer requires macOS.'
[ "$(id -u)" != 0 ] || fail 'Run as your normal user, not root or sudo.'
[ -n "${HOME:-}" ] && [ "${HOME#/}" != "$HOME" ] || fail 'HOME must be absolute.'
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)
APP="$HOME/Library/Application Support/AdCode"
ROOT="$HOME/AdCode Workspaces"

# Reject links before mkdir can follow them. Existing installs and user configs stay put.
# Stage below HOME, not macOS /tmp or /var aliases. SOURCE above is canonicalized
# with pwd -P, so a checkout reached through those system aliases is supported.
# HOME/install/workspace paths themselves must use real, non-symlink ancestors.
check_directory() {
    local path="$1"
    while [ "$path" != / ]; do
        [ ! -L "$path" ] || fail 'An installation path contains a symlink.'
        if [ -e "$path" ] && [ ! -d "$path" ]; then fail 'An installation path is not a directory.'; fi
        path=$(dirname -- "$path")
    done
}
check_directory "$APP/releases"
check_directory "$APP/bin"
check_directory "$APP/python"
check_directory "$APP/cache"
check_directory "$ROOT"
for item in src/local_setup.py src/bootstrap_server.py requirements-local.lock; do
    [ -f "$SOURCE/$item" ] && [ ! -L "$SOURCE/$item" ] || fail 'Incomplete source input; runtime lock and bootstrap are required.'
done
mkdir -p -- "$APP/releases" "$APP/bin"
mkdir -- "$APP/.install-lock" 2>/dev/null || fail 'Another installer is running, or a stale .install-lock needs local inspection.'
STAGE=''
RELEASE=''
SUCCESS=0
cleanup() {
    local result=$?
    trap - EXIT
    if [ -n "$STAGE" ]; then rm -rf -- "$STAGE"; fi
    # Completed releases are retained, including on publication failure, for inspection.
    rmdir -- "$APP/.install-lock"
    if [ "$SUCCESS" != 1 ]; then printf 'Existing releases and configuration were retained. Review the error above before retrying.\n' >&2; fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
STAGE=$(mktemp -d "$APP/.stage.XXXXXXXX")

UV_VERSION=0.13.7
case "$(uname -m)" in
    arm64|aarch64)
        TARGET=aarch64-apple-darwin
        SHA256=81b811b57e4624df7ed3aac148e0359100d9962f3d9dce00aec533dc2e086731
        ;;
    x86_64)
        TARGET=x86_64-apple-darwin
        SHA256=20c47e4c1f630b8abaff8c291fa9b9aa300fef92c4fbff95adf198b55287cda7
        ;;
    *) fail 'Unsupported Mac architecture.' ;;
esac
UV=''
if command -v uv >/dev/null 2>&1; then
    if [ "$(uv --version)" = "uv $UV_VERSION" ]; then UV=$(command -v uv); fi
fi
if [ -z "$UV" ]; then
    ASSET="uv-$TARGET.tar.gz"
    printf 'Downloading official uv %s for %s (SHA-256 verified before extraction).\n' "$UV_VERSION" "$TARGET"
    curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --connect-timeout 30 --max-time 300 --retry 2 \
        "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ASSET" --output "$STAGE/$ASSET"
    printf '%s  %s\n' "$SHA256" "$STAGE/$ASSET" > "$STAGE/checksum"
    shasum -a 256 -c "$STAGE/checksum" || fail 'uv archive checksum mismatch; nothing was executed.'
    # Extract only the verified executable, not arbitrary archive contents.
    tar -xzf "$STAGE/$ASSET" -C "$STAGE" "uv-$TARGET/uv"
    UV="$STAGE/uv-$TARGET/uv"
    [ "$("$UV" --version)" = "uv $UV_VERSION" ] || fail 'Unexpected uv version.'
fi

# Managed Python is installed once here; launchers invoke venv Python directly,
# never uv run, pip, or any dependency downloader at MCP startup.
export UV_PYTHON_INSTALL_DIR="$APP/python"
export UV_CACHE_DIR="$APP/cache"
export UV_NO_CONFIG=1
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV UV_PROJECT_ENVIRONMENT
printf 'Installing user-local standalone Python 3.13 and hash-locked runtime dependencies.\n'
"$UV" python install 3.13 --no-progress
# Build at its final versioned path: virtualenvs are not safely relocatable.
RELEASE=$(mktemp -d "$APP/releases/local-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXXXX")
"$UV" venv --managed-python --python 3.13 "$RELEASE/venv"
PYTHON="$RELEASE/venv/bin/python"
"$PYTHON" "$SOURCE/src/local_setup.py" stage-source --source "$SOURCE" --destination "$RELEASE"
"$UV" pip sync --python "$PYTHON" --require-hashes --only-binary :all: --no-progress "$RELEASE/requirements-local.lock"
"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 13); import dotenv, mcp, anthropic, jsonschema, openpyxl, facebook_business'
# Cursor may start MCP with any cwd. Fail before activation if the installed
# bootstrap cannot import its own package when launched exactly as registered.
(cd -- "$STAGE"; "$PYTHON" "$RELEASE/src/bootstrap_server.py" --help >/dev/null)
"$PYTHON" "$RELEASE/src/local_setup.py" publish-install --app "$APP" --release "$RELEASE" --root "$ROOT"
SUCCESS=1
printf '\nAdCode installed. Restart Cursor to load the global AdCode-Setup server.\n'
printf 'Ask AdCode-Setup to create a workspace for your business, then ask to open it.\n'
printf 'Open its .env yourself, enter your keys locally, save, then ask to check the workspace.\n'
printf 'Never paste credentials into chat. Normal Cursor approval prompts still apply.\n'
printf 'Stable setup launcher: %s/bin/Configure AdCode.command\n' "$APP"
printf 'Previous releases remain under %s/releases; previous points to the last active release.\n' "$APP"
