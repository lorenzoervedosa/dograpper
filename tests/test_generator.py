"""page_generator(): the generator a page's <meta name="generator"> declares."""

from dograpper.utils.generator import SCAN_CHARS, page_generator


def test_javadoc():
    head = '<head><meta name="generator" content="javadoc/ClassWriter"></head>'
    assert page_generator(head) == "javadoc/ClassWriter"


def test_mediawiki_after_a_long_head():
    head = "<head>" + "<script>x</script>" * 300 + '<meta name="generator" content="MediaWiki 1.43.10"/>'
    assert page_generator(head) == "MediaWiki 1.43.10"


def test_attribute_order_and_case_do_not_matter():
    assert page_generator("<META CONTENT='Sphinx 7.2' NAME='Generator'>") == "Sphinx 7.2"


def test_entities_in_the_value_are_decoded():
    assert page_generator('<meta name="generator" content="A &amp; B">') == "A & B"


def test_no_generator_meta():
    assert page_generator('<meta name="description" content="javadoc/ClassWriter">') is None
    assert page_generator("") is None


def test_a_meta_past_the_scan_window_is_ignored():
    head = " " * SCAN_CHARS + '<meta name="generator" content="javadoc/ClassWriter">'
    assert page_generator(head) is None
