from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "web/app.js").read_text()
INDEX_HTML = (ROOT / "web/index.html").read_text()


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


def test_panel_toggles_expose_relationships_and_initial_state():
    assert (
        'id="menuButton" type="button" aria-label="Toggle sidebar" '
        'aria-controls="sidebar" aria-expanded="false"'
    ) in INDEX_HTML
    assert (
        'id="settingsButton" type="button" aria-controls="settingsPanel" '
        'aria-expanded="false"'
    ) in INDEX_HTML


def test_panel_toggle_state_is_updated_and_sidebar_close_resets_state():
    assert (
        'els.settingsButton.setAttribute("aria-expanded", String(expanded))'
        in APP_JS
    )
    assert 'els.menuButton.setAttribute("aria-expanded", String(expanded))' in APP_JS
    assert 'els.menuButton.setAttribute("aria-expanded", "false")' in APP_JS


def test_icon_buttons_and_unlabelled_text_inputs_have_accessible_names():
    assert 'del.setAttribute("aria-label", `Delete chat: ${chat.title}`)' in APP_JS
    assert 'rename.setAttribute("aria-label", `Rename chat: ${chat.title}`)' in APP_JS
    assert 'id="searchInput"' in INDEX_HTML and 'aria-label="Search chats"' in INDEX_HTML
    assert 'id="promptInput"' in INDEX_HTML and 'aria-label="Message"' in INDEX_HTML
