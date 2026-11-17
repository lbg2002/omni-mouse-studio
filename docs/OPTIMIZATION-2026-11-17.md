# Omni Mouse Studio v1.2.5：功能、性能与稳定性优化

基准：v1.2.4 / `4964937`。本批改动不改变鼠标原生 HID 协议、默认宏配置或现有 WebGL 3D 页面。

## 实际改动

| 类别 | 改动 | 机制/边界 |
| --- | --- | --- |
| 配置可靠性 | 保存时独立临时文件 + fsync + 原子替换 | 多入口写入统一通过文件锁；已有合法配置存 `.bak`，损坏时只读回退 |
| 设备选择 | 显式型号严格匹配 | 不再回退抓取其他型号 |
| 延迟 | 高开销快捷键与宏在单一工作线程执行 | 事件读取线程不等待 12–36ms 模拟按键；队列上限 64，溢出记录丢弃量 |
| 资源 | 宏不再按触发次数创建线程 | 队列串行执行；单次宏最多 100 步，关闭时停止 |
| 恢复 | evdev `SYN_DROPPED`/EOF、uinput 写失败等路径 | 输入丢帧重新接管，错误时释放独占；设备断开时释放镜像按键 |
| 健康检查 | 新增 CLI `doctor [--json]` | 不执行 HID 硬件读写；报告权限、服务、托盘、待执行动作、丢弃数量 |
| 控制中心 | 静态文件路径使用 realpath/commonpath | 仅允许预期资产目录内文件；POST JSON 限制 1 MiB |
| 托盘 | 区分守护进程与虚拟输入是否正常 | 不再用“守护在线”代表“设备已接管” |

## 更新 / 验证

源码安装：

```bash
git pull --ff-only
./install.sh
omni-mouse-cli doctor
systemctl --user status omni-mouse-daemon.service omni-mouse-tray.service
```

deb 安装或升级：

```bash
bash packaging/build-deb.sh
sudo apt install ./dist/omni-mouse-studio_1.2.5_all.deb
systemctl --user daemon-reload
systemctl --user enable --now omni-mouse-daemon.service omni-mouse-tray.service
systemctl --user restart omni-mouse-daemon.service omni-mouse-tray.service
omni-mouse-cli doctor
```

若以前曾用 `./install.sh` 源码安装，用户目录内旧 unit 会覆盖 deb 的 unit。务必先按 `docs/RESIDENCY-TROUBLESHOOTING.md` 处理混合安装，不要直接删除个人配置。

自动测试：CI 执行已有回归和 `tests/test_optimizations.py`、Python 编译、Shell 语法、deb 构建。

## 真机验收（尚未在当前环境完成）

1. 连续移动鼠标并高频滚轮切标签时，观察光标是否有可感知卡顿、按键是否按顺序完成
2. 拔插 USB、无线断线、休眠/恢复、锁屏/解锁后检查是否出现虚拟按键粘滞
3. 多次快速通过托盘/控制中心/CLI 切换设备或开关映射，检查保存结果与 `.bak`
4. `omni-mouse-cli doctor --json` 中确认 `dropped_actions` 在正常使用下为零，异常峰值有明确计数
5. 用 `systemctl --user status` 与 `journalctl --user` 对比 24h RSS、CPU、重启次数和真实设备稳定性

**无真机延迟/内存测量，本批不声称量化提速或长期稳定性完全达标。**

## 保守设计

- 过量宏动作直接丢弃而不是无限排队，因此极端触发量下可能漏掉部分快捷键；可通过 `doctor` 发现
- 保留物理鼠标原生直通和设备错误时主动释放 EVIOCGRAB 的安全优先策略
- 旧版配置自动兼容，不删除用户配置、硬件备份和已录入的方案
