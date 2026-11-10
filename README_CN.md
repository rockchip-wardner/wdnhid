[English](README.md) | [简体中文](README_CN.md)

# wdnhid

通过 ``configfs`` 和 ``/dev/hidgN`` 字符设备驱动 Linux USB Gadget HID 功能的
Python 库。

让一块 Linux 板子（通常是 RK3588 / Rockchip 平台，即 ``wdn*`` 系列）向宿主 PC
声明自己是一个或多个 HID 设备——键盘、鼠标、数字化仪——方式是把 HID 报告块写到
``/dev/hidg0``、``/dev/hidg1`` 等设备节点。

本包刻意只做**传输层**。它做：

* configfs 树管理（用正确的 string / config / function 描述符创建或拆除 gadget）
* UDC bind / unbind
* HID 报告描述符拼装
* 往 ``/dev/hidgN`` 写时遇 EAGAIN 重试，遇 ``BrokenPipeError`` 自动重开
  （gadget 重新 bind 时内核会关掉字符设备）

它**不做**：

* 不跑网络服务（那是使用方的事——在我们这儿是 ``wdnwebui`` 的 ``usb-hid``
  卡挂 FastAPI 路由）
* 不枚举宿主侧的 HID 设备（使用方若关心宿主状态，自己读 ``/sys/class/udc/``）
* 不带任何 AI / LLM 依赖（有意为之）

## 环境要求

* 内核带 ``CONFIG_USB_CONFIGFS_F_HID=y``（及同类项）。RK3588 自带的 6.12
  内核默认就是开的。
* 一个空闲的 UDC（USB 设备控制器）——通常是 OTG 口。通过 ``/sys/class/udc/``
  发现。
* 写 ``configfs`` 需要 root（``/sys/kernel/config/usb_gadget/``）。内核的
  ``/dev/hidgN`` 字符设备要授予「使用方进程所跑的用户」组写权限；见使用本包的
  项目里的 ``99-wdnhid-gadget.rules`` 片段（``wdnwebui/scripts/``）。

## 安装

从 GitHub 装 editable 版（推荐）：

```bash
pip install -e "git+ssh://git@github.com:rockchip-wardner/wdnhid.git#egg=wdnhid"
```

或者从已有检出目录装：

```bash
pip install -e /path/to/wdnhid
```

构建 wheel（用于分发）：

```bash
cd /path/to/wdnhid
python -m build
pip install dist/wdnhid-0.1.0-*.whl
```

## 快速上手

```python
from wdnhid import manager, keycodes as kc

# 1. 建 gadget 树 + 绑到第一个可用 UDC。
#    幂等：用同样的参数重跑等于什么都没做。
manager.setup_gadget(vid=0x1D6B, pid=0x0103,
                     manufacturer="acme", product="HID bridge",
                     serial="hid-001")

# 2. 写一个 8 字节的 boot keyboard 报告。
fd = manager.get_chardev_fd("keyboard")
manager.safe_write(fd, bytes([0, 0, kc.KEYCODES["h"],
                                kc.KEYCODES["e"],
                                kc.KEYCODES["l"],
                                kc.KEYCODES["l"],
                                kc.KEYCODES["o"], 0]))
manager.safe_write(fd, bytes([0, 0, 0, 0, 0, 0, 0, 0]))   # 松开

# 3. 移动绝对坐标数字化仪。
fd = manager.get_chardev_fd("digitizer")
manager.safe_write(fd, bytes([0x01, 0x00, 0x40, 0x0F, 0x00]))  # tip, X=4000, Y=0

# 4. 退出时拆除。
manager.teardown_gadget()
```

## 模块结构

* ``wdnhid.manager`` —— configfs 树 + UDC bind + ``/dev/hidgN`` FD 缓存，
  带重试 / 重开逻辑。
* ``wdnhid.keycodes`` —— USB HID Boot Keyboard usage ID、``char_to_keycode``、
  ``name_to_keycode``、``parse_modifier``。
* ``wdnhid.hid_descriptors`` —— Boot Keyboard 与 Digitizer / Tablet 报告描述符
  的原始 ``bytes``。

## License

Apache-2.0。见 [LICENSE](LICENSE)。
