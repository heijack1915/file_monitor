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
- 支持架构：x64、ARM64、x86（32位）
- Python 3.8+（未安装时 `run.bat` 会自动检测架构并引导安装）

## 首次运行

1. 将本文件夹复制到**本地磁盘**（不要用网络路径）
2. 双击 `run.bat`
3. 若 Python 未安装，脚本会自动检测 CPU 架构并显示菜单：
   - 选 `1` 通过 winget 自动安装对应架构的 Python 3.11
   - 选 `2` 打开官网手动下载
4. Python 安装完成后，**重新双击 `run.bat`**
5. 脚本自动安装依赖（flask / watchdog / psutil）并启动
6. 打开浏览器访问 http://localhost:5006

## 从网络路径运行

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
| run.bat | 双击运行，包含菜单选项 |
| build.bat | 打包为独立 exe 文件 |
| uninstall.bat | 彻底卸载 |

## 使用说明

1. 双击 `run.bat`（首次运行会自动安装 Python 依赖）
2. 打开浏览器访问 http://localhost:5006
3. 选择要监控的路径，点击「开始监控」

## 进程识别说明

约 85% 准确率，识别策略：
1. 目录缓存（5 秒 TTL）
2. psutil 查询（open_files → cwd → cmdline）
3. 路径规则兜底

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| 首次运行没反应 | 双击 `run.bat`，Python 安装完后需**重新运行一次** |
| CMD 显示 UNC 路径错误 | 复制到本地磁盘运行 |
| Python 未安装 | 运行 `run.bat`，按提示选择自动安装 |
| 进程显示 "unknown" | 文件操作太快，psutil 无法捕获 |
| CPU 占用高 | 减少监控路径，避免大目录 |
| 中文显示乱码（\uXXXX）| 需要 Flask 2.0+，运行 `pip install flask --upgrade` |

## 许可证

MIT
