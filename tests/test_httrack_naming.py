import hashlib
import os
import threading

from dograpper.lib.httrack.naming import NameRegistry


def _reg(tmp_path):
    return NameRegistry(str(tmp_path)), os.path.realpath(str(tmp_path))


def test_directory_url_maps_to_index_html(tmp_path):
    reg, root = _reg(tmp_path)
    assert reg.assign("https://Example.com/", "text/html") == os.path.join(root, "example.com", "index.html")
    assert reg.assign("https://example.com/docs/", None) == os.path.join(root, "example.com", "docs", "index.html")
    assert NameRegistry(str(tmp_path)).assign("https://example.com", "text/html") == os.path.join(root, "example.com", "index.html")


def test_host_dir_port_only_when_non_default(tmp_path):
    reg, root = _reg(tmp_path)
    assert reg.assign("https://example.com:443/a.html", None) == os.path.join(root, "example.com", "a.html")
    assert reg.assign("http://example.com:8080/a.html", None) == os.path.join(root, "example.com:8080", "a.html")


def test_html_extension_adjusted(tmp_path):
    reg, root = _reg(tmp_path)
    d = os.path.join(root, "e.com")
    assert reg.assign("http://e.com/page", "Text/HTML; charset=utf-8") == os.path.join(d, "page.html")
    assert reg.assign("http://e.com/a.htm", "text/html") == os.path.join(d, "a.htm")
    assert reg.assign("http://e.com/b.php", "text/html") == os.path.join(d, "b.html")  # R14
    assert reg.assign("http://e.com/c", None) == os.path.join(d, "c")
    assert reg.assign("http://e.com/d", "application/pdf") == os.path.join(d, "d")


def test_html_replaces_dynamic_and_html_family_extensions_like_httrack(tmp_path):
    reg, root = _reg(tmp_path)
    d = os.path.join(root, "e.com")
    h = lambda q: hashlib.md5(q.encode()).hexdigest()[:4]  # noqa: E731
    assert reg.assign("http://e.com/page.php?x=1", "text/html") == os.path.join(d, f"page{h('x=1')}.html")
    assert reg.assign("http://e.com/foo.cgi?q=45", "text/html") == os.path.join(d, f"foo{h('q=45')}.html")
    for name in ("a.ASP", "b.jsp", "c.pl", "d.cfm", "e.nsf", "f.php3", "g.shtml", "h.phtml", "i."):
        assert reg.assign(f"http://e.com/{name}", "text/html") == os.path.join(d, name.split(".")[0] + ".html")
    # an unknown token is part of the name: appended to, not replaced
    assert reg.assign("http://e.com/article-1.884291", "text/html") == os.path.join(d, "article-1.884291.html")
    assert reg.assign("http://e.com/x.php", "application/pdf") == os.path.join(d, "x.php")


def test_forbidden_characters_become_underscores(tmp_path):
    reg, root = _reg(tmp_path)
    d = os.path.join(root, "h")
    assert reg.assign("http://h/a%1b%5b31mX%0aY", "text/html") == os.path.join(d, "a_[31mX_Y.html")
    got = reg.assign("http://h/d%7Ce/a~b%5Cc%3Ad%2Ae%3Ff%22g%3Ch%3Ei%7Cj%7Fk%09l", None)
    assert got == os.path.join(d, "d_e", "a_b_c_d_e_f_g_h_i_j_k_l")
    assert reg.assign("http://a\x1bb.com/x", None) == os.path.join(root, "a_b.com", "x")
    assert reg.assign("http://h/%E4%BD%A0%C3%A9", None) == os.path.join(d, "你é")  # non-ASCII kept


def test_query_hash_suffix(tmp_path):
    reg, root = _reg(tmp_path)
    h = hashlib.md5(b"x=1").hexdigest()[:4]
    d = os.path.join(root, "e.com")
    assert reg.assign("http://e.com/page.html?x=1", "text/html") == os.path.join(d, f"page{h}.html")
    assert reg.assign("http://e.com/?x=1", "text/html") == os.path.join(d, f"index{h}.html")


def test_collision_suffix_and_stability(tmp_path):
    reg, root = _reg(tmp_path)
    d = os.path.join(root, "e.com")
    a = reg.assign("http://e.com/a%2Eb", None)  # decodes to a.b
    b = reg.assign("http://e.com/a.b", None)
    c = reg.assign("http://e.com/a.b#frag", None)
    assert a == os.path.join(d, "a.b")
    assert b == os.path.join(d, "a-2.b")
    assert c == b
    assert reg.assign("http://e.com/a%2Eb", None) == a
    assert reg.assign("http://e.com/a./b", None) != a


def test_traversal_rejected(tmp_path):
    reg, root = _reg(tmp_path)
    for u in ("http://e.com/../x", "http://e.com/%2e%2e/x", "http://e.com/a\\..\\..\\b",
              "http://e.com/a/%2e%2e/%2e%2e/x", "http://e.com/a%00b", "http:///x"):
        p = reg.assign(u, None)
        assert p is None or os.path.commonpath([root, p]) == root, u
    assert reg.assign("http://e.com/../x", None) is None
    assert reg.assign("http://e.com/a/../b", None) == os.path.join(root, "e.com", "b")


def test_symlink_escape_rejected(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "secret").mkdir()
    (out / "e.com").symlink_to(tmp_path / "secret")
    assert NameRegistry(str(out)).assign("http://e.com/x", None) is None


def test_thread_safe_unique_paths(tmp_path):
    reg, _ = _reg(tmp_path)
    out = []
    def work(i):
        out.append(reg.assign(f"http://e.com/{'a' if i % 2 else 'a%2E'}?q={i}", None))
    ts = [threading.Thread(target=work, args=(i,)) for i in range(40)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(out)) == 40
