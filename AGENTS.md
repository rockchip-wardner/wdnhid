# AGENTS.md

Quick reference for agent sessions in this repo.

Python library for driving the Linux USB Gadget HID functions through
`configfs` and the `/dev/hidgN` character devices. It lets a Rockchip
board advertise itself to a host PC as one or more HID devices —
keyboard, mouse, digitizer — by writing HID report blobs into the gadget
device. Distribution / import name `wdnhid`.

## 仓库地址与同步策略（2026-11-10）

| 角色 | 地址 | 允许的操作 |
|---|---|---|
| **局域网主仓库** | http://10.10.10.10:8080/wardner | **pull + push** —— 唯一权威源，所有更新的第一站 |
| **GitHub** | https://github.com/rockchip-wardner | **只允许 push** —— 发布镜像，不从它 pull |
| **Gitee 国内镜像** | https://gitee.com/rockchip-wardner | **不允许任何 git 操作** —— 公开只读镜像，内容由上游自动同步 |

远端命名：`origin` = `git@10.10.10.10:wardner/wdnhid.git`（局域网），
`github` = `git@github.com:rockchip-wardner/wdnhid.git`（只 push）。

**提交顺序不可颠倒：先 `git push origin master`（局域网主仓库），再
`git push github master`（GitHub）。Gitee 一概不碰。** `master` 的跟踪分支指向
`origin`，裸 `git pull` / `git push` 即为对主仓库操作。拉取最新代码只走局域网
主仓库 —— 从 GitHub 拉的是「已发布出去的历史」，会让本地与主仓库分叉。

## 提交信息规范（2026-11-11）

**commit message 必须用英文。**

- 格式：Conventional Commits —— `type(scope): subject`，正文（若有）也用英文。
  例：`feat(hid): add a digitizer report descriptor`
- 原因：本仓发布到公开的 GitHub 镜像（发布镜像 = 国际可见），提交历史是给国际读者
  看的 —— 中文提交信息让公开历史没法读。
- **只约束提交信息**：代码注释、docstring、仓内文档（AGENTS.md / README）仍按各仓
  现有的写法（中文没问题）。README 是中英双语，AGENTS.md 允许中文。


## Repo map (one-line each)

- `src/wdnhid/manager.py` — the gadget manager: claims a HID function in `configfs`, opens `/dev/hidgN`, writes reports.
- `src/wdnhid/hid_descriptors.py` — HID report descriptor builders.
- `src/wdnhid/keycodes.py` — keycode tables.
- `tests/` — unit tests.
- `MANIFEST.in` — sdist contents.
