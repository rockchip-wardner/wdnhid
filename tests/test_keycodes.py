"""Unit tests for :mod:`wdnhid.keycodes`.

These tests are pure-stdlib and need no kernel state — they exercise
the table itself and the parse helpers. Hardware / ``/dev/hidgN``
tests are out of scope and live in the consumer project
(``wdnwebui/scripts/verify_usb_hid.py``).
"""

from __future__ import annotations

import pytest

from wdnhid import keycodes as kc


# --------------------------------------------------------------------------- #
# char_to_keycode
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ch, expected_kc", [
    ("a", 0x04), ("b", 0x05), ("z", 0x1D),
    ("1", 0x1E), ("0", 0x27),
    ("\n", 0x28),  # ENTER
    ("\t", 0x2B),  # TAB
    (" ", 0x2C),   # SPACE
    ("-", 0x2D),   # unshifted dash
    ("=", 0x2E),   # unshifted equals
])
def test_char_to_keycode_unshifted(ch, expected_kc):
    modifier, code = kc.char_to_keycode(ch)
    assert modifier == 0
    assert code == expected_kc


@pytest.mark.parametrize("ch, expected_kc", [
    ("A", 0x04), ("Z", 0x1D),       # uppercase letters → shift + base
    ("!", 0x1E), ("@", 0x1F),       # shifted digits
    ("_", 0x2D), ("+", 0x2E),       # shifted punctuation
    (":", 0x33), ("?", 0x38),       # more shifted punctuation
])
def test_char_to_keycode_shifted(ch, expected_kc):
    modifier, code = kc.char_to_keycode(ch)
    assert modifier == kc.MOD_LSHIFT
    assert code == expected_kc


@pytest.mark.parametrize("ch", ["中", "🦀", "\x00", "\x07", "\x80"])
def test_char_to_keycode_rejects_non_ascii(ch):
    with pytest.raises(kc.KeycodeError):
        kc.char_to_keycode(ch)


def test_char_to_keycode_rejects_multi_char():
    with pytest.raises(kc.KeycodeError):
        kc.char_to_keycode("ab")


# --------------------------------------------------------------------------- #
# name_to_keycode
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, expected_kc", [
    ("a", 0x04), ("z", 0x1D),
    ("A", 0x04), ("Z", 0x1D),     # case-insensitive
    ("ENTER", 0x28), ("Enter", 0x28), ("enter", 0x28),
    ("ESC", 0x29), ("ESCAPE", kc.KeycodeError),  # only "ESC"
    ("F1", 0x3A), ("F12", 0x45),
    ("LEFT", 0x50), ("RIGHT", 0x4F),
    ("SPACE", 0x2C),
])
def test_name_to_keycode(name, expected_kc):
    if expected_kc is kc.KeycodeError:
        with pytest.raises(kc.KeycodeError):
            kc.name_to_keycode(name)
    else:
        assert kc.name_to_keycode(name) == expected_kc


def test_name_to_keycode_rejects_empty():
    with pytest.raises(kc.KeycodeError):
        kc.name_to_keycode("")


def test_name_to_keycode_rejects_unknown():
    with pytest.raises(kc.KeycodeError):
        kc.name_to_keycode("BANANA")


# --------------------------------------------------------------------------- #
# parse_modifier
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name, expected", [
    ("", 0), (None, 0),
    ("CTRL", kc.MOD_LCTRL), ("ctrl", kc.MOD_LCTRL),
    ("LCTRL", kc.MOD_LCTRL), ("RCTRL", kc.MOD_RCTRL),
    ("SHIFT", kc.MOD_LSHIFT), ("LSHIFT", kc.MOD_LSHIFT),
    ("RSHIFT", kc.MOD_RSHIFT),
    ("ALT", kc.MOD_LALT), ("LALT", kc.MOD_LALT), ("RALT", kc.MOD_RALT),
    ("GUI", kc.MOD_LGUI), ("LGUI", kc.MOD_LGUI), ("RGUI", kc.MOD_RGUI),
    ("META", kc.MOD_LGUI), ("WIN", kc.MOD_LGUI), ("SUPER", kc.MOD_LGUI),
    ("UNKNOWN", 0),     # unknown names degrade to 0, not raise
])
def test_parse_modifier(name, expected):
    assert kc.parse_modifier(name) == expected
