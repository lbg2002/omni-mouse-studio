# Delux M618XSD Linux Driver & 3D Control Center

专为 **DELUX 多彩 M618XSD (Seeker)** 垂直人体工学鼠标（无线 2.4G / 有线双通道 `1d57:fa60`）打造的 Linux 原生硬件驱动、按应用智能重映射引擎与 3D 硬件控制中心。

采用 **「极简常驻后台 + 按需全量 3D 界面」** 双层低功耗架构：
- **极简常驻层（`m618xsd-daemon` + `m618xsd-tray`）**：平时仅常驻内核事件驱动守护进程与顶部通知栏轻量图标，**空闲 0.0% CPU 占用**，不加载任何浏览器/3D 引擎。
- **按需全量层（`m618xsd-studio`）**：仅当从**系统顶部通知栏菜单**或桌面图标点击 **「打开控制中心 (全量 3D 模式)」** 时才启动 WebGL 实时 3D 建模与硬件调参界面；**关闭窗口即 100% 退出并彻底释放全部显存与内存**。

---

## 核心特性

### 1. 硬件板载直写（烧录进鼠标内置 Flash 芯片，拔下换电脑依然生效）
- **5 档光学传感器 DPI (`Report 0x04`)**：支持 5 档独立开关、`400–4000 DPI` 步进调节、每档独立 RGB 指示灯颜色。
- **USB 回报率 (`Report 0x06`)**：支持 `125 Hz` / `250 Hz` / `500 Hz` / `1000 Hz` 一键切换。
- **蜂巢尾翼 RGB 灯效与省电参数 (`Report 0x05`)**：炫彩流光、霓虹渐变、单色常亮/呼吸、跟随 DPI 档位色、关闭灯光；支持亮度（1–8）、流光速度（1–5）、静止灭灯时间（0.5–30 分钟）、深度休眠时间（1–60 分钟）及微动防双击消抖延迟（4–50 ms）。
- **板载按键直写映射 (`Report 0x08`)** 与 **出厂固件快照一键恢复 (`factory_backup.json`)**。
- **零干扰被动电量监控 (`Interrupt 0x03`)**：只读被动监听无线唤醒与状态上报报文，实时同步电量百分比与充放电状态，绝不干扰 2.4G 无线通信。

### 2. 智能应用联动与罗技级四向鼠标手势（Linux `evdev` + `uinput` 双虚拟设备引擎）
- **按焦点应用自动切换方案 (Per-App Profiles)**：原生适配 **Ubuntu GNOME (Wayland AT-SPI2 & X11)**、Hyprland 等环境；内置 **网页浏览器 / PDF 与图片查看器 / WPS 办公套件 / 代码 IDE / 终端** 专属预设，并提供 **「一键从运行中/已安装应用列表添加」**。
- **拇指球形侧滚轮增强**：支持按软件自动切换为标签页切换（`Ctrl+Tab` / `Ctrl+Shift+Tab`）、画面智能无级缩放（自动识别 `Loupe` / `Evince` 发送 `Ctrl+=/-` 或通用 `Ctrl+滚轮`）、横向倍速平滑滚动、系统音量调节、时间轴快进等。
- **罗技风格四向滑动手势 + 滚轮弦联动**：
  - 例如按住后退侧键：轻点单击保持原生「后退」；按住上滑呼出多任务概览（`Super`）；下滑最小化窗口（`Super+H`）；左/右滑切换工作区；**按住侧键 + 拨动主滚轮**直接调节音量；内置内核按键位图校验防卡死保护。
- **按住精准微操模式 (Sniper Mode)**、**多步延迟宏序列**与**自定义 Shell 命令触发**。

---

## 安装方式

### 方式一：源码一键安装（推荐本机日常使用与二次开发）
```bash
git clone https://github.com/lbg2002/delux-m618xsd-driver.git
cd delux-m618xsd-driver
./install.sh
```
安装脚本会自动配置：
1. `udev` 非 root 设备权限规则（`/dev/hidraw*`、`/dev/input/event*`、`/dev/uinput`）
2. `systemd --user` 开机自启极简守护服务 `delux-m618xsd-daemon.service`
3. `systemd --user` 顶部通知栏常驻托盘服务 `delux-m618xsd-tray.service`
4. 系统应用菜单图标 **「多彩 M618XSD 硬件控制中心」** 与命令行工具软链接

如需卸载用户态服务与启动器：
```bash
./uninstall.sh
```

### 方式二：构建并安装 Debian / Ubuntu `.deb` 软件包
```bash
./packaging/build-deb.sh
sudo apt install ./dist/delux-m618xsd-driver_1.0.0_all.deb
systemctl --user enable --now delux-m618xsd-daemon.service delux-m618xsd-tray.service
```

---

## 日常使用与命令行工具

- **通知栏快捷控制（常驻极简模式）**：点击屏幕右上角系统通知栏的鼠标图标，可查看实时电量与当前命中方案、一键开关「按焦点应用自动切换」、切换回报率，或点击 **「打开控制中心 (全量 3D 模式)」** 调出完整界面。
- **全量 3D 控制中心（按需运行）**：
  ```bash
  m618xsd-studio
  ```
- **命令行工具 (`m618xsd-cli`)**：
  ```bash
  # 查看状态、电量、固件版本与当前生效方案
  m618xsd-cli status

  # 切换板载回报率 (125 / 250 / 500 / 1000)
  m618xsd-cli poll 500

  # 设置 DPI 档位与数值
  m618xsd-cli dpi --stage 2 --value 1600

  # 设置尾翼 RGB 灯效
  m618xsd-cli rgb --mode stream --brightness 6

  # 一键恢复出厂板载默认设置
  m618xsd-cli restore-factory
  ```

---

## 运行自检测试
```bash
/usr/bin/python3 tests/test_all.py
```

## License
[MIT](./LICENSE)
