#!/usr/bin/env sh
set -eu

INSTALL_DIR="${HOME}/.local/bin"

# Platform check
if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: only linux is supported in v1 (detected: $(uname -s))" >&2
    exit 21
fi

if [ "$(uname -m)" != "x86_64" ]; then
    echo "ERROR: only linux x86_64 is supported in v1 (detected: $(uname -m))" >&2
    exit 20
fi

# Download
URL_BIN="https://github.com/lorenzoervedosa/dograpper/releases/latest/download/dograpper-linux-x86_64"
URL_SHA="${URL_BIN}.sha256"

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT INT TERM

echo "[→] Downloading dograpper..."
if ! curl -fsSL --connect-timeout 10 --max-time 120 "$URL_BIN" -o "$TMPDIR/dograpper-linux-x86_64"; then
    echo "ERROR: failed to download binary from $URL_BIN" >&2
    exit 30
fi

if ! curl -fsSL --connect-timeout 10 --max-time 30 "$URL_SHA" -o "$TMPDIR/dograpper-linux-x86_64.sha256"; then
    echo "ERROR: failed to download checksum from $URL_SHA" >&2
    exit 30
fi

# Verify checksum (sha256 file references the filename "dograpper-linux-x86_64")
if ! ( cd "$TMPDIR" && sha256sum -c dograpper-linux-x86_64.sha256 >/dev/null 2>&1 ); then
    echo "ERROR: checksum mismatch, aborting" >&2
    exit 10
fi

# Install
mkdir -p "$INSTALL_DIR"
mv "$TMPDIR/dograpper-linux-x86_64" "$INSTALL_DIR/dograpper"
chmod +x "$INSTALL_DIR/dograpper"

# PATH hint
case ":$PATH:" in
    *":$INSTALL_DIR:"*) ;;
    *)
        printf '\n[!] Add to your shell rc:\n    export PATH="$HOME/.local/bin:$PATH"\n\n'
        ;;
esac

echo "[✓] dograpper installed to $INSTALL_DIR/dograpper"
echo "[→] Next step: run 'dograpper doctor --install' to fetch wget and chromium"
