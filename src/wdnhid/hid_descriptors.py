"""HID report descriptors (raw bytes) for the two functions.

Both descriptors follow the USB HID 1.11 spec. The keyboard uses the
*boot* subclass (allows BIOS / Win32 SetReport fallback), the digitizer
uses the *generic* desktop / digitizer subclass because absolute
touchscreens never need boot-subclass fallback.

Why these specific descriptors:

* ``BOOT_KEYBOARD_REPORT_DESC`` — boot keyboard with 8-byte IN reports
  (modifier, reserved, 6 keycodes) + 1-byte OUT report (5 LED bits
  + 3 pad bits). The OUT report is what Win10 actually validates
  against when the device attaches — without it the host driver
  marks the device "USB Input Device" with Status=Error and never
  opens the IN endpoint. Limiting to 6KRO is the cost of using boot
  subclass; it keeps the host driver state machine trivial and is
  what BIOS expects.
* ``DIGITIZER_TABLET_REPORT_DESC`` — single-finger absolute pointer,
  tip-switch + in-range bits, 16-bit X/Y in the logical 0..32767 range
  (the maximum supported by the HID spec; we scale user coordinates
  into this range in :mod:`app.apps.usb_hid.service`). Uses the
  *Digitizer* Usage Page (0x0D) so the host actually recognises it
  as a tablet rather than misclassifying it as a mouse.
"""

from __future__ import annotations


# --------------------------------------------------------------------------- #
# Boot keyboard — 8-byte IN report + 1-byte OUT LED report
# --------------------------------------------------------------------------- #
# IN report (1 byte modifier, 1 reserved, 6 keycodes = 8 bytes):
#   USAGE_PAGE(Generic Desktop), USAGE(Keyboard), COLLECTION(Application),
#     USAGE_PAGE(Keys), USAGE_MIN(0xE0) USAGE_MAX(0xE7),
#       REPORT_COUNT(8), REPORT_SIZE(1), INPUT(Data,Var,Abs) — modifier
#     REPORT_COUNT(1), REPORT_SIZE(8), INPUT(Constant) — reserved
#     REPORT_COUNT(5), REPORT_SIZE(1), USAGE_PAGE(LEDs), USAGE_MIN(1)
#       USAGE_MAX(5), OUTPUT(Data,Var,Abs) — LED bits (Num/Caps/Scroll/Compose/Kana)
#     REPORT_COUNT(1), REPORT_SIZE(3), OUTPUT(Constant) — pad
#     REPORT_COUNT(6), REPORT_SIZE(8), USAGE_PAGE(Keys), USAGE_MIN(0)
#       USAGE_MAX(255), INPUT(Data,Array) — 6 keycodes
#   END_COLLECTION
BOOT_KEYBOARD_REPORT_DESC: bytes = bytes([
    0x05, 0x01,              # Usage Page (Generic Desktop)
    0x09, 0x06,              # Usage (Keyboard)
    0xA1, 0x01,              # Collection (Application)
    # modifier byte (8 bits, 0xE0..0xE7)
    0x05, 0x07,              #   Usage Page (Key Codes)
    0x19, 0xE0,              #   Usage Minimum (0xE0)
    0x29, 0xE7,              #   Usage Maximum (0xE7)
    0x75, 0x01,              #   Report Size (1)
    0x95, 0x08,              #   Report Count (8)
    0x15, 0x00,              #   Logical Minimum (0)
    0x25, 0x01,              #   Logical Maximum (1)
    0x81, 0x02,              #   Input (Data, Variable, Absolute)
    # reserved byte
    0x95, 0x01,              #   Report Count (1)
    0x75, 0x08,              #   Report Size (8)
    0x81, 0x01,              #   Input (Constant)
    # LED output report (Num/Caps/Scroll/Compose/Kana + 3 pad bits)
    # IMPORTANT: Win10/11 attaches HID keyboards only when the device
    # also exposes an Output report for LEDs. Without this block, the
    # host driver marks the device Status=Error and never opens the
    # IN endpoint — /dev/hidg0 write() then EAGAINs forever.
    0x95, 0x05,              #   Report Count (5)
    0x75, 0x01,              #   Report Size (1)
    0x05, 0x08,              #   Usage Page (LEDs)
    0x19, 0x01,              #   Usage Minimum (1)
    0x29, 0x05,              #   Usage Maximum (5)
    0x91, 0x02,              #   Output (Data, Variable, Absolute)
    0x95, 0x01,              #   Report Count (1)
    0x75, 0x03,              #   Report Size (3)
    0x91, 0x01,              #   Output (Constant) — pad
    # 6 keycodes
    0x95, 0x06,              #   Report Count (6)
    0x75, 0x08,              #   Report Size (8)
    0x15, 0x00,              #   Logical Minimum (0)
    0x26, 0xFF, 0x00,        #   Logical Maximum (255)
    0x05, 0x07,              #   Usage Page (Key Codes)
    0x19, 0x00,              #   Usage Minimum (0)
    0x29, 0xFF,              #   Usage Maximum (255)
    0x81, 0x00,              #   Input (Data, Array)
    0xC0,                    # End Collection
])
BOOT_KEYBOARD_REPORT_LEN = 8


