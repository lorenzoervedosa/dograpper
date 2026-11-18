"""--changes (HTTrack -%d): hts-changes.json, as htschanges.c at 06ada4a writes it.

Each test runs `download --downloader httrack --changes` against the local `server`
fixture, or the engine directly, and reads the report back.
"""

import json
import os
import re

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.httrack.changes import CHANGES_FILE, json_string
from dograpper.lib.httrack.crawl import fetch_url_list
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.policy import build_policy
from dograpper.lib.manifest import build_manifest

HTML = {"content-type": "text/html"}
TXT = {"content-type": "text/plain"}
WORDS = " ".join(["documentation"] * 40)
DATE = re.compile(r'"date": "\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"')


def page(*links: str) -> bytes:
    return (f"<html><body><p>{WORDS}</p>"
            + "".join(f'<a href="{h}">{h}</a>' for h in links) + "</body></html>").encode()


def download(base, out, *args):
    res = CliRunner().invoke(cli, ["download", base + "/", "-o", str(out), "--downloader",
                                   "httrack", "--include-extensions", "html,txt", "--changes",
                                   *args])
    assert res.exit_code == 0, res.output
    return res.output


def read(out):
    """The report with its date masked, and parsed."""
    text = (out / CHANGES_FILE).read_text(encoding="utf-8")
    assert len(DATE.findall(text)) == 1
    return DATE.sub('"date": "D"', text), json.loads(text)


@pytest.mark.parametrize("value, expected", [
    ('a"b\\c', '"a\\"b\\\\c"'),
    ("tab\there\x7f", '"tab\\u0009here\\u007f"'),
    ("é/ü", '"é/ü"'),              # well-formed UTF-8 verbatim, "/" not escaped
    ("bad\udc80byte", '"bad\\ufffdbyte"'),  # an undecodable name byte (surrogateescape)
])
def test_json_strings_are_escaped_as_hts_json_string(value, expected):
    """htscharset.c:1268-1303."""
    assert json_string(value) == expected


def test_first_crawl_reports_every_file_new_in_httrack_format(server, tmp_path):
    """htschanges.c:457-532: the layout, the counts on one line, one entry per line; a first
    crawl (no previous index) has first_crawl true and its own summary (595-597)."""
    base, script, _ = server
    host = base.split("//")[1]
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (200, HTML, page("a.html", "n.txt"))
    script["/a.html"] = (200, HTML, page())
    script["/n.txt"] = (200, TXT, b"notes")
    out = tmp_path / "m"
    output = download(base, out)
    text, data = read(out)
    sizes = {f: os.path.getsize(out / host / f) for f in ("index.html", "a.html", "n.txt")}
    assert text == (
        '{\n  "schema": 1,\n  "generator": ' + json_string(data["generator"]) + ',\n'
        '  "date": "D",\n  "first_crawl": true,\n  "partial": false,\n  "purged": false,\n'
        '  "counts": { "new": 3, "changed": 0, "unchanged": 0, "gone": 0 },\n'
        '  "new": [\n'
        f'    {{ "url": "{base}/", "file": "{host}/index.html", "size": {sizes["index.html"]} }},\n'
        f'    {{ "url": "{base}/a.html", "file": "{host}/a.html", "size": {sizes["a.html"]} }},\n'
        f'    {{ "url": "{base}/n.txt", "file": "{host}/n.txt", "size": 5 }}\n'
        '  ],\n  "changed": [],\n  "unchanged": [],\n  "gone": []\n}\n')
    assert data["generator"].startswith("dograpper/")
    assert ("Change report: first crawl, 3 files mirrored, nothing to compare against "
            "(hts-changes.json)") in output


def test_an_update_sorts_each_file_as_htschanges_c(server, tmp_path):
    """htschanges.c:189-206, 299-345, 407-455 and htscore.c:2186-2210, on a second run:
    - a page whose payload is the same is unchanged, though its saved bytes moved (a link
      it carries now reaches a saved file, so -K0 rewrote it);
    - a page whose payload changed is changed, with its previous size (the start page links
      to other pages now);
    - a text file rewritten with the same bytes is unchanged, one with other bytes of the
      same size changed (MD5 of the file before and after);
    - a page new to the site is new, one kept by a 304 unchanged;
    - a file of the previous run no link reaches is gone (no size); one the run requested
      without keeping it (it now redirects off the host) is unchanged, with no URL."""
    base, script, _ = server
    host = base.split("//")[1]
    lm = {"last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"}

    def kept304(body):
        def reply(h):
            if h.get("If-None-Match") == '"k"':
                return 304, {"etag": '"k"'}, b""
            return 200, {**HTML, "etag": '"k"'}, body
        return reply
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (200, {**HTML, **lm}, page("a.html", "b.html", "n.txt", "m.txt", "k.html",
                                              "r.html", "g.html"))
    script["/a.html"] = (200, HTML, page("x.html"))  # x.html: 404 on the first run
    script["/b.html"] = (200, HTML, page())
    script["/n.txt"] = (200, TXT, b"same")
    script["/m.txt"] = (200, TXT, b"old!")
    script["/k.html"] = kept304(page())
    script["/r.html"] = (200, HTML, page())
    script["/g.html"] = (200, HTML, page())
    out = tmp_path / "m"
    download(base, out)
    a_before = (out / host / "a.html").read_bytes()
    b_size = os.path.getsize(out / host / "b.html")
    script["/"] = (200, {**HTML, **lm}, page("a.html", "b.html", "n.txt", "m.txt", "k.html",
                                              "r.html", "c.html"))
    script["/b.html"] = (200, HTML, page("more"))
    script["/m.txt"] = (200, TXT, b"new!")
    script["/x.html"] = (200, HTML, page())
    script["/c.html"] = (200, HTML, page())
    script["/r.html"] = (301, {"location": "http://elsewhere.invalid/r"}, b"")
    output = download(base, out)
    assert (out / host / "a.html").read_bytes() != a_before  # relinked to x.html
    _, data = read(out)
    files = {b: [(e["url"], e["file"].split("/", 1)[1]) for e in data[b]] for b in
             ("new", "changed", "unchanged", "gone")}
    assert files == {
        "new": [(f"{base}/c.html", "c.html"), (f"{base}/x.html", "x.html")],
        "changed": [(f"{base}/", "index.html"), (f"{base}/b.html", "b.html"),
                    (f"{base}/m.txt", "m.txt")],
        "unchanged": [(f"{base}/a.html", "a.html"), (f"{base}/n.txt", "n.txt"),
                      (f"{base}/k.html", "k.html"), ("", "r.html")],
        "gone": [("", "g.html")]}
    changed = {e["file"].split("/", 1)[1]: e for e in data["changed"]}
    assert changed["b.html"]["previous_size"] == b_size
    assert changed["m.txt"]["previous_size"] == 4 == changed["m.txt"]["size"]
    assert "size" not in data["gone"][0] and "previous_size" not in data["unchanged"][0]
    assert data["first_crawl"] is False and data["counts"] == {
        "new": 2, "changed": 3, "unchanged": 4, "gone": 1}
    assert "Change report: 2 new, 3 changed, 4 unchanged, 1 gone (hts-changes.json)" in output


