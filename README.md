# Omni Mouse Studio (`omni-mouse-studio`)

**Omni Mouse Studio** 是一款面向 Linux 桌面（Wayland / X11）的全能多设备鼠标原生硬件驱动、按焦点应用智能重映射引擎与 WebGL 实时 3D 硬件智控中心。

目前原生支持 **Inphic 英菲克 W1** 有线宏定义游戏鼠标（`30fa:1701` / `Instant A704`）与 **DELUX 多彩 M618XSD (Seeker)** 垂直人体工学无线/有线双模鼠标（`1d57:fa60`），后续可持续扩展更多品牌型号。

支持 **「自动识别在线鼠标 + 界面/托盘一键切换型号」**，并采用 **「极简常驻后台 + 按需全量 3D 界面」** 双层低功耗架构：
- **极简常驻层（`omni-mouse-daemon` + `omni-mouse-tray`）**：平时仅常驻内核事件驱动守护进程与顶部通知栏轻量图标，**空闲 0.0% CPU 占用**，不加载任何浏览器/3D 引擎。
- **按需全量层（`omni-mouse-studio`）**：仅当从**系统顶部通知栏菜单**或桌面图标点击 **「打开控制中心 (全量 3D 模式)」** 时才启动专属 WebGL 实时 3D 建模与硬件调参界面；**关闭窗口即 100% 退出并彻底释放全部显存与内存**。

---

## 支持设备与硬件能力对照

| 模块能力 | 英菲克 Inphic W1 有线版 (`30fa:1701`) | 多彩 Delux M618XSD (`1d57:fa60`) |
| :--- | :--- | :--- |
| **实时 3D 建模** | V 型分割枪灰机甲盖板 + 中脊菱形 `CPI` 键 + 左侧五道斜向导流槽 + 发光 `in` 徽标 | 垂直人体工学机身 + 蜂巢发光尾翼 + 磁吸手托 + 球形拇指轮 |
| **按应用自动切换方案** | **完整支持**（浏览器 / PDF图片 / WPS / IDE / 终端） | **完整支持**（浏览器 / PDF图片 / WPS / IDE / 终端） |
| **侧键四向滑动手势 & 宏** | **前进键 / 后退键 / 中键 四向滑动 + 滚轮弦 + 宏** | **前进键 / 后退键 / 中键 四向滑动 + 滚轮弦 + 宏** |
| **侧滚轮 / 虚拟侧滚轮** | **「按住前进侧键 + 拨动主滚轮」虚拟侧滚轮一键快设**（切标签/PDF缩放/横向滚轮/音量，单击前进键仍保持原生前进） | 独立球形拇指侧滚轮一键快设 |
| **传感器档位硬件直写** | **4 档硬件 CPI** (`400–4800 CPI`, 步进 400, Feature `0x07` / Cmd `0x09`) + 顶部物理 `CPI` 键切档实时同步 (`Interrupt 0x06`) | 5 档 DPI (`400–4000 DPI`, Report `0x04`) + 1000Hz 回报率 (`Report 0x06`) |
| **灯光系统控制** | **8 种芯片背光呼吸/律动频率、常亮与一键关灯** (`0x10..0x17`, Cmd `0x13`) | 尾翼全彩 RGB 流光/呼吸/亮度/双级休眠 (`Report 0x05`) |
| **芯片按键寄存器** | **Instant A704 6 槽硬件寄存器**（含硬件三连发火力键 `0x16`、双击键 `0x17` 等，本地持久化热插拔自动重放） | Flash 永久直写 (`Report 0x08`) + 零干扰被动电量监控 (`Interrupt 0x03`) |

---

## 安装方式

### 方式一：源码一键安装（推荐本机日常使用与二次开发）
```bash
git clone https://github.com/lbg2002/omni-mouse-studio.git
cd omni-mouse-studio
./install.sh
```
安装脚本会自动配置：
1. `udev` 非 root 多设备权限规则（`/dev/hidraw*`、`/dev/input/event*`、`/dev/uinput`）
2. `systemd --user` 开机自启极简守护服务 `omni-mouse-daemon.service`
3. `systemd --user` 顶部通知栏常驻托盘服务 `omni-mouse-tray.service`
4. 系统应用菜单图标 **「Omni Mouse 多功能鼠标智控中心」** 与命令行工具软链接

如需卸载用户态服务与启动器：
```bash
./uninstall.sh
```

### 方式二：构建并安装 Debian / Ubuntu `.deb` 软件包
```bash
./packaging/build-deb.sh
sudo apt install ./dist/omni-mouse-studio_1.2.0_all.deb
systemctl --user enable --now omni-mouse-daemon.service omni-mouse-tray.service
```

---

## 日常使用与命令行工具

- **通知栏快捷控制（常驻极简模式）**：点击屏幕右上角系统通知栏的鼠标图标，可查看当前识别设备与生效方案、一键切换管理型号、开关「按焦点应用自动切换」，或点击 **「打开控制中心 (全量 3D 模式)」** 调出完整界面。
- **全量 3D 控制中心（按需运行）**：
  ```bash
  omni-mouse-studio
  ```
- **命令行工具 (`omni-mouse-cli`)**：
  ```bash
  # 查看在线鼠标型号、CPI/DPI、灯光及守护进程状态
  omni-mouse-cli status

  # 切换识别策略 (auto / inphic_w1 / delux_m618xsd)
  omni-mouse-cli model auto

  # 设置当前激活鼠标的 CPI / DPI 档位与数值
  omni-mouse-cli dpi --stage 2 --value 1200

  # 设置背光 / RGB 模式
  omni-mouse-cli rgb --mode steady

  # 一键恢复当前鼠标出厂硬件默认参数
  omni-mouse-cli restore-factory
  ```

---

## 运行自检测试
```bash
/usr/bin/python3 tests/test_all.py
```

## License
[MIT](./LICENSE)
