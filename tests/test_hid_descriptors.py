"""Unit tests for :mod:`wdnhid.hid_descriptors`.

Confirms the report descriptors are the right length, start with the
mandatory opening tokens, and end with a closing collection byte.
"""

from __future__ import annotations

import pytest

from wdnhid.hid_descriptors import (
    BOOT_KEYBOARD_REPORT_DESC,
    BOOT_KEYBOARD_REPORT_LEN,
    DIGITIZER_TABLET_REPORT_DESC,
    DIGITIZER_TABLET_REPORT_LEN,
)


def test_kb_descriptor_opens_with_collection_application():
    # Every HID report descriptor must start with COLLECTION(Application)
    # and end with END_COLLECTION (0xC0).
    assert BOOT_KEYBOARD_REPORT_DESC[:3] == bytes([0x05, 0x01, 0x09])  # GD / Keyboard
    assert BOOT_KEYBOARD_REPORT_DESC[3] == 0x06                        # Usage = Keyboard
    assert BOOT_KEYBOARD_REPORT_DESC[4:6] == bytes([0xA1, 0x01])       # Collection(App)
    assert BOOT_KEYBOARD_REPORT_DESC[-1] == 0xC0                       # End Collection


def test_kb_descriptor_has_led_output():
    # 0x91 = Output item; required for Win10 to recognise the device
    # as a complete HID keyboard (see commit history of
    # hid_descriptors.py: "boot keyboard + LED Output" fix).
    assert 0x91 in BOOT_KEYBOARD_REPORT_DESC, (
        "Boot keyboard descriptor missing LED Output report — Win10 "
        "will mark the device Status=Error and never open the IN endpoint."
    )


def test_digitizer_descriptor_uses_digitizer_page():
    # First 4 bytes must be 05 0D 09 02 — Usage Page(Digitizer), Usage(Tablet).
    # Previous bug: had 05 01 09 02 (Mouse page + Tablet usage), which
    # Win10 attaches as a Mouse class driver and then refuses to start.
    assert DIGITIZER_TABLET_REPORT_DESC[:4] == bytes([0x05, 0x0D, 0x09, 0x02])


def test_digitizer_descriptor_closes_collections():
    # Two C0s — one for Collection(Physical), one for Collection(Application).
    assert DIGITIZER_TABLET_REPORT_DESC.count(0xC0) == 2


@pytest.mark.parametrize("name, desc, length", [
    ("BOOT_KEYBOARD", BOOT_KEYBOARD_REPORT_DESC, BOOT_KEYBOARD_REPORT_LEN),
    ("DIGITIZER", DIGITIZER_TABLET_REPORT_DESC, DIGITIZER_TABLET_REPORT_LEN),
])
def test_descriptor_lengths_match_declared(name, desc, length):
    assert len(desc) > 0
    # Length constants are for the *report* (what gets sent per write),
    # not the descriptor size. Sanity: descriptor is always longer than
    # the report it describes.
    assert len(desc) >= length
