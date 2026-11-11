[English](README.md) | [简体中文](README_CN.md)

# wdnhid

Python library for driving Linux USB Gadget HID functions through
``configfs`` and ``/dev/hidgN`` character devices.

Lets a Linux board (typically the RK3588 / Rockchip platform in the
``wdn*`` family) advertise itself to a host PC as one or more HID
devices — keyboards, mice, digitizers — by writing HID report blobs
to ``/dev/hidg0``, ``/dev/hidg1``, etc.

The package is intentionally **transport-only**. It does:

* configfs tree management (create / teardown a gadget with the right
  string, config, function descriptors)
* UDC bind / unbind
* HID report descriptor assembly
* ``os.write`` to ``/dev/hidgN`` with EAGAIN retry + automatic
  reopen on ``BrokenPipeError`` (kernel can close the chardev when
  the gadget is rebound)

It does **not**:

* run a network service (the consumer does that — in our case the
  ``wdnwebui`` ``usb-hid`` card mounts the FastAPI router)
* enumerate host-side HID devices (the consumer reads ``/sys/class/udc/``
  if it cares about host state)
* carry any AI / LLM dependencies (deliberately)

## Requirements

* Linux kernel with ``CONFIG_USB_CONFIGFS_F_HID=y`` (and friends).
  On RK3588's stock 6.12 kernel this is enabled by default.
* A free UDC (USB device controller) — typically the OTG port.
  Discovered via ``/sys/class/udc/``.
* Root access for ``configfs`` writes (``/sys/kernel/config/usb_gadget/``).
  The kernel ``/dev/hidgN`` chardevs should be granted group-write
  permissions to the user the consumer process runs as; see the
  ``99-wdnhid-gadget.rules`` snippet in the project that uses this
  package (``wdnwebui/scripts/``).

## Install

Editable, straight from GitHub (recommended):

```bash
pip install -e "git+ssh://git@github.com:rockchip-wardner/wdnhid.git#egg=wdnhid"
```

Or from an existing checkout:

```bash
pip install -e /path/to/wdnhid
```

Wheel build (for distribution):

```bash
cd /path/to/wdnhid
python -m build
pip install dist/wdnhid-0.1.1-*.whl
```

## Quick start

```python
from wdnhid import manager, keycodes as kc

# 1. Build the gadget tree + bind to the first available UDC.
#    Idempotent: re-running with the same parameters is a no-op.
manager.setup_gadget(vid=0x1D6B, pid=0x0103,
                     manufacturer="acme", product="HID bridge",
                     serial="hid-001")

# 2. Write an 8-byte boot-keyboard report.
fd = manager.get_chardev_fd("keyboard")
manager.safe_write(fd, bytes([0, 0, kc.KEYCODES["h"],
                                kc.KEYCODES["e"],
                                kc.KEYCODES["l"],
                                kc.KEYCODES["l"],
                                kc.KEYCODES["o"], 0]))
manager.safe_write(fd, bytes([0, 0, 0, 0, 0, 0, 0, 0]))   # release

# 3. Move an absolute-pointer digitizer.
fd = manager.get_chardev_fd("digitizer")
manager.safe_write(fd, bytes([0x01, 0x00, 0x40, 0x0F, 0x00]))  # tip, X=4000, Y=0

# 4. Tear down on shutdown.
manager.teardown_gadget()
```

## Module layout

* ``wdnhid.manager`` — configfs tree + UDC bind + ``/dev/hidgN`` FD cache
  with retry / reopen logic.
* ``wdnhid.keycodes`` — USB HID Boot Keyboard usage IDs, ``char_to_keycode``,
  ``name_to_keycode``, ``parse_modifier``.
* ``wdnhid.hid_descriptors`` — raw ``bytes`` for the Boot Keyboard and
  Digitizer / Tablet report descriptors.

## License

Apache-2.0. See [LICENSE](LICENSE).
