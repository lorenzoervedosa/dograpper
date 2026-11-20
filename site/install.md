# Install

> No release is published yet: dograpper is in development, so install it from
> source. `scripts/install.sh` and its exit codes apply once a release binary
> exists.

## From source

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lorenzoervedosa/dograpper.git
cd dograpper
uv sync --extra dev --extra headless --extra httrack --extra fire-engine   # same extras as CI
uv run dograpper --help
```

### System dependencies

The `download` subcommand uses `wget` by default:

```bash
# macOS
brew install wget

# Ubuntu/Debian
sudo apt install wget
```

For SPA sites (React, Next.js, Mintlify, Docusaurus, etc.), cascade layer 4
uses `playwright`:

```bash
uv sync --extra headless
uv run playwright install chromium
```

On Linux, Chromium requires native libraries. `dograpper doctor
--check-system-libs` lists the missing ones and prints the `apt install`
command. On Ubuntu 24.04+ / Debian 13+:

```bash
sudo apt install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64
```

On Ubuntu 22.04 / Debian 12 and older the package is called `libasound2`
(without the `t64` suffix). `doctor --check-system-libs` reads
`/etc/os-release` and prints the name of your release; on a derivative it
cannot classify, it prints `libasound2` and a note about the `t64` name.

### Storage layout

`dograpper doctor --install` fetches a static wget and chromium (chromium needs
the `headless` extra); dograpper uses them before the ones on `PATH`.

| Path | Contents |
|------|---------|
| `~/.dograpper/bin/` | static wget |
| `~/.dograpper/playwright-browsers/` | chromium |

Override the default root: `DOGRAPPER_HOME=/custom/path dograpper doctor --install`
