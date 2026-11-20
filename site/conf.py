import click
from docutils import nodes
from sphinx.util.docutils import SphinxDirective

project = "dograpper"
html_title = "dograpper"
extensions = ["myst_parser"]
html_theme = "furo"
myst_heading_anchors = 4
exclude_patterns = ["_build"]


class DograpperOptions(SphinxDirective):
    """Options table of one command, built from the click tree like `dograpper docs`."""

    required_arguments = 1

    def run(self):
        from dograpper.cli import cli
        from dograpper.commands.docs import OPTION_COLUMNS, option_cells

        name = self.arguments[0]
        root = click.Context(cli, info_name="dograpper")
        if name == "dograpper":
            cmd, ctx = cli, root
        elif name in cli.commands:
            cmd = cli.commands[name]
            ctx = click.Context(cmd, info_name=name, parent=root)
        else:
            raise self.error(f"dograpper-options: unknown command {name!r}")

        def row(cells, head=False):
            r = nodes.row()
            for i, text in enumerate(cells):
                para = nodes.paragraph()
                para += nodes.literal(text=text) if (i == 0 and not head) else nodes.Text(text)
                r += nodes.entry("", para)
            return r

        group = nodes.tgroup(cols=len(OPTION_COLUMNS))
        for _ in OPTION_COLUMNS:
            group += nodes.colspec(colwidth=1)
        group += nodes.thead("", row(OPTION_COLUMNS, head=True))
        body = nodes.tbody()
        for opt in cmd.get_params(ctx):
            if isinstance(opt, click.Option):
                body += row(option_cells(opt, ctx))
        group += body
        return [nodes.table("", group)]


def setup(app):
    app.add_directive("dograpper-options", DograpperOptions)
