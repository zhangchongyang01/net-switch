# NetSwitch · 有线 / WiFi 出网切换工具

Windows 同时插网线、连 WiFi 时，一键切换「哪张网卡负责出网」。不断开任何连接，秒级生效，新连接立即走新网卡。

## 原理

Windows 选默认路由比较的是 **默认路由 RouteMetric + 接口 InterfaceMetric 之和**，不是只看接口跃点。本工具：

1. 把目标网卡接口跃点固定为 `5`，关闭「自动跃点」；
2. 其它物理网卡设为动态计算的大值（`min(9999, max(200, 最大默认路由 RouteMetric + 5 + 50))`），用于抵消公司有线网常见的 `256` 偏置；
3. 用 `Find-NetRoute` **实测校验**，没真生效就报错，不盲报成功；
4. 不修改路由表本身，点「恢复自动」即可完全还原。

## 前置条件

| 项 | 要求 |
| --- | --- |
| 系统 | Windows 8 / 10 / 11 或 Server 2012+（PowerShell 5.1 + NetAdapter 模块） |
| 权限 | **本地管理员**（脚本自动弹 UAC；域控机器无管理员则不可用） |
| GUI | Python 3，安装时勾选 **tcl/tk**；建议同时勾选 py launcher |
| 网络 | 两张网卡都要处于 Up（未连 WiFi 时无法切换） |

只要零依赖、不装 Python：直接用 `deliver/` 里的三个 bat。

## 快速开始（GUI + 桌面快捷方式）

```bash
git clone https://github.com/zhangchongyang01/net-switch.git
cd net-switch
python make_shortcuts.py
```

生成器会在**当前用户桌面**创建 4 个图标：`网络切换器`、`切换网络`、`查看状态`、`恢复自动`。双击「网络切换器」→ UAC 点「是」→ 打开 GUI。

> 桌面 `.lnk` 内含本机绝对路径（Python 位置、脚本位置、桌面位置），**不能随仓库分发**，必须每台机器本地生成。生成器已适配 py launcher 位置差异、OneDrive / 企业桌面重定向、以及缺少 tkinter 的情况。

不跑命令行也行：直接双击目录里的 `start_gui.bat` 即可启动 GUI。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `NetSwitch.ps1` | 核心 PowerShell 脚本，全部切换逻辑 |
| `net_switch_gui.py` | tkinter 图形界面 |
| `make_shortcuts.py` | 生成本机桌面快捷方式 |
| `start_gui.bat` | GUI 启动入口 |
| `toggle.bat` / `status.bat` / `reset.bat` | 一键切换 / 查看状态 / 恢复自动（三个快捷方式指向它们） |
| `deliver/` | 零依赖交付包（纯 PowerShell，给没装 Python 的同事） |
| `同步交付包.bat` | 改动主脚本后同步 `deliver/` 快照 |
| `build_exe.bat` | 用 PyInstaller 打单文件 exe |

## 命令行用法

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File NetSwitch.ps1 -List           # 查看网卡与跃点
powershell -NoProfile -ExecutionPolicy Bypass -File NetSwitch.ps1 -Toggle        # 一键切换
powershell -NoProfile -ExecutionPolicy Bypass -File NetSwitch.ps1 -Use 16        # 指定 ifIndex
powershell -NoProfile -ExecutionPolicy Bypass -File NetSwitch.ps1 -Reset         # 恢复自动
powershell -NoProfile -ExecutionPolicy Bypass -File NetSwitch.ps1 -Toggle -Hard  # 彻底模式（禁用另一张卡）
```

`deliver/` 里的三个中文 bat 与之等价。特殊网络可加 `-ProbeIP 114.114.114.114` 更换探测地址。

## 注意事项

- 改的是**持久配置**，重启仍在；停用务必点「恢复自动」或运行 `reset.bat`。
- 切换只影响新建连接，已建立的 TCP 连接不会迁移；企业内网域名解析异常时重开浏览器。
- 切换没生效时先跑 `route print -4` 看活跃默认路由的跃点列；VPN / 虚拟网卡 / 组策略可能注入更优路由。
- `NetSwitch.ps1` 必须保留 **UTF-8 BOM**：PowerShell 5.1 按 ANSI 读取无 BOM 文件会导致中文乱码（`.gitattributes` 已禁止转换）。
- 中文文件名的 bat 在 Git 里正常，`git status` 显示为八进制转义属正常现象。

## 已知限制

- 仅 Windows，依赖 PowerShell 5.1（不调用 PowerShell 7）。
- `make_shortcuts.py` 生成的 lnk 用系统 ANSI 编码写 LinkInfo，非中文系统 + 中文路径可能显示异常。
- 打包的单文件 exe 可能被企业 EDR / 杀软拦截；exe 建议走 GitHub Release，不提交到仓库。
