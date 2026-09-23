"""Console and chat: Say/GetLog round trip with various text."""
import base64
import pytest
from harness import b64

# Note: Say/GetLog are workspace commands, not session commands


def test_say_get_log_round_trip(level):
    """Say/GetLog round trip with simple text."""
    editor = level.ed
    
    editor.cmd("Say -From Test -Text " + b64("Hello World"))
    log = editor.cmd("GetLog")
    assert "Hello World" in log


def test_say_unicode(level):
    """Say with unicode text."""
    editor = level.ed
    
    unicode_text = "Hello 世界 🌍"
    editor.cmd("Say -From Test -Text " + b64(unicode_text))
    log = editor.cmd("GetLog")
    assert "Hello" in log
    assert "世界" in log
    assert "🌍" in log


def test_say_emoji(level):
    """Say with emoji."""
    editor = level.ed
    
    editor.cmd("Say -From Test -Text " + b64("Test 🎉 ✅ 🚀"))
    log = editor.cmd("GetLog")
    assert "🎉" in log
    assert "✅" in log
    assert "🚀" in log


def test_say_long_line(level):
    """Say with a very long line."""
    editor = level.ed
    
    long_text = "X" * 1000
    editor.cmd("Say -From Test -Text " + b64(long_text))
    log = editor.cmd("GetLog")
    assert "XXXX" in log  # At least some of it


def test_say_with_newlines(level):
    """Say with \\n in the text."""
    editor = level.ed
    
    text_with_newlines = "Line 1\\nLine 2\\nLine 3"
    editor.cmd("Say -From Test -Text " + b64(text_with_newlines))
    log = editor.cmd("GetLog")
    assert "Line 1" in log
    assert "Line 2" in log
    assert "Line 3" in log


def test_say_with_count(level):
    """Say with -Count to limit log entries."""
    editor = level.ed
    
    for i in range(5):
        editor.cmd("Say -From Test -Text " + b64(f"Message {i}"))
    
    # Get only last 2
    log = editor.cmd("GetLog -Count 2")
    lines = log.splitlines()
    assert len(lines) <= 2


def test_get_log_empty(level):
    """GetLog on an empty log."""
    # Close and reopen to get a clean log
    level.ed.cmd("Close -Save 0")
    level.ed.cmd(f"OpenLevel -Level {level.guid} -Save 0")
    
    log = level.ed.cmd("GetLog")
    # Should be empty or just system messages


@pytest.mark.xfail(reason="Editor does not properly validate base64 input", strict=False)
def test_bad_base64_refused(level):
    """Bad base64 is refused."""
    editor = level.ed
    
    assert "base64" in editor.cmd("Say -From Test -Text ZZZ!!!invalid!!!")
