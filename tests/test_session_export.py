import json

from core.session_export import build_document, render_json, render_markdown


def test_cli_and_gui_records_share_markdown_shape():
    cli = build_document(
        [("agent", "你好", "回答")],
        sid="sid-1", title="测试会话", created="t1", updated="t2")
    gui = build_document(
        [{"mode": "agent", "question": "你好", "answer": "回答",
          "provider": "local", "elapsed": 1.2, "time": "t2"}],
        sid="sid-1", title="测试会话", created="t1", updated="t2")

    cli_text = render_markdown(cli)
    gui_text = render_markdown(gui)

    assert "# 测试会话" in cli_text
    assert "会话标识：sid-1" in cli_text
    assert "**提问：** 你好" in cli_text
    assert "**提问：** 你好" in gui_text
    assert "local" in gui_text and "1.2s" in gui_text


def test_json_export_is_structured_and_unicode_safe():
    document = build_document(
        [{"mode": "rag", "question": "拓扑？", "answer": "回答"}],
        sid="sid-2", title="中文会话")

    payload = json.loads(render_json(document))

    assert payload["sid"] == "sid-2"
    assert payload["title"] == "中文会话"
    assert payload["records"][0]["question"] == "拓扑？"
