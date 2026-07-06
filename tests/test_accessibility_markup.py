from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web/app.js").read_text()


def render_chat_item_source():
    return APP_JS.split("function renderChatItem(chat) {", 1)[1].split(
        "\nfunction renderMessages()", 1
    )[0]


def test_chat_row_uses_sibling_native_buttons():
    source = render_chat_item_source()

    assert 'open.className = "open-chat"' in source
    assert "open.type = \"button\"" in source
    assert "actions.append(rename, del)" in source
    assert "item.append(open, actions)" in source
    assert "item.tabIndex" not in source
    assert "item.role" not in source
    assert 'item.addEventListener("keydown"' not in source


def test_chat_row_actions_have_specific_accessible_names():
    source = render_chat_item_source()

    assert "`Open chat: ${chat.title}`" in source
    assert 'open.setAttribute("aria-current", "page")' in source
    assert "`Rename chat: ${chat.title}`" in source
    assert "`Delete chat: ${chat.title}`" in source
