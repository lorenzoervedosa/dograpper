"""Docs subcommand — local reference site generated from the click tree.

The page is built at run time from the same command objects `--help` reads, so
it cannot disagree with the installed CLI. Self-contained HTML/CSS (no external
resource, no data file) served by stdlib `http.server` on 127.0.0.1 only.
"""

import inspect
import webbrowser
from html import escape as _e
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import click

_CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#59636e;--line:#d1d9e0;--accent:#0b5fd1;--code:#f3f5f7}
@media (prefers-color-scheme:dark){:root{--bg:#14171a;--fg:#e6e9ec;--muted:#9aa4ae;--line:#2f353b;--accent:#6ea8ff;--code:#1e2328}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;display:flex;align-items:flex-start}
nav{position:sticky;top:0;height:100vh;overflow:auto;width:15rem;flex:none;padding:1rem;border-right:1px solid var(--line)}
nav a{display:block;padding:.15rem 0;color:var(--accent);text-decoration:none}
main{min-width:0;flex:1;padding:1rem 1.5rem 4rem;max-width:70rem}
h1{margin-top:0}h2{margin-top:2.5rem;border-bottom:1px solid var(--line);padding-bottom:.25rem}
code,pre{font-family:ui-monospace,monospace;font-size:.9em}
pre{background:var(--code);padding:.6rem .8rem;overflow:auto;white-space:pre-wrap}
table{border-collapse:collapse;width:100%;margin:.5rem 0}
th,td{border-top:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}
td:first-child{white-space:nowrap}
tr:target{background:var(--code);outline:2px solid var(--accent)}
.muted{color:var(--muted)}
@media (max-width:720px){body{display:block}nav{position:static;height:auto;width:auto;border:0;border-bottom:1px solid var(--line)}main{padding:1rem}table{display:block;overflow-x:auto}}
"""


def _description(cmd):
    """Command help as click prints it: dedented, `\\b` markers dropped."""
    lines = inspect.cleandoc(cmd.help or "").splitlines()
    return "\n".join(l for l in lines if l.strip() != "\b")


def _default(opt, ctx):
    d = opt.get_default(ctx)
    if d is None or d == ():
        return "none"
    if isinstance(d, bool):
        return "on" if d else "off"
    return str(d)


def _type(opt):
    if opt.is_flag:
        return "flag"
    return opt.type.name


OPTION_COLUMNS = ("Option", "Type", "Values", "Default", "Flags", "Help")


def option_cells(opt: click.Option, ctx: click.Context) -> tuple[str, str, str, str, str, str]:
    """The six cells of an option row, in OPTION_COLUMNS order (shared with the docs site)."""
    signature = opt.get_help_record(ctx)[0]
    values = ", ".join(opt.type.choices) if isinstance(opt.type, click.Choice) else ""
    marks = [m for m, on in (("required", opt.required), ("repeatable", opt.multiple)) if on]
    return (signature, _type(opt), values, _default(opt, ctx), ", ".join(marks), opt.help or "")


def _option_row(cmd_name, opt, ctx):
    long = next((o for o in opt.opts if o.startswith("--")), opt.opts[0]).lstrip("-")
    tds = "".join(f"<td>{_e(c)}</td>" for c in option_cells(opt, ctx))
    return f'<tr id="{_e(cmd_name)}--{_e(long)}">{tds}</tr>'


def _options_table(cmd_name, params, ctx):
    rows = "\n".join(_option_row(cmd_name, p, ctx) for p in params if isinstance(p, click.Option))
    head = "".join(f"<th>{h}</th>" for h in OPTION_COLUMNS)
    return f"<table><thead><tr>{head}</tr></thead><tbody>\n{rows}\n</tbody></table>"


def _arguments(params):
    items = []
    for p in params:
        if isinstance(p, click.Argument):
            flags = ("required" if p.required else "optional") + (", repeatable" if p.nargs == -1 else "")
            items.append(f"<li><code>{_e(p.human_readable_name)}</code> <span class=\"muted\">({_e(flags)})</span></li>")
    return f"<h3>Arguments</h3><ul>{''.join(items)}</ul>" if items else ""


def _section(name, cmd, parent_ctx):
    ctx = click.Context(cmd, info_name=name, parent=parent_ctx)
    params = cmd.get_params(ctx)
    usage = f"{ctx.command_path} {' '.join(cmd.collect_usage_pieces(ctx))}"
    return (
        f'<section id="{_e(name)}"><h2>{_e(name)}</h2>'
        f"<pre>{_e(_description(cmd))}</pre>"
        f"<p><strong>Usage:</strong> <code>{_e(usage)}</code></p>"
        f"{_arguments(params)}{_options_table(name, params, ctx)}</section>"
    )


def build_page(cli_group: click.Group) -> str:
    """Return the whole reference page for `cli_group`; pure, no I/O."""
    root = click.Context(cli_group, info_name=cli_group.name or "dograpper")
    commands = sorted(cli_group.commands.items())
    nav = '<a href="#global">Global options</a>' + "".join(
        f'<a href="#{_e(n)}">{_e(n)}</a>' for n, _ in commands)
    glob = (
        f'<section id="global"><h2>Global options</h2>'
        f"<pre>{_e(_description(cli_group))}</pre>"
        f"{_options_table('global', cli_group.get_params(root), root)}</section>"
    )
    body = glob + "".join(_section(n, c, root) for n, c in commands)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>dograpper reference</title><style>{_CSS}</style></head><body>"
        f"<nav><strong>dograpper</strong>{nav}</nav>"
        f"<main><h1>dograpper reference</h1>{body}</main></body></html>"
    )


def make_server(port: int, page: str) -> ThreadingHTTPServer:
    """Bind 127.0.0.1:`port` (0 = any free port) and return the unstarted server."""
    payload = page.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?", 1)[0] not in ("/", "/index.html"):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper docs\n"
        "  dograpper docs --port 9000 --no-browser\n"
    )
)
@click.option('--port', type=click.IntRange(1, 65535), default=8000, show_default=True,
              help="TCP port to listen on (127.0.0.1 only). If it is taken the command "
                   "fails; it never picks another port by itself.")
@click.option('--no-browser', is_flag=True, default=False,
              help="Only print the URL; do not open the default browser.")
@click.pass_context
def docs(ctx, port, no_browser):
    """Serve a local reference site for the CLI.

    Lists every command and option. Generated from the installed CLI, so it always matches `--help`. Works
    offline: the page has no external resources. Stop with Ctrl+C.
    """
    page = build_page(ctx.find_root().command)
    try:
        server = make_server(port, page)
    except OSError as e:
        click.echo(f"Error: cannot listen on 127.0.0.1:{port} ({e.strerror}). "
                   "Choose another port with --port.", err=True)
        ctx.exit(1)
    url = f"http://127.0.0.1:{port}/"
    click.echo(f"Serving the dograpper reference at {url} (Ctrl+C to stop)")
    try:
        if not no_browser:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        click.echo("Stopped.")
    finally:
        server.server_close()