# --------------------------------------------------------------------------- #
# Digitizer / Tablet — single-finger absolute pointer (Precision Touch)
# --------------------------------------------------------------------------- #
# Report layout: 1 byte Contact Count + 1 byte (Tip Switch | Contact ID |
# 3 pad bits) + 2 bytes X (LE) + 2 bytes Y (LE) = 6 bytes.
#
# Key choices:
#   * Usage Page 0x0D (Digitizers), Usage 0x04 (Touchscreen) — the host
#     recognises this as a *touchscreen* and the host OS automatically
#     routes Tip Switch + absolute X/Y as touch events. Earlier
#     versions declared Usage 0x02 (Tablet/Pen), which made Win10/11
#     attach a HID-compliant *pen* driver instead; pen drivers only
#     surface events through the Wintab / Win32 pen stack and never
#     route through the standard touch / mouse pipeline, so desktop
#     apps (Start menu, Paint brushes, file-manager icon taps) saw
#     nothing. Touchscreen is the only Usage the host treats as
#     "user is poking the screen" without a manual Tablet PC Settings
#     binding flip per device.
#   * Win 8+ Precision Touch topology (Contact Count Maximum as a
#     *Feature*, plus Contact Count as a per-report *Input* field).
#     Earlier 5-byte descriptors without these fields made Windows
#     mark the touch function "HID Input Device" / Status=Error
#     because the driver couldn't parse a "no-contact frame exists"
#     signal — it relied entirely on Contact Count transitions to
#     distinguish tip-down from move-without-touch. Without both
#     fields the touch driver rejects the device.
#   * Logical Collection USAGE 0x22 (Finger). Earlier versions pushed
#     USAGE 0x00 (Undefined / Reserved) before COLLECTION(Logical),
#     which the Windows HID parser also rejects with Status=Error.
#     Finger is the canonical Precision Touch choice.
#   * Logical range 0..32767 — the HID spec max. We scale the
#     user-supplied pixel coordinates into this range in
#     :mod:`app.apps.usb_hid.service`.
DIGITIZER_TABLET_REPORT_DESC: bytes = bytes([
    0x05, 0x0D,              # Usage Page (Digitizers)
    0x09, 0x04,              # Usage (Touchscreen)
    0xA1, 0x01,              # Collection (Application)
    # Contact Count Maximum (Feature) — declares the device's *maximum*
    # concurrent contacts. Required for the Win 8+ Precision Touch driver
    # to route this as a touchscreen instead of a generic digitizer.
    0x05, 0x0D,              #   Usage Page (Digitizers)
    0x09, 0x54,              #   Usage (Contact Count Maximum)
    0x25, 0x01,              #   Logical Maximum (1)
    0x15, 0x00,              #   Logical Minimum (0)
    0x75, 0x08,              #   Report Size (8)
    0x95, 0x01,              #   Report Count (1)
    0xB1, 0x02,              #   Feature (Data, Variable, Absolute)
    # Per-contact Logical Collection. USAGE 0x22 (Finger) is mandatory —
    # USAGE 0x00 / Undefined was the prior bug that caused Status=Error.
    0x05, 0x0D,              #   Usage Page (Digitizers)
    0x09, 0x22,              #   Usage (Finger)
    0xA1, 0x02,              #   Collection (Logical)
    # Contact Count (Input) — current contacts *in this report*.
    # Distinct from the Feature Max above. 1 = finger down, 0 = release.
    # Without this field the host can't pair the report's X/Y with the
    # "is there a contact" signal.
    0x05, 0x0D,              #     Usage Page (Digitizers)
    0x09, 0x55,              #     Usage (Contact Count)
    0x15, 0x00,              #     Logical Minimum (0)
    0x25, 0x01,              #     Logical Maximum (1)
    0x75, 0x08,              #     Report Size (8)
    0x95, 0x01,              #     Report Count (1)
    0x81, 0x02,              #     Input (Data, Variable, Absolute)
    # Tip Switch — 1 bit
    0x05, 0x0D,              #     Usage Page (Digitizers)
    0x09, 0x42,              #     Usage (Tip Switch)
    0x15, 0x00,              #     Logical Minimum (0)
    0x25, 0x01,              #     Logical Maximum (1)
    0x75, 0x01,              #     Report Size (1)
    0x95, 0x01,              #     Report Count (1)
    0x81, 0x02,              #     Input (Data, Variable, Absolute)
    # Contact Identifier — 4 bits (0..15)
    0x05, 0x0D,              #     Usage Page (Digitizers)
    0x09, 0x51,              #     Usage (Contact Identifier)
    0x25, 0x0F,              #     Logical Maximum (15)
    0x75, 0x04,              #     Report Size (4)
    0x95, 0x01,              #     Report Count (1)
    0x81, 0x02,              #     Input (Data, Variable, Absolute)
    # Pad — 3 bits, constant zero (rounds byte 1 up to byte boundary)
    0x75, 0x03,              #     Report Size (3)
    0x95, 0x01,              #     Report Count (1)
    0x81, 0x01,              #     Input (Constant)
    # X + Y — 16 bits each on the Generic Desktop page
    0x05, 0x01,              #     Usage Page (Generic Desktop)
    0x09, 0x30,              #     Usage (X)
    0x09, 0x31,              #     Usage (Y)
    0x26, 0xFF, 0x7F,        #     Logical Maximum (32767)
    0x75, 0x10,              #     Report Size (16)
    0x95, 0x02,              #     Report Count (2)
    0x81, 0x02,              #     Input (Data, Variable, Absolute)
    0xC0,                    # End Collection (Logical)
    0xC0,                    # End Collection (Application)
])
# Report layout: 1 byte Contact Count + 1 byte (Tip Switch | Contact ID | pad)
# + 4 bytes X+Y = 6 bytes total. Must match the bytes written by
# :class:`app.apps.usb_hid.service.DigitizerWriter._encode`.
DIGITIZER_TABLET_REPORT_LEN = 6
