"""USB Gadget HID support (configfs-based).

Two HID functions are exposed to the host (PC):

* ``hid.usb0`` — Boot Keyboard (8-byte boot report: modifier, reserved,
  up to 6 concurrent keycodes). Backed by ``/dev/hidg0``.
* ``hid.usb1`` — Digitizer / Tablet (single-finger absolute pointer with
  tip switch and in-range bit). Backed by ``/dev/hidg1``.

Module entry points:

* :func:`manager.setup_gadget`  — idempotent configfs write + UDC bind.
* :func:`manager.teardown_gadget` — unbind + best-effort configfs cleanup.
* :func:`manager.gadget_status` — introspection used by ``/api/usb-hid``.

All configfs writes go through :class:`manager.ConfigfsWriter` which
holds a single :class:`threading.RLock` so concurrent HTTP requests
cannot interleave kernel-facing sysfs operations.
"""

from __future__ import annotations
