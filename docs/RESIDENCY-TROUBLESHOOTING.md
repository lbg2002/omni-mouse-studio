# 后台驻留与失效排查 (v1.2.4)

## 架构与预期

- `omni-mouse-daemon.service` 随 systemd 用户管理器的 `default.target` 启动，不依赖 Studio 窗口、托盘或硬件是否在线。
- `omni-mouse-tray.service` 仅在图形会话中运行；deb 不再同时配置 XDG 自启动，避免两份托盘实例。
- 硬件热插拔、设备节点重建或 evdev EOF 后重新探测鼠标，释放旧的 `EVIOCGRAB`。
- `/dev/uinput` 权限不足时，后台 IPC 仍运行，保持物理鼠标原生直通，5 秒间隔重试。修好权限后自动恢复。
- 关闭 3D Studio 窗口不影响后台服务。退出托盘只退出托盘，不停止鼠标守护进程。

## 使用源码安装升级

```bash
git pull --ff-only
./install.sh
systemctl --user status omni-mouse-daemon.service omni-mouse-tray.service --no-pager
omni-mouse-cli status
```

不要通过 `sudo ./install.sh` 运行：用户服务必须以桌面登录用户身份安装。权限规则安装步骤本身会请求提权。

## 使用 deb 升级

```bash
bash packaging/build-deb.sh
sudo apt install ./dist/omni-mouse-studio_1.2.4_all.deb
systemctl --user daemon-reload
systemctl --user enable --now omni-mouse-daemon.service
systemctl --user restart omni-mouse-daemon.service
systemctl --user enable --now omni-mouse-tray.service
```

**注意**：以前若用源码安装，`~/.config/systemd/user/omni-mouse-*.service` 会覆盖 deb 自带单元。先执行旧源码目录的 `./uninstall.sh` 清理这些用户单元（保留个人配置），然后重新安装 deb。不要同时使用两种安装来源。

## 失效时检查

```bash
systemctl --user is-active omni-mouse-daemon.service omni-mouse-tray.service
systemctl --user show omni-mouse-daemon.service -p ExecMainStatus -p NRestarts -p ActiveState
journalctl --user -u omni-mouse-daemon.service -u omni-mouse-tray.service --since '2 hours ago' --no-pager
omni-mouse-cli status
ls -l /dev/uinput /dev/input/event* /dev/hidraw* 2>/dev/null
id -nG
```

如果 `daemon` 返回在线但 `virtual_ready=false`，优先检查 `/dev/uinput` 的 ACL/组权限、udev 规则和当前用户组成员资格。通过 `usermod -aG` 新增组成员后，需要重新登录才能获得新组权限。

如果服务在线但 `grabbed=false`，检查设备事件节点是否可读、鼠标是否处于休眠或 USB 重连状态，以及 `daemon_enabled` 配置是否被关闭。

GNOME Wayland 的托盘图标需要桌面支持 AppIndicator；图标不显示不代表守护进程未运行。先检查服务和 CLI 状态，再排查 GNOME 扩展。

## 验收范围

CI 负责 Python 编译、无硬件回归、Shell 语法和 deb 构建。以下测试必须在装有目标鼠标的 Ubuntu/GNOME 真机执行，不以 CI 替代：

1. 登录后不打开 Studio，检查后台 daemon、托盘与侧键映射；
2. USB 拔插、无线设备休眠与唤醒后验证恢复；
3. 锁屏/解锁、系统挂起/恢复后检查设备权限和映射；
4. 手动停掉 daemon、删除 uinput 权限，观察诊断日志和恢复；
5. 连续运行 24 小时，监视 RSS、CPU、重启次数和异常日志。

**未完成上述真机验证前，不宣称长期驻留问题已完全解决。**
