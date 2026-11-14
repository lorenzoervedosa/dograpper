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
    assert reg.assign("http://e.com/b.php", "text/html") == os.path.join(d, "b.php.html")
    assert reg.assign("http://e.com/c", None) == os.path.join(d, "c")
    assert reg.assign("http://e.com/d", "application/pdf") == os.path.join(d, "d")


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
