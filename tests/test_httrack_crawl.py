import os
import threading

import pytest

from dograpper.lib.httrack.crawl import fetch_url_list
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.policy import build_policy
from dograpper.lib.httrack.report import RunReport, format_report

HTML = {"content-type": "text/html"}


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.lock = threading.Lock()

    def clock(self):
        return self.now

    def sleep(self, s):
        with self.lock:
            self.now += s


def run(urls, out, exts="html", **kw):
    policy = build_policy(retries=0, **kw)
    ft = FakeTime()
    return fetch_url_list(urls, str(out), policy, exts,
                          fetcher=Fetcher(policy, clock=ft.clock, sleep=ft.sleep))


def test_writes_only_2xx_non_challenge(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/ok"] = (200, HTML, b"<p>ok</p>")
    script["/gone"] = (404, HTML, b"<p>gone</p>")
    script["/cf"] = (403, {**HTML, "cf-mitigated": "challenge"}, b"<p>x</p>")
    res = run([f"{base}/ok", f"{base}/gone", f"{base}/cf"], tmp_path)
    assert len(res.files_downloaded) == 1 and res.files_downloaded[0].endswith("ok.html")
    assert open(res.files_downloaded[0], "rb").read() == b"<p>ok</p>"
    assert res.success and not res.front_failed and res.files_skipped == 0
    assert res.report.challenged == [f"{base}/cf"]
    assert [e[:2] for e in res.report.errors] == [(f"{base}/gone", "HTTP 404")]
    assert res.report.status_counts["2xx"] == 1 and res.report.status_counts["4xx"] == 2
    assert sum(len(f) for _, _, f in os.walk(tmp_path)) == 1


def test_robots_blocked_not_fetched(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /private\n")
    script["/private/a"] = (200, HTML, b"secret")
    res = run([f"{base}/private/a"], tmp_path)
    assert "/private/a" not in seen
    assert res.report.robots_blocked == [f"{base}/private/a"]
    assert res.files_downloaded == [] and res.front_failed


def test_cross_host_redirect_reported_out_of_scope(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/go"] = (302, {"location": "http://example.invalid/x"}, b"")
    res = run([f"{base}/go"], tmp_path)
    assert res.report.out_of_scope == ["http://example.invalid/x"]
    assert res.files_downloaded == [] and not res.front_failed


def test_same_host_redirect_is_followed_and_final_url_named(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/new"] = (200, HTML, b"<p>n</p>")
    res = run([f"{base}/old"], tmp_path)
    assert [os.path.basename(f) for f in res.files_downloaded] == ["new.html"]


def test_redirect_target_refused_by_filters_is_not_fetched(server, tmp_path):
    from dograpper.lib.url_filter import UrlFilters
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/Special:Login"}, b"")
    script["/Special:Login"] = (200, HTML, b"<p>login</p>")
    filters = UrlFilters(["-*Special:*"])
    policy = build_policy(retries=0)
    ft = FakeTime()
    res = fetch_url_list([f"{base}/old"], str(tmp_path), policy, "html",
                         fetcher=Fetcher(policy, clock=ft.clock, sleep=ft.sleep), filters=filters)
    assert res.files_downloaded == [] and not res.front_failed
    assert "/Special:Login" not in seen
    assert filters.excluded == {f"{base}/Special:Login"}


def test_redirect_with_undecodable_body_is_followed(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/new", "content-encoding": "gzip"}, b"not gzip")
    script["/new"] = (200, HTML, b"<p>n</p>")
    res = run([f"{base}/old"], tmp_path)
    assert [os.path.basename(f) for f in res.files_downloaded] == ["new.html"]
    assert res.report.errors == [] and res.report.status_counts["3xx"] == 1


def test_redirect_loop_is_an_error(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (302, {"location": "/a"}, b"")
    res = run([f"{base}/a"], tmp_path)
    assert res.report.errors == [(f"{base}/a", "too many redirects", None)]


def test_front_failed_when_all_challenged(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    for p in ("/a", "/b"):
        script[p] = (403, {**HTML, "cf-mitigated": "challenge"}, b"")
    res = run([f"{base}/a", f"{base}/b"], tmp_path)
    assert res.front_failed and not res.success and res.files_downloaded == []


def test_max_links_sets_partial(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    for p in ("/a", "/b", "/c"):
        script[p] = (200, HTML, b"<p>x</p>")
    res = run([f"{base}/a", f"{base}/b", f"{base}/c"], tmp_path, max_links=2)
    assert res.report.partial and len(res.files_downloaded) == 2
    assert "/c" not in seen


def test_include_extensions_filters_written_files(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/p"] = (200, HTML, b"<p>x</p>")
    script["/i.png"] = (200, {"content-type": "image/png"}, b"\x89PNG")
    res = run([f"{base}/p", f"{base}/i.png"], tmp_path, exts="html")
    assert [os.path.basename(f) for f in res.files_downloaded] == ["p.html"]


def test_write_conflict_is_recorded_and_run_continues(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (200, {"content-type": "text/plain"}, b"x")
    script["/a/b"] = (200, {"content-type": "text/plain"}, b"y")
    res = run([f"{base}/a", f"{base}/a/b"], tmp_path, exts="", connections=1)
    assert len(res.files_downloaded) == 1
    assert len(res.report.errors) == 1 and res.report.errors[0][1].startswith("write failed")


def test_cdn_cgi_skipped_without_request(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    res = run([f"{base}/cdn-cgi/trace"], tmp_path)
    assert "/cdn-cgi/trace" not in seen
    assert res.report.out_of_scope == [f"{base}/cdn-cgi/trace"]


def test_report_urls_are_redacted(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    url = base.replace("http://", "http://user:pw@") + "/missing"
    res = run([url], tmp_path)
    assert res.report.errors[0][0] == f"{base}/missing"


def test_format_report_truncates_errors_unless_verbose():
    r = RunReport(errors=[(f"http://h/{i:02d}", "HTTP 500", None) for i in range(15)])
    short = "\n".join(format_report(r, verbose=False))
    full = "\n".join(format_report(r, verbose=True))
    assert "http://h/09" in short and "http://h/10" not in short and "5 more" in short
    assert "http://h/14" in full and "more" not in full


def test_seeds_redirecting_to_one_target_write_one_file(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (301, {"location": "/t"}, b"")
    script["/b"] = (301, {"location": "/t"}, b"")
    script["/t"] = (200, HTML, b"<p>t</p>")
    res = run([f"{base}/a", f"{base}/b", f"{base}/t"], tmp_path)
    assert [os.path.basename(f) for f in res.files_downloaded] == ["t.html"]
    assert list(res.urls.values()) == [f"{base}/t"]  # the seed that needed no redirect


def test_seeds_redirecting_to_one_file_record_the_smallest_url(server, tmp_path):
    """Whichever thread writes first, the manifest gets the same URL."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/b"] = (301, {"location": "/t"}, b"")
    script["/a"] = (301, {"location": "/t"}, b"")
    script["/t"] = (200, HTML, b"<p>t</p>")
    res = run([f"{base}/b", f"{base}/a"], tmp_path)
    assert list(res.urls.values()) == [f"{base}/a"]


def test_each_written_file_maps_to_the_url_fetched(server, tmp_path):
    """#94: the manifest records these instead of rebuilding a URL from the name."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/wiki/Category:En"] = (200, HTML, b"<p>c</p>")
    script["/w/index.php?title=A"] = (200, HTML, b"<p>q</p>")
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/new"] = (200, HTML, b"<p>n</p>")
    script["/gone"] = (404, HTML, b"<p>x</p>")
    res = run([f"{base}/wiki/Category:En", f"{base}/w/index.php?title=A", f"{base}/old",
               f"{base}/gone"], tmp_path)
    assert sorted(res.urls) == res.files_downloaded
    by_name = {os.path.basename(f): u for f, u in res.urls.items()}
    assert by_name.pop("Category_En.html") == f"{base}/wiki/Category:En"
    assert by_name.pop("new.html") == f"{base}/old"  # named after the target, URL as requested
    assert list(by_name.values()) == [f"{base}/w/index.php?title=A"]


def test_malformed_seed_is_recorded_and_run_continues(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/ok"] = (200, HTML, b"<p>ok</p>")
    res = run(["http://[x", f"{base}/ok"], tmp_path)
    assert len(res.files_downloaded) == 1
    assert res.report.errors == [("<redacted url>", "malformed URL", None)]


def test_malformed_redirect_location_is_recorded(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/r"] = (302, {"location": "http://[x"}, b"")
    res = run([f"{base}/r"], tmp_path)
    assert res.report.errors == [(f"{base}/r", "malformed redirect Location", None)]


def test_filtered_pages_are_reported(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/i.png"] = (200, {"content-type": "image/png"}, b"\x89PNG")
    res = run([f"{base}/i.png"], tmp_path, exts="html")
    assert res.report.filtered == [f"{base}/i.png"] and res.files_downloaded == []
    short = "\n".join(format_report(res.report, verbose=False))
    full = "\n".join(format_report(res.report, verbose=True))
    assert "Filtered by --include-extensions: 1" in short and "i.png" not in short
    assert f"{base}/i.png" in full


def test_control_chars_in_location_never_reach_the_report(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/r"] = (302, {"location": "http://example.invalid/\x1b[31mx\x9by"}, b"")
    res = run([f"{base}/r"], tmp_path)
    out = "\n".join(format_report(res.report, verbose=True))
    assert "\x1b" not in out and "\r" not in out and "example.invalid" in out


def test_format_report_escapes_control_chars_in_reasons():
    r = RunReport(errors=[("http://h/x", "bad \x1b[31m thing\x07", "http://h/\x1b")])
    out = "\n".join(format_report(r, verbose=True))
    assert "\x1b" not in out and "\x07" not in out and "\\x1b" in out


@pytest.mark.parametrize("rule,seed,wire", [
    ("/a%20b", "/a b", "/a%20b"),
    ("/caf%C3%A9", "/caf\u00e9", "/caf%c3%a9"),
    ("/caf%c3%a9", "/caf\u00e9", "/caf%c3%a9"),
])
def test_robots_matches_escaped_wire_target(server, tmp_path, rule, seed, wire):
    base, script, seen = server
    script["/robots.txt"] = (200, {"content-type": "text/plain"},
                             f"User-agent: *\nDisallow: {rule}\n".encode())
    script[wire] = (200, HTML, b"x")
    res = run([base + seed], tmp_path)
    assert wire not in seen and len(res.report.robots_blocked) == 1


def test_robots_allows_other_encoded_path(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (200, {"content-type": "text/plain"},
                             b"User-agent: *\nDisallow: /a%20b\n")
    script["/c%20d"] = (200, HTML, b"x")
    res = run([f"{base}/c d"], tmp_path)
    assert "/c%20d" in seen and res.report.robots_blocked == []


def test_progress_counts_the_seeds_of_the_list(server, tmp_path, caplog):
    """[progress] in the fixed-list shape of wget -i: seeds done of the list and the
    bytes written; a redirect onto a file another seed wrote adds no bytes."""
    import logging
    import re
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/big"] = (200, HTML, b"x" * 1_200_000)
    script["/gone"] = (404, HTML, b"<p>gone</p>")
    script["/old"] = (301, {"location": "/big"}, b"")
    with caplog.at_level(logging.INFO, logger="dograpper"):
        run([f"{base}/big", f"{base}/gone", f"{base}/old"], tmp_path)
    progress = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[progress]")]
    assert progress and re.fullmatch(r"\[progress\] httrack: 3/3 URLs \(100%\) · 1\.1 MB · \d+s",
                                     progress[-1]), progress


def test_links_between_seeded_pages_are_rewritten(server, tmp_path):
    """-K0, as wget -i --convert-links: saved targets become relative paths, others absolute."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/a"] = (200, HTML, b'<a href="b">b</a> <a href="/docs/old">o</a> <a href="/x">x</a>')
    script["/docs/b"] = (200, HTML, b'<a href="a#top">a</a>')
    script["/docs/old"] = (301, {"location": "/docs/new/"}, b"")
    script["/docs/new/"] = (200, HTML, b'<a href="../a">a</a>')
    script["/docs/t.txt"] = (200, {"content-type": "text/plain"}, b'<a href="b">raw</a>')
    res = run([f"{base}/docs/a", f"{base}/docs/b", f"{base}/docs/old", f"{base}/docs/t.txt"],
              tmp_path, exts="html,txt")
    docs = tmp_path / base.split("//")[1] / "docs"
    assert (docs / "a.html").read_bytes() == (
        f'<a href="b.html">b</a> <a href="new/index.html">o</a> <a href="{base}/x">x</a>'.encode())
    assert (docs / "b.html").read_bytes() == b'<a href="a.html#top">a</a>'
    # resolved against the URL the page came from after the redirect, not the seed
    assert (docs / "new" / "index.html").read_bytes() == b'<a href="../a.html">a</a>'
    assert (docs / "t.txt").read_bytes() == b'<a href="b">raw</a>'  # only HTML is rewritten
    assert res.report.errors == []



def test_seeded_scripts_and_stylesheets_are_rewritten(server, tmp_path):
    """The links the script scans take, in a page and in a seeded stylesheet, are
    rewritten too (htsparse.c:3379-3502, 3807-3852); a seed is a start URL, so no page
    loaded it and its links resolve against itself (htsparse.c:1280-1285)."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/a"] = (200, HTML, b'<script>img.src = "b";</script>')
    script["/docs/b"] = (200, HTML, b"<p>b</p>")
    script["/docs/s.css"] = (200, {"content-type": "text/css"}, b"p{background:url(b)}")
    res = run([f"{base}/docs/a", f"{base}/docs/b", f"{base}/docs/s.css"], tmp_path,
              exts="html,css")
    docs = tmp_path / base.split("//")[1] / "docs"
    assert (docs / "a.html").read_bytes() == b'<script>img.src = "b.html";</script>'
    assert (docs / "s.css").read_bytes() == b"p{background:url(b.html)}"
    assert res.report.errors == []
    run([f"{base}/docs/a", f"{base}/docs/b"], tmp_path / "off", parse_scripts=False)
    assert (tmp_path / "off" / docs.relative_to(tmp_path) / "a.html").read_bytes() == (
        b'<script>img.src = "b";</script>')

# -- update mode: the previous run's manifest records drive conditional revalidation --

from dograpper.lib.manifest import build_manifest  # noqa: E402

LM = "Mon, 01 Jan 2024 00:00:00 GMT"


def again(res, base, out):
    """The manifest a download would save after `res`."""
    return build_manifest(base + "/", str(out), res.urls, records=res.records)


def run_update(urls, out, previous, exts="html", **kw):
    policy = build_policy(**{"retries": 0, **kw})
    ft = FakeTime()
    return fetch_url_list(urls, str(out), policy, exts, previous=previous,
                          fetcher=Fetcher(policy, clock=ft.clock, sleep=ft.sleep))


def validated(etag, body, then=None, log=None):
    """A page that answers 304 to its ETag, else `then` (default: 200 with `body`)."""
    def reply(h):
        if log is not None:
            log.append({k: h[k] for k in ("If-None-Match", "If-Modified-Since") if k in h})
        if h.get("If-None-Match") == etag:
            return then or (304, {"etag": etag}, b"")
        return (200, {**HTML, "etag": etag, "last-modified": LM}, body)
    return reply


def test_first_run_records_what_a_revalidation_needs(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (200, {**HTML, "etag": '"a1"', "last-modified": LM}, b"<p>a</p>")
    script["/d"] = (200, HTML, b"<p>d</p>")  # http.server always sends Date
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/new"] = (200, {**HTML, "etag": '"n1"'}, b"<p>n</p>")
    res = run([f"{base}/a", f"{base}/d", f"{base}/old"], tmp_path)
    recs = {os.path.basename(p): r for p, r in res.records.items()}
    assert recs["a.html"] == {"status": 200, "content_type": "text/html", "etag": '"a1"',
                              "last_modified": LM, "redirected": False}
    assert recs["d.html"]["etag"] is None and recs["d.html"]["last_modified"].endswith(" GMT")
    assert recs["new.html"]["redirected"] is True and recs["new.html"]["etag"] == '"n1"'


def test_304_keeps_the_previous_copy_byte_identical(server, tmp_path):
    base, script, _ = server
    log = []
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = validated('"a1"', b'<a href="b">b</a>', log=log)
    script["/b"] = validated('"b1"', b"<p>b</p>")
    first = run([f"{base}/a", f"{base}/b"], tmp_path)
    a = tmp_path / base.split("//")[1] / "a.html"
    before = a.read_bytes()
    assert before == b'<a href="b.html">b</a>'  # relinked by the first run
    log.clear()
    script["/b"] = validated('"b2"', b"<p>b changed</p>")
    res = run_update([f"{base}/a", f"{base}/b"], tmp_path, again(first, base, tmp_path))
    assert log == [{"If-None-Match": '"a1"', "If-Modified-Since": LM}]
    assert a.read_bytes() == before  # neither rewritten nor relinked
    assert [os.path.basename(f) for f in res.files_downloaded] == ["b.html"]
    assert [os.path.basename(f) for f in res.kept] == ["a.html"] and res.files_skipped == 1
    assert res.report.not_modified == 1 and res.report.errors == [] and res.success
    assert res.records[str(a.resolve())] == first.records[str(a.resolve())]
    assert res.urls[str(a.resolve())] == f"{base}/a"


@pytest.mark.parametrize("reply,reason", [
    ((404, HTML, b"<p>gone</p>"), "HTTP 404"),
    ((500, HTML, b"<p>oops</p>"), "HTTP 500"),
])
def test_answered_error_on_update_keeps_the_copy_without_retry(server, tmp_path, reply, reason):
    """htsback.c:4266-4280: masked as a 304, so htsmirror.c never retries it."""
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = validated('"a1"', b"<p>a</p>")
    first = run([f"{base}/a"], tmp_path)
    script["/a"] = validated('"a1"', b"", then=reply)
    seen.clear()
    res = run_update([f"{base}/a"], tmp_path, again(first, base, tmp_path), retries=2)
    assert seen.count("/a") == 1
    assert res.report.kept == [(f"{base}/a", reason)] and res.report.errors == []
    assert open(res.kept[0], "rb").read() == b"<p>a</p>"
    assert not res.front_failed and res.success and res.files_downloaded == []


def test_challenged_revalidation_keeps_the_copy_and_is_still_a_front_failure(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = validated('"a1"', b"<p>a</p>")
    first = run([f"{base}/a"], tmp_path)
    script["/a"] = validated('"a1"', b"", then=(403, {**HTML, "cf-mitigated": "challenge"},
                                                b"<title>Just a moment...</title>"))
    res = run_update([f"{base}/a"], tmp_path, again(first, base, tmp_path))
    assert res.report.challenged == [f"{base}/a"] and res.front_failed
    assert open(first.files_downloaded[0], "rb").read() == b"<p>a</p>"


def test_failed_transfer_on_update_is_an_error_and_keeps_the_copy(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = validated('"a1"', b"<p>a</p>")
    first = run([f"{base}/a"], tmp_path)
    script["/a"] = validated('"a1"', b"", then=(200, {**HTML, "content-encoding": "gzip"},
                                                b"not gzip"))
    res = run_update([f"{base}/a"], tmp_path, again(first, base, tmp_path))
    assert [e[0] for e in res.report.errors] == [f"{base}/a"] and res.front_failed
    assert open(first.files_downloaded[0], "rb").read() == b"<p>a</p>"
    assert res.kept == first.files_downloaded and res.records == first.records  # #746, #1421


def test_changed_page_is_rewritten_with_its_new_record(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = validated('"a1"', b"<p>a</p>")
    first = run([f"{base}/a"], tmp_path)
    script["/a"] = validated('"a2"', b"<p>a, new</p>")
    res = run_update([f"{base}/a"], tmp_path, again(first, base, tmp_path))
    path = res.files_downloaded[0]
    assert open(path, "rb").read() == b"<p>a, new</p>" and res.records[path]["etag"] == '"a2"'
    assert res.kept == [] and res.report.not_modified == 0


@pytest.mark.parametrize("erase", [os.remove, lambda p: open(p, "wb").close()])
def test_file_erased_since_is_refetched_unconditionally(server, tmp_path, erase):
    """htsback.c:2414-2492: a file missing or empty is fetched again, "Previous file not
    found (erased by user ?), recatching"."""
    base, script, _ = server
    log = []
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = validated('"a1"', b"<p>a</p>", log=log)
    first = run([f"{base}/a"], tmp_path)
    previous = again(first, base, tmp_path)
    erase(first.files_downloaded[0])
    log.clear()
    res = run_update([f"{base}/a"], tmp_path, previous)
    assert log == [{}] and open(res.files_downloaded[0], "rb").read() == b"<p>a</p>"


def test_redirected_seed_revalidates_its_target_only(server, tmp_path):
    """HTTrack's cache holds the redirect (sent plain) and the target's 200 (sent its
    validators); the manifest never records the target, so the chain carries them."""
    base, script, _ = server
    old, new = [], []
    script["/robots.txt"] = (404, {}, b"")

    def moved(h):
        old.append(h.get("If-None-Match"))
        return (301, {"location": "/new"}, b"")
    script["/old"] = moved
    script["/new"] = validated('"n1"', b"<p>n</p>", log=new)
    first = run([f"{base}/old"], tmp_path)
    old.clear(), new.clear()
    res = run_update([f"{base}/old"], tmp_path, again(first, base, tmp_path))
    assert old == [None] and new == [{"If-None-Match": '"n1"', "If-Modified-Since": LM}]
    assert [os.path.basename(f) for f in res.kept] == ["new.html"]
    assert res.records[res.kept[0]]["redirected"] is True


def test_format_report_lists_what_an_update_kept():
    r = RunReport(not_modified=3, kept=[("http://h/gone", "HTTP 404")],
                  unreached=["http://h/old", "h/loose.html"])
    short = format_report(r, verbose=False)
    assert short[1:] == ["Not modified (304): 3", "Kept the previous copy after an error: 1",
                         "Not reached this run, kept on disk: 2"]
    full = format_report(r, verbose=True)
    assert "  http://h/gone: HTTP 404" in full and "  h/loose.html" in full
    assert format_report(RunReport(), verbose=True) == format_report(RunReport(), False)


def test_redirected_record_is_never_sent_to_another_target(server, tmp_path):
    """A redirect that now leads elsewhere: the new target is fetched in full, never
    revalidated with the old target's date (it would answer 304 for the wrong page)."""
    base, script, _ = server
    log = []

    def since(body):
        def reply(h):
            log.append(h.get("If-Modified-Since"))
            return (304, {}, b"") if h.get("If-Modified-Since") else (
                200, {**HTML, "last-modified": LM}, body)
        return reply
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/new"] = since(b"<p>new</p>")
    first = run([f"{base}/old"], tmp_path)
    script["/old"] = (301, {"location": "/other"}, b"")
    script["/other"] = since(b"<p>other</p>")
    log.clear()
    res = run_update([f"{base}/old"], tmp_path, again(first, base, tmp_path))
    host = tmp_path / base.split("//")[1]
    assert log == [None] and res.kept == []
    assert (host / "other.html").read_bytes() == b"<p>other</p>"
    assert (host / "new.html").read_bytes() == b"<p>new</p>"  # untouched, not reached


def test_seed_with_userinfo_updates_its_own_file(server, tmp_path):
    """The manifest drops user:password@; the update still finds the file it recorded."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = validated('"a1"', b"<p>a v1</p>")
    auth = base.replace("http://", "http://u:p@")
    first = run([f"{auth}/a"], tmp_path)
    script["/a"] = validated('"a2"', b"<p>a v2</p>")
    res = run_update([f"{auth}/a"], tmp_path, again(first, base, tmp_path))
    host = tmp_path / base.split("//")[1]
    assert sorted(os.listdir(host)) == ["a.html"] and res.files_downloaded == first.files_downloaded
    assert (host / "a.html").read_bytes() == b"<p>a v2</p>"


def test_edited_manifest_never_chooses_where_a_page_is_written(server, tmp_path):
    from dograpper.lib.manifest import Manifest, ManifestEntry
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (200, {**HTML, "etag": '"a2"'}, b"<p>page a</p>")
    (tmp_path / "notes.txt").write_bytes(b"my own notes")
    entry = dict(size_bytes=1, etag='"a1"', status=200, content_type="text/html")
    previous = Manifest(base, "", {
        "x": ManifestEntry(url=f"{base}/a", local_path="notes.txt", **entry),
        "y": ManifestEntry(url="http://[bad", local_path="notes.txt", **entry)})
    res = run_update([f"{base}/a"], tmp_path, previous, exts="html,txt")
    assert (tmp_path / "notes.txt").read_bytes() == b"my own notes"
    assert [os.path.basename(f) for f in res.files_downloaded] == ["a.html"]


class WireSpy(Fetcher):
    """Records the headers each GET puts on the wire (robots.txt left out)."""

    def __init__(self, policy):
        ft = FakeTime()
        super().__init__(policy, clock=ft.clock, sleep=ft.sleep)
        self.sent = {}

    def _request(self, key, parts, target, headers):
        if target != "/robots.txt":
            self.sent[target] = dict(headers)
        return super()._request(key, parts, target, headers)


def test_seed_redirect_target_is_requested_as_htsmirror_c_requests_it(server, tmp_path):
    # hts_mirror_check_moved (htsmirror.c:131-325): a page target is a link of the stub
    # standing for the seed, so the seed is its Referer (back_add gets heap(precedent),
    # htscore.c:3424-3426), without its login or fragment (htslib.c:1136-1163); a known
    # non-page target is a fresh link with the seed's parent, the primary link, which sends
    # no Referer (htsback.c:2332). A start URL's chain keeps Sec-Fetch-Site none.
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/new"] = (200, HTML, b"<p>n</p>")
    script["/doc"] = (302, {"location": "/f.txt"}, b"")
    script["/f.txt"] = (200, {"content-type": "text/plain"}, b"t")
    script["/gone"] = (301, {"location": "/missing"}, b"")
    policy = build_policy(retries=0)
    spy = WireSpy(policy)
    host = base.split("//")[1]
    res = fetch_url_list([f"http://u:pw@{host}/old#frag", f"{base}/doc", f"{base}/gone"],
                         str(tmp_path), policy, "html,txt", fetcher=spy)
    assert sorted(os.path.basename(f) for f in res.files_downloaded) == ["f.txt", "new.html"]
    new, txt = spy.sent["/new"], spy.sent["/f.txt"]
    assert new["Referer"] == f"{base}/old"
    assert (new["Sec-Fetch-Site"], new["Sec-Fetch-Mode"], new["Sec-Fetch-Dest"]) == (
        "none", "navigate", "document")
    assert "Referer" not in txt and txt["Sec-Fetch-Site"] == "none"
    assert "Referer" not in spy.sent["/old"] and "Referer" not in spy.sent["/doc"]
    # the report names the referrer of the failed request, as htsmirror.c:462-482 logs it
    assert [e for e in res.report.errors] == [(f"{base}/missing", "HTTP 404", f"{base}/gone")]


def test_failed_write_leaves_no_seed_counted_for_the_shared_file(server, tmp_path, monkeypatch):
    """Two seeds reaching one file: the write fails, so neither counts as written (#134)."""
    from dograpper.lib.httrack import crawl

    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (301, {"location": "/t"}, b"")
    script["/b"] = (301, {"location": "/t"}, b"")
    script["/t"] = (200, HTML, b"<p>t</p>")
    second_seed_done, first = threading.Event(), threading.Event()
    real_reporter = crawl.ProgressReporter

    class Reporter(real_reporter):
        def update(self, *a, **kw):  # run() calls it when a seed has an outcome
            second_seed_done.set()
            super().update(*a, **kw)

    def failing_write(path, body):
        if not first.is_set():  # the first writer holds the claim until the other seed
            first.set()         # has an outcome; a seed that must wait for the write never
            second_seed_done.wait(1)  # does, so the bound only ends the wait
        raise OSError("disk full")

    monkeypatch.setattr(crawl, "ProgressReporter", Reporter)
    monkeypatch.setattr(crawl, "atomic_write_bytes", failing_write)
    res = run([f"{base}/a", f"{base}/b"], tmp_path, connections=2)
    assert res.files_downloaded == [] and res.urls == {} and res.records == {}
    assert res.front_failed
    assert [e[1].startswith("write failed") for e in res.report.errors] == [True, True]
