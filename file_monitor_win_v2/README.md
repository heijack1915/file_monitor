# Windows 文件监控工具 v2

一个跨平台文件监控工具，提供 Web 界面，可在 Windows 10/11 上实时监控系统文件变化。

## 功能特性

- **实时监控**：基于 watchdog（Windows ReadDirectoryChangesW 后端）
- **进程识别**：使用 psutil 识别触发文件操作的进程
- **Web 界面**：深色主题，支持实时事件推送（SSE）
- **AI 分析**：支持 OpenAI 兼容接口进行智能分析
- **离线规则**：内置规则引擎分析进程和路径
- **低资源占用**：设计为最小系统开销

## 系统要求

- Windows 10/11
- 自动检测并安装 Python 3.8+（如未安装）

## 快速开始

### 首次运行（只需运行一次）

1. 下载或克隆本项目到**本地磁盘**（避免网络路径问题）
2. 双击 `run.bat`
3. 如果提示 Python 未安装，选择 `1` 自动安装
4. **安装完成后会自动启动程序，无需再次运行**

### 从网络路径运行

如果必须从网络路径（UNC）运行，Windows CMD 可能不支持。建议：
- 复制到本地磁盘（如 `C:\Tools\FileMonitor`）
- 或使用映射的网络驱动器

## 目录结构

```
file_monitor_win_v2/
├── run.py              # Python 启动脚本
├── run.bat             # Windows 入口（双击运行）
├── app.py              # Flask 后端
├── templates/
│   └── index.html     # Web 前端
├── requirements.txt     # 依赖清单
├── build.bat           # 打包为独立 exe
├── uninstall.bat        # 彻底卸载
└── README.md           # 本文件
```

## 脚本说明

| 脚本 | 说明 |
|------|------|
| run.bat | 双击运行，自动安装 Python 和依赖 |
| build.bat | 打包为独立 exe 文件 |
| uninstall.bat | 彻底卸载 |

## 使用说明

1. 运行 `run.bat`
2. 如果提示 Python 未安装，选择 `1` 安装（或选 `2` 手动下载）
3. 安装完成后程序**自动启动**
4. 打开浏览器访问 http://localhost:5006
5. 选择要监控的路径，点击「开始监控」

## 进程识别说明

约 85% 准确率，识别策略：
1. 目录缓存（5 秒 TTL）
2. psutil 查询（open_files → cwd → cmdline）
3. 路径规则兜底

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| CMD 显示 UNC 路径错误 | 复制到本地磁盘运行 |
| Python 未安装 | 运行 `run.bat`，选择自动安装 |
| 进程显示 "unknown" | 文件操作太快，psutil 无法捕获 |
| CPU 占用高 | 减少监控路径，避免大目录 |

## 许可证

MIT