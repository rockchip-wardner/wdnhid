"""USB Gadget HID configfs manager (RK3588 OTG).

Layout produced under ``/sys/kernel/config/usb_gadget/g1``:

    g1/
    ├── idVendor, idProduct, bcdDevice, bcdUSB
    ├── strings/0x409/{serialnumber, manufacturer, product}
    ├── configs/c.1/
    │   ├── strings/0x409/configuration
    │   └── hid.usb0 (keyboard), hid.usb1 (digitizer)
    └── UDC = <bound controller name, e.g. fc000000.usb>

On success, the kernel exposes ``/dev/hidg0`` (keyboard) and
``/dev/hidg1`` (digitizer). User code writes 8-byte / 5-byte
report blobs to those character devices; the gadget driver
encapsulates them in USB HID IN reports to the host.

Safety / lifecycle:

* All sysfs writes are guarded by a single ``RLock`` so concurrent
  HTTP requests cannot interleave (configfs is not transactional
  — interleaving produces "no such file" on the second writer).
* ``setup_gadget()`` is idempotent. If the gadget already exists
  with the same configuration, it is a no-op. If a stale gadget
  exists with conflicting state (e.g. bound to a different UDC),
  it is torn down first.
* ``teardown_gadget()`` unbind the UDC + remove every configfs
  node we created. Best-effort: a node that is "busy" is logged
  and skipped, never partially-removed (configfs does not
  support partial rollback).
* ``gadget_status()`` is the introspection surface used by
  ``GET /api/usb-hid``.

The UDC is auto-discovered by scanning ``/sys/class/udc/``. On RK3588
that yields ``fc000000.usb`` — the only DWC3 instance in device role.
If a deployment has more than one UDC, ``bind_udc`` lets the caller
pick via config or the ``WDNWEBUI_USB_HID_UDC`` env var.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from .hid_descriptors import (
    BOOT_KEYBOARD_REPORT_DESC,
    BOOT_KEYBOARD_REPORT_LEN,
    DIGITIZER_TABLET_REPORT_DESC,
    DIGITIZER_TABLET_REPORT_LEN,
)

LOG = logging.getLogger("usb_gadget.manager")


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
GADGET_NAME = "g1"
GADGET_ROOT = Path("/sys/kernel/config/usb_gadget")
CONFIGFS_MOUNT = Path("/sys/kernel/config")
UDC_CLASS = Path("/sys/class/udc")

# Defaults — overridable via config.jsonc["usb_hid_gadget"]
DEFAULT_VID = 0x1D6B   # Linux Foundation (vendoring as RK3588 board)
DEFAULT_PID = 0x0103   # Multifunction Composite Gadget (HID only)
DEFAULT_MANUFACTURER = "wdnwebui"
DEFAULT_PRODUCT = "USB HID Bridge"
DEFAULT_SERIAL = "rk3588-hid-0001"
DEFAULT_CONFIG_LABEL = "HID Keyboard + Tablet"

# /dev/hidgN device paths
HIDG_DEVICES = {
    "keyboard": Path("/dev/hidg0"),
    "digitizer": Path("/dev/hidg1"),
}

# Report sizes (re-exported so callers don't need to import descriptors)
KEYBOARD_REPORT_LEN = BOOT_KEYBOARD_REPORT_LEN
DIGITIZER_REPORT_LEN = DIGITIZER_TABLET_REPORT_LEN


class GadgetError(RuntimeError):
    """Raised when configfs manipulation fails (e.g. UDC already bound,
    insufficient privileges, kernel feature missing)."""


# --------------------------------------------------------------------------- #
# Configfs helper
# --------------------------------------------------------------------------- #
class _Configfs:
    """Tiny wrapper around the gadget's configfs subtree.

    All writes are funnelled through one ``RLock``. ``mkdir`` /
    ``write`` / ``unlink`` mirror the underlying filesystem calls but
    raise :class:`GadgetError` on any failure with a path-tagged message
    so the caller's logs actually pinpoint the bad node.
    """

    def __init__(self, root: Path):
        self._root = root
        self._lock = threading.RLock()

    # -- public helpers ------------------------------------------------- #
    @property
    def root(self) -> Path:
        return self._root

    def exists(self) -> bool:
        return self._root.is_dir()

    def mkdir(self, rel: str) -> Path:
        """Create a directory (and parents) under the gadget root.

        ``mkdir -p`` semantics: an existing target is a no-op. Other
        OSError subtypes are wrapped in :class:`GadgetError`.
        """
        with self._lock:
            target = self._root / rel
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise GadgetError(f"mkdir {target}: {e}") from e
            return target

    def write(self, rel: str, value: str | int | bytes) -> None:
        """Atomic-ish write to a configfs file. ``value`` is coerced to
        ASCII bytes (no BOM, no newline)."""
        with self._lock:
            target = self._root / rel
            try:
                if isinstance(value, bytes):
                    data = value
                else:
                    data = str(value).encode("utf-8")
                # O_TRUNC | O_WRONLY; configfs files are small (≤ a few KB)
                fd = os.open(target, os.O_WRONLY | os.O_TRUNC)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
            except OSError as e:
                raise GadgetError(f"write {target}={value!r}: {e}") from e

    def read(self, rel: str) -> str:
        with self._lock:
            target = self._root / rel
            try:
                return target.read_text().strip()
            except OSError as e:
                raise GadgetError(f"read {target}: {e}") from e

    def unlink(self, rel: str) -> None:
        """Remove a configfs leaf. No-op if missing.

        ``rmdir`` for directories, ``unlink`` for files. We never
        recursively remove under the gadget root: the operator should
        call :func:`teardown_gadget` for that.
        """
        with self._lock:
            target = self._root / rel
            if not target.exists():
                return
            try:
                if target.is_dir() and not target.is_symlink():
                    target.rmdir()
                else:
                    target.unlink()
            except OSError as e:
                raise GadgetError(f"unlink {target}: {e}") from e


# --------------------------------------------------------------------------- #
# Module-level helpers
# --------------------------------------------------------------------------- #
def list_udcs() -> list[str]:
    """Return the names of all UDC controllers currently registered
    with the kernel. On RK3588 that's exactly one — ``fc000000.usb``
    — but the manager is generic enough to handle more."""
    if not UDC_CLASS.is_dir():
        return []
    return sorted(p.name for p in UDC_CLASS.iterdir() if p.is_dir())


def pick_default_udc() -> str | None:
    """First UDC returned by :func:`list_udcs`, or ``None`` if the
    class directory is empty (USB device-side driver not loaded)."""
    udcs = list_udcs()
    return udcs[0] if udcs else None


def _read_gadget_attrs(root: Path, *names: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in names:
        p = root / n
        if p.exists():
            try:
                out[n] = p.read_text().strip()
            except OSError:
                pass
    return out


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def setup_gadget(
    *,
    vid: int = DEFAULT_VID,
    pid: int = DEFAULT_PID,
    manufacturer: str = DEFAULT_MANUFACTURER,
    product: str = DEFAULT_PRODUCT,
    serial: str = DEFAULT_SERIAL,
    config_label: str = DEFAULT_CONFIG_LABEL,
    udc: str | None = None,
) -> dict[str, Any]:
    """Idempotent: build the HID gadget + bind to UDC.

    Returns a snapshot dict suitable for ``/api/usb-hid`` response. On
    partial failure (configfs written but bind refused) the function
    raises :class:`GadgetError` after rolling back the configfs tree.
    """
    if not CONFIGFS_MOUNT.is_mount():
        raise GadgetError(
            f"configfs not mounted at {CONFIGFS_MOUNT} — "
            "mount it before setup (e.g. `mount -t configfs none "
            "/sys/kernel/config` or fix the systemd unit)."
        )

    gadget_root = GADGET_ROOT / GADGET_NAME
    cfg = _Configfs(gadget_root)

    # --- idempotency / stale-state handling -------------------------- #
    if cfg.exists():
        status = gadget_status()
        # Re-running with the exact same configuration is a no-op.
        if (
            status.get("idVendor") == f"0x{vid:04x}"
            and status.get("idProduct") == f"0x{pid:04x}"
            and status.get("manufacturer") == manufacturer
            and status.get("product") == product
            and status.get("udc")
            and (udc is None or status["udc"] == udc)
        ):
            LOG.info("setup_gadget: already configured and bound to %s",
                     status["udc"])
            return status
        LOG.info("setup_gadget: stale config detected, tearing down first")
        teardown_gadget()

    # --- create tree -------------------------------------------------- #
    LOG.info("setup_gadget: writing HID configfs tree at %s", gadget_root)
    cfg.mkdir(GADGET_NAME)
    cfg.write("idVendor", f"0x{vid:04x}")
    cfg.write("idProduct", f"0x{pid:04x}")
    cfg.write("bcdUSB", "0x0200")            # USB 2.0
    cfg.write("bcdDevice", "0x0100")
    cfg.write("max_speed", "high-speed")     # 480 Mbps is enough for HID
    # device class = 0 (interface-class based, see configs)
    cfg.write("device/class", "00")
    cfg.write("device/subclass", "00")
    cfg.write("device/protocol", "00")

    # --- strings ------------------------------------------------------ #
    cfg.mkdir("strings/0x409")
    cfg.write("strings/0x409/serialnumber", serial)
    cfg.write("strings/0x409/manufacturer", manufacturer)
    cfg.write("strings/0x409/product", product)

    # --- config + functions ------------------------------------------ #
    cfg.mkdir("configs/c.1")
    cfg.write("configs/c.1/MaxPower", "250")  # 500 mA (USB 3 high-power unit load)
    cfg.write("configs/c.1/bmAttributes", "0x80")  # bus-powered
    cfg.mkdir("configs/c.1/strings/0x409")
    cfg.write("configs/c.1/strings/0x409/configuration", config_label)

    # Function 0: Boot Keyboard
    cfg.mkdir("functions/hid.usb0")
    cfg.write("functions/hid.usb0/protocol", "1")  # Keyboard
    cfg.write("functions/hid.usb0/subclass", "1")  # Boot Interface Subclass
    cfg.write("functions/hid.usb0/report_length", str(BOOT_KEYBOARD_REPORT_LEN))
    cfg.write("functions/hid.usb0/report_desc", BOOT_KEYBOARD_REPORT_DESC)
    (gadget_root / "configs/c.1/hid.usb0").symlink_to(
        gadget_root / "functions/hid.usb0"
    )

    # Function 1: Digitizer. bInterfaceProtocol=3 puts the host's HID
    # stack into *Digitizer* class — which is what binds the device as
    # a touchscreen/tablet in Tablet PC Settings, lets Paint accept
    # pen events, and routes the touch to the screen the user picked
    # in Tablet PC Settings. The earlier "2 = mouse fallback"
    # caused Win10/11 to load the HID Mouse class driver instead;
    # mouse drivers interpret absolute X/Y as a delta cursor jump and
    # silently drop most of the report, so the digitizer appeared
    # non-functional at the host even though writes were succeeding.
    cfg.mkdir("functions/hid.usb1")
    cfg.write("functions/hid.usb1/protocol", "3")  # Digitizer
    cfg.write("functions/hid.usb1/subclass", "0")  # Generic desktop / digitizer
    cfg.write("functions/hid.usb1/report_length", str(DIGITIZER_TABLET_REPORT_LEN))
    cfg.write("functions/hid.usb1/report_desc", DIGITIZER_TABLET_REPORT_DESC)
    (gadget_root / "configs/c.1/hid.usb1").symlink_to(
        gadget_root / "functions/hid.usb1"
    )

    # --- bind UDC ----------------------------------------------------- #
    target_udc = udc or os.environ.get("WDNWEBUI_USB_HID_UDC") or pick_default_udc()
    if not target_udc:
        raise GadgetError(
            "no UDC available — /sys/class/udc is empty. Is the device-side "
            "dwc3 driver loaded? Check `lsmod | grep dwc3`."
        )
    if not (UDC_CLASS / target_udc).exists():
        raise GadgetError(f"UDC {target_udc!r} does not exist in /sys/class/udc")
    try:
        cfg.write("UDC", target_udc)
    except GadgetError as e:
        # Roll back so a half-bound state doesn't survive across retries.
        LOG.warning("setup_gadget: UDC bind failed (%s); rolling back", e)
        teardown_gadget()
        raise

    LOG.info("setup_gadget: bound to %s", target_udc)
    return gadget_status()


def teardown_gadget() -> None:
    """Best-effort: unbind UDC + remove every configfs node we made.

    The kernel will not let us rmdir a function while it's linked into
    a config, so order is strict: UDC="" first, then unlink symlinks,
    then rmdir leaves. Any failure logs and moves on so a stale
    gadget can still be cleaned up incrementally across multiple calls.
    """
    gadget_root = GADGET_ROOT / GADGET_NAME
    if not gadget_root.exists():
        return
    cfg = _Configfs(gadget_root)

    # 1. Unbind
    try:
        cfg.write("UDC", "")
    except GadgetError as e:
        LOG.warning("teardown: UDC unbind failed: %s", e)

    # 2. Unlink functions from the config
    for fn in ("hid.usb0", "hid.usb1"):
        link = gadget_root / "configs" / "c.1" / fn
        if link.is_symlink() or link.exists():
            try:
                link.unlink()
            except OSError as e:
                LOG.warning("teardown: unlink %s failed: %s", link, e)

    # 3. Rmdir config strings / config
    for rel in (
        "configs/c.1/strings/0x409",
        "configs/c.1",
        "configs",
    ):
        try:
            cfg.unlink(rel)
        except GadgetError as e:
            LOG.warning("teardown: rmdir %s failed: %s", rel, e)

    # 4. Rmdir functions
    for fn in ("functions/hid.usb1", "functions/hid.usb0", "functions"):
        try:
            cfg.unlink(fn)
        except GadgetError as e:
            LOG.warning("teardown: rmdir %s failed: %s", fn, e)

    # 5. Rmdir device-level strings + gadget root
    for rel in ("strings/0x409", "strings", GADGET_NAME):
        try:
            cfg.unlink(rel)
        except GadgetError as e:
            LOG.warning("teardown: rmdir %s failed: %s", rel, e)

    LOG.info("teardown_gadget: %s", gadget_root)


def gadget_status() -> dict[str, Any]:
    """Read-only snapshot used by ``GET /api/usb-hid``.

    Reports:
      * config (vid / pid / strings) — only when gadget exists
      * binding (udc / state) — when bound
      * device nodes (whether ``/dev/hidgN`` is present and writable)
    """
    gadget_root = GADGET_ROOT / GADGET_NAME
    out: dict[str, Any] = {
        "configfs_mounted": CONFIGFS_MOUNT.is_mount(),
        "udcs_available": list_udcs(),
        "gadget_path": str(gadget_root),
    }
    if not gadget_root.exists():
        out["present"] = False
        out["udc"] = ""
        out["state"] = "absent"
        out["devices"] = {
            name: {"path": str(p), "exists": p.exists(),
                   "writable": p.exists() and os.access(p, os.W_OK)}
            for name, p in HIDG_DEVICES.items()
        }
        return out

    out["present"] = True
    out.update(_read_gadget_attrs(gadget_root, "idVendor", "idProduct",
                                  "bcdUSB", "max_speed"))
    out["manufacturer"] = (gadget_root / "strings/0x409/manufacturer").read_text().strip() \
        if (gadget_root / "strings/0x409/manufacturer").exists() else ""
    out["product"] = (gadget_root / "strings/0x409/product").read_text().strip() \
        if (gadget_root / "strings/0x409/product").exists() else ""
    out["serial"] = (gadget_root / "strings/0x409/serialnumber").read_text().strip() \
        if (gadget_root / "strings/0x409/serialnumber").exists() else ""

    udc_file = gadget_root / "UDC"
    if udc_file.exists():
        udc = udc_file.read_text().strip()
        out["udc"] = udc
        if not udc:
            out["state"] = "unbound"
        else:
            state_path = UDC_CLASS / udc / "state"
            out["state"] = state_path.read_text().strip() if state_path.exists() else "unknown"
    else:
        out["udc"] = ""
        out["state"] = "no-udc-file"

    out["functions"] = []
    fn_root = gadget_root / "functions"
    if fn_root.exists():
        for fn in sorted(fn_root.iterdir()):
            sub = _read_gadget_attrs(fn, "protocol", "subclass", "report_length")
            out["functions"].append({"name": fn.name, **sub})

    out["devices"] = {
        name: {"path": str(p), "exists": p.exists(),
               "writable": p.exists() and os.access(p, os.W_OK)}
        for name, p in HIDG_DEVICES.items()
    }
    return out


# --------------------------------------------------------------------------- #
# /dev/hidgN helpers
# --------------------------------------------------------------------------- #
def ensure_chardev_open() -> bool:
    """Open the cached /dev/hidgN FDs if not already open. Returns
    ``True`` on success, ``False`` if any device is missing or
    unwritable. This is the "warmup" entry point — preferred over
    :func:`get_chardev_fd` for read-only callers that just want to
    know whether the device is ready."""
    return _ensure_chardev_open_done()


_FD_CACHE: dict[str, int] = {}
_FD_LOCK = threading.RLock()
_FD_KEYS = {"keyboard": HIDG_DEVICES["keyboard"],
            "digitizer": HIDG_DEVICES["digitizer"]}


def _ensure_chardev_open_done() -> bool:
    """Reopen FDs lazily. Idempotent."""
    with _FD_LOCK:
        for name, path in _FD_KEYS.items():
            if name in _FD_CACHE:
                continue
            if not path.exists():
                # Missing → drop the cache and report failure.
                _close_cached_fds()
                return False
            # MUST be O_NONBLOCK: Linux 6.x's f_hid.c returns EAGAIN
            # when the single-slot request buffer is busy, regardless
            # of blocking mode. So we open non-blocking and use
            # :func:`safe_write` below to wait for the slot to drain
            # before each write (≈ USB poll interval, typically 1 ms
            # at high-speed).
            try:
                _FD_CACHE[name] = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as e:
                LOG.warning("open %s: %s", path, e)
                _close_cached_fds()
                return False
    return True


def _close_cached_fds() -> None:
    for fd in _FD_CACHE.values():
        try:
            os.close(fd)
        except OSError:
            pass
    _FD_CACHE.clear()


def get_chardev_fd(name: str) -> int:
    """Public accessor: return the cached FD for ``"keyboard"`` or
    ``"digitizer"``. Opens the chardev lazily on first call.

    Raises :class:`GadgetError` if the device is missing or unwritable;
    callers can convert that to an HTTP 503."""
    if name not in _FD_KEYS:
        raise GadgetError(f"unknown HID function {name!r}")
    with _FD_LOCK:
        if name not in _FD_CACHE:
            if not _ensure_chardev_open_done():
                raise GadgetError(
                    f"HID device {HIDG_DEVICES[name]} missing — "
                    "is the gadget bound to a UDC? "
                    "Run scripts/setup_usb_hid_gadget.sh once."
                )
        return _FD_CACHE[name]


def safe_write(fd: int, data: bytes, *, retries: int = 50,
               retry_sleep: float = 0.002) -> int:
    """Write ``data`` to a non-blocking ``/dev/hidgN`` FD, retrying on
    EAGAIN until the gadget driver's single-slot buffer drains.

    The driver holds a single pending URB per endpoint; a second
    ``write`` while the previous URB hasn't been completed by the
    host (USB poll) returns ``EAGAIN``. We retry with a small
    backoff (``retry_sleep`` seconds) for up to ``retries`` attempts
    (~100 ms wall-time at the defaults), then raise :class:`GadgetError`
    so the HTTP layer returns 502 instead of leaving the caller
    hanging forever if the host stops polling (cable unplugged etc.).

    Also handles ``BrokenPipeError`` (errno 108) by **invalidating
    ONLY the cached FD for the function that just failed and
    re-opening it** (without disturbing the other function's FD
    cache). This fires when the user has just re-bound the gadget
    (the old chardev was closed by the kernel's configfs teardown
    but our :data:`_FD_CACHE` still holds the now-stale FD). One
    re-open is enough; if it still fails the underlying problem is
    the gadget being absent, not a transient stale FD.

    Returns the number of bytes written (always ``len(data)`` — the
    driver either takes the whole report or returns EAGAIN).
    """
    for attempt in range(retries):
        try:
            return os.write(fd, data)
        except BlockingIOError:
            # Slot is full; the host hasn't polled the previous report.
            # Sleep, retry until the host catches up.
            if attempt == retries - 1:
                raise GadgetError(
                    f"/dev/hidg write stalled after {retries} retries — "
                    "is the host polling? (cable unplugged?)"
                )
            time.sleep(retry_sleep)
        except BrokenPipeError:
            # Cached FD is stale — gadget was torn down / rebound while
            # we held it. Find the function key for this FD, close it,
            # re-open only that function. Then loop and try the write
            # again with the new FD.
            new_fd = _reopen_stale_fd(fd)
            if new_fd is None:
                raise GadgetError(
                    "HID device disappeared during write — "
                    "is the gadget still bound? Run "
                    "scripts/setup_usb_hid_gadget.sh"
                )
            fd = new_fd
            # Loop continues; next iteration writes to the fresh FD.


def _reopen_stale_fd(stale_fd: int) -> int | None:
    """Close the cached FD that matches ``stale_fd`` and open a new one
    in its place. Returns the new FD, or ``None`` if the device is no
    longer present (gadget fully gone).

    Only the matching function's FD is touched — the other function's
    FD cache entry is left intact, so a keyboard write that hits a
    stale FD doesn't accidentally reopen the digitizer FD.
    """
    with _FD_LOCK:
        for name, cached_fd in list(_FD_CACHE.items()):
            if cached_fd == stale_fd:
                try:
                    os.close(cached_fd)
                except OSError:
                    pass
                _FD_CACHE.pop(name, None)
                path = HIDG_DEVICES[name]
                if not path.exists():
                    return None
                try:
                    new_fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
                except OSError as e:
                    LOG.warning("reopen %s: %s", path, e)
                    return None
                _FD_CACHE[name] = new_fd
                return new_fd
    # FD not found in cache — someone else closed it already; treat
    # the gadget as gone and let the caller surface a useful error.
    return None


def close_chardevs() -> None:
    """Drop the cached /dev/hidgN FDs. Used at shutdown and on gadget
    teardown so the host sees a real disconnect instead of a write
    against a stale FD."""
    with _FD_LOCK:
        _close_cached_fds()
