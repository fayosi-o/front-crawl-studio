from main import server_address


def test_server_address_stays_local_without_port():
    assert server_address({}) == ('127.0.0.1', 8080)


def test_server_address_uses_render_port():
    assert server_address({'PORT': '10000'}) == ('0.0.0.0', 10000)
