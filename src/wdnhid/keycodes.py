"""USB HID keycodes (Boot Keyboard, page 0x07).

Subset that's actually useful for "type a string" / "send a hotkey"
operations. Only the boot-subset codes (0x04-0xE7) are listed —
anything above 0xE7 requires a HID report descriptor with more than
6KRO (the boot descriptor caps at 6 concurrent keys). See
``hid_descriptors.py::BOOT_KEYBOARD_REPORT_DESC`` for the limit.

The mapping table is from the USB HID Usage Tables 1.5 (Section 10,
"Keyboard/Keypad Page"). ``char_to_keycode`` only handles ASCII
printables; non-ASCII chars raise :class:`KeycodeError`.
"""

from __future__ import annotations


# ----- modifier bits (boot report byte 0) ------------------------------- #
MOD_LCTRL = 0x01
MOD_LSHIFT = 0x02
MOD_LALT = 0x04
MOD_LGUI = 0x08
MOD_RCTRL = 0x10
MOD_RSHIFT = 0x20
MOD_RALT = 0x40
MOD_RGUI = 0x80


# ----- keycode lookup (USB HID boot keyboard usage IDs) ---------------- #
# Range 0x04..0x1D = letters A..Z, 0x1E..0x27 = digits 1..0,
# 0x28..0x29 = Enter/Escape, 0x2A..0x38 = F1..F12 ... (truncated set below)
KEYCODES: dict[str, int] = {
    # Letters
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D,
    # Digits row
    "1": 0x1E, "2": 0x1F, "3": 0x20, "4": 0x21, "5": 0x22, "6": 0x23,
    "7": 0x24, "8": 0x25, "9": 0x26, "0": 0x27,
    # Control
    "ENTER": 0x28, "ESC": 0x29, "BACKSPACE": 0x2A, "TAB": 0x2B,
    "SPACE": 0x2C,
    # Punctuation (unshifted)
    "-": 0x2D, "=": 0x2E, "[": 0x2F, "]": 0x30, "\\": 0x31, "#": 0x32,
    ";": 0x33, "'": 0x34, "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38,
    # Lock keys
    "CAPSLOCK": 0x39,
    # Function
    "F1": 0x3A, "F2": 0x3B, "F3": 0x3C, "F4": 0x3D, "F5": 0x3E,
    "F6": 0x3F, "F7": 0x40, "F8": 0x41, "F9": 0x42, "F10": 0x43,
    "F11": 0x44, "F12": 0x45,
    # Navigation
    "PRINTSCREEN": 0x46, "SCROLLLOCK": 0x47, "PAUSE": 0x48,
    "INSERT": 0x49, "HOME": 0x4A, "PAGEUP": 0x4B, "DELETE": 0x4C,
    "END": 0x4D, "PAGEDOWN": 0x4E,
    "RIGHT": 0x4F, "LEFT": 0x50, "DOWN": 0x51, "UP": 0x52,
    # Numpad
    "NUMLOCK": 0x53,
    "KP_SLASH": 0x54, "KP_ASTERISK": 0x55, "KP_MINUS": 0x56,
    "KP_PLUS": 0x57, "KP_ENTER": 0x58,
    "KP_1": 0x59, "KP_2": 0x5A, "KP_3": 0x5B, "KP_4": 0x5C,
    "KP_5": 0x5D, "KP_6": 0x5E, "KP_7": 0x5F, "KP_8": 0x60,
    "KP_9": 0x61, "KP_0": 0x62,
    "KP_DOT": 0x63,
}

# Punctuation that requires Shift on US layout. Anything here is sent with
# the SHIFT modifier held; the resulting character comes out correctly
# only if the host OS keyboard layout matches. We deliberately do NOT
# auto-detect layout — the API caller passes either pre-formatted text
# (we apply US layout defaults) or pre-computed keycode sequences.
SHIFT_NEEDED: frozenset[str] = frozenset({
    # Letters are handled by upper/lower in char_to_keycode(), not here.
    "!", "@", "#", "$", "%", "^", "&", "*", "(", ")",
    "_", "+", "{", "}", "|", ":", "\"", "~", "<", ">", "?",
})


class KeycodeError(ValueError):
    """Raised when a character / name has no USB HID boot-subset mapping."""


def char_to_keycode(ch: str) -> tuple[int, int]:
    """Map a single ASCII char to ``(modifier_byte, keycode)``.

    Lowercase ASCII letters and US unshifted punctuation come back with
    modifier = 0. Uppercase letters and shifted punctuation come back
    with ``MOD_LSHIFT`` set so the host prints the intended glyph.
    """
    if len(ch) != 1:
        raise KeycodeError(f"char_to_keycode expects exactly 1 char, got {ch!r}")
    if "a" <= ch <= "z":
        return (0, KEYCODES[ch])
    if "A" <= ch <= "Z":
        return (MOD_LSHIFT, KEYCODES[ch.lower()])
    if ch == " ":
        return (0, KEYCODES["SPACE"])
    if ch == "\n":
        return (0, KEYCODES["ENTER"])
    if ch == "\t":
        return (0, KEYCODES["TAB"])
    if ch in KEYCODES:
        return (0, KEYCODES[ch])
    if ch in SHIFT_NEEDED:
        unshifted = {
            "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
            "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
            "_": "-", "+": "=", "{": "[", "}": "]", "|": "\\",
            ":": ";", "\"": "'", "~": "`", "<": ",", ">": ".",
            "?": "/",
        }
        return (MOD_LSHIFT, KEYCODES[unshifted[ch]])
    raise KeycodeError(f"unsupported char {ch!r} (non-ASCII / non-US-layout)")


def name_to_keycode(name: str) -> int:
    """Map a symbolic key name (e.g. ``"c"`` / ``"ENTER"`` / ``"F5"``) to
    its 8-bit USB HID usage id. Case-insensitive; the canonical form
    in :data:`KEYCODES` is mixed (letters lowercase, named keys
    uppercase) so we uppercase the lookup key but keep the table
    authoritative.

    Raises :class:`KeycodeError` if the name is not a known key."""
    if not name:
        raise KeycodeError("empty key name")
    upper = name.strip().upper()
    # Direct hit on the canonical entry (handles 'ENTER', 'F1', 'a'... no
    # — KEYCODES uses lowercase letters, so we normalize letters below).
    if upper in KEYCODES:
        return KEYCODES[upper]
    # Letters are stored lowercase; uppercase variants must also resolve.
    if len(upper) == 1 and "A" <= upper <= "Z":
        return KEYCODES[upper.lower()]
    raise KeycodeError(f"unknown key name {name!r}")


def parse_modifier(name: str) -> int:
    """Map a modifier name to its bit. Case-insensitive; ``LCTRL`` / ``ctrl``
    both work. Returns 0 if ``name`` is empty / None."""
    if not name:
        return 0
    key = name.strip().upper()
    return {
        "CTRL": MOD_LCTRL, "LCTRL": MOD_LCTRL, "RCTRL": MOD_RCTRL,
        "SHIFT": MOD_LSHIFT, "LSHIFT": MOD_LSHIFT, "RSHIFT": MOD_RSHIFT,
        "ALT": MOD_LALT, "LALT": MOD_LALT, "RALT": MOD_RALT,
        "GUI": MOD_LGUI, "LGUI": MOD_LGUI, "RGUI": MOD_RGUI,
        "META": MOD_LGUI, "WIN": MOD_LGUI, "SUPER": MOD_LGUI,
    }.get(key, 0)