def test_cache_0_has_no_index_and_compares_what_was_on_disk(server, tmp_path):
    """-C0 opens no file list (htscore.c:2147): first_crawl is null, nothing is gone, and a
    file counts as existing when it was on disk; with no cache to read, a page rewritten
    is changed even with the same payload (no digest, a 200), a text file is compared by
    MD5 (htschanges.c:201-205, 588-592)."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (200, HTML, page("n.txt", "a.html", "g.html"))
    script["/n.txt"] = (200, TXT, b"same")
    script["/a.html"] = (200, HTML, page())
    script["/g.html"] = (200, HTML, page())
    out = tmp_path / "m"
    download(base, out)
    script["/"] = (200, HTML, page("n.txt", "a.html"))
    output = download(base, out, "--cache", "0")
    _, data = read(out)
    assert data["first_crawl"] is None and data["gone"] == []
    assert [e["file"].rsplit("/", 1)[1] for e in data["changed"]] == ["index.html", "a.html"]
    assert [e["file"].rsplit("/", 1)[1] for e in data["unchanged"]] == ["n.txt"]
    assert ("Change report: no mirror index (the cache is off), 3 files mirrored, "
            "deletions not detected (hts-changes.json)") in output


def test_seeded_entries_follow_the_seed_order(server, tmp_path):
    """The seeds are fetched on several threads; the report lists them in seed order."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    for name in ("z", "a", "m"):
        script[f"/{name}"] = (200, HTML, page())
    policy = build_policy(retries=0, changes=True, connections=3)
    res = fetch_url_list([f"{base}/z", f"{base}/a", f"{base}/m"], str(tmp_path), policy, "html",
                         fetcher=Fetcher(policy))
    data = json.loads(res.changes[0])
    assert [e["url"] for e in data["new"]] == [f"{base}/z", f"{base}/a", f"{base}/m"]


def test_a_url_off_the_allowlist_is_reported_without_its_query(server, tmp_path):
    """The manifest's rule for the URL requested (redact.recordable_url): a query parameter
    off the navigation allowlist gives "" (HTTrack's "no URL"), never the URL."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/p?token=s3cret"] = (200, HTML, page())
    policy = build_policy(retries=0, changes=True)
    res = fetch_url_list([f"{base}/p?token=s3cret"], str(tmp_path), policy, "html",
                         fetcher=Fetcher(policy))
    assert "s3cret" not in res.changes[0]
    assert json.loads(res.changes[0])["new"][0]["url"] == ""


def test_off_by_default_and_never_written_for_a_failed_run(server, tmp_path):
    """-%d is off (htslib.c:5441); a run that fails keeps the previous report, as HTTrack
    writes one only for a completed run (htscore.c:2360-2367)."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (200, HTML, page("a.html"))
    script["/a.html"] = (200, HTML, page())
    out = tmp_path / "m"
    res = CliRunner().invoke(cli, ["download", base + "/", "-o", str(out),
                                   "--downloader", "httrack"])
    assert res.exit_code == 0, res.output
    assert not (out / CHANGES_FILE).exists()
    (out / CHANGES_FILE).write_text("previous")
    script["/robots.txt"] = (200, TXT, b"User-agent: *\nDisallow: /\n")  # a front failure
    res = CliRunner().invoke(cli, ["download", base + "/", "-o", str(out),
                                   "--downloader", "httrack", "--changes"])
    assert res.exit_code == 1, res.output
    assert (out / CHANGES_FILE).read_text() == "previous"


def test_the_report_is_no_mirror_content(server, tmp_path):
    """Like the manifest: never listed by build_manifest, never packed."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (200, HTML, page("a.html"))
    script["/a.html"] = (200, HTML, page())
    out = tmp_path / "m"
    download(base, out)
    assert all(e.local_path != CHANGES_FILE
               for e in build_manifest(base, str(out)).files.values())
    res = CliRunner().invoke(cli, ["pack", str(out), "-o", str(tmp_path / "c"),
                                   "--include-extensions", "html,json"])
    assert res.exit_code == 0, res.output
    assert "hts-changes" not in "".join(p.read_text() for p in (tmp_path / "c").glob("*.md"))
