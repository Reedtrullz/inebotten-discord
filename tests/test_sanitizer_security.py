from utils.sanitizer import sanitize_discord_mention, sanitize_html, sanitize_url


def test_sanitize_discord_mention_removes_user_mentions():
    assert sanitize_discord_mention("hei <@123456> og <@!789>").strip() == "hei  og"


def test_sanitize_html_escapes_tags_and_quotes():
    assert sanitize_html('<img src=x onerror="alert(1)">') == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"


def test_sanitize_url_blocks_loopback_and_private_hosts():
    assert sanitize_url("http://127.0.0.1:8080/secret") == ""
    assert sanitize_url("http://localhost:8080/secret") == ""
    assert sanitize_url("http://10.0.0.1/secret") == ""
    assert sanitize_url("http://192.168.1.10/secret") == ""
    assert sanitize_url("http://172.16.0.1/secret") == ""


def test_sanitize_url_allows_public_https_url():
    assert sanitize_url("https://example.com/path?q=1") == "https://example.com/path?q=1"
