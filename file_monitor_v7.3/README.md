# macOS 文件监控 v7.3

基于 `fs_usage` + `watchdog` 双引擎的 macOS 文件系统监控工具，通过 Web 界面实时展示文件操作事件及操作进程，v7.3 新增 AI 事件分析功能。

## 版本历史

### v7.3 新增
| 功能 | 说明 |
|------|------|
| AI 事件分析 | 每条日志可点击「🤖 AI 分析」，调用任意 OpenAI 兼容接口解读事件含义、进程来源、风险评估 |
| 离线规则分析 | 点击「📖 离线分析」，无需网络，本地规则引擎即时给出解读 |
| 服务商快速预设 | 一键填写 Deepseek / OpenAI / 阿里通义 / Kimi / 灵芽 / n1n 等平台的接口地址和模型名 |
| Key 获取指引 | 面板内展开式说明，指引各平台注册和获取 API Key |

### v7.2 修复
| 问题 | 根因 | 修复方式 |
|------|------|---------|
| 只能记录删除事件，写入/新建全部丢失 | `creat` syscall 未在关键字表中 | `WRITE_OP_KEYWORDS` 和 `OP_MAP` 加入 `creat` |
| 写入/新建事件路径匹配失败 | PTY 输出含 ANSI 转义码，字节级路径匹配被截断 | 先解码剥离 ANSI 再做字符串过滤 |
| write/wrdata 行无路径，写入事件全部丢失 | fs_usage 写入行只有 `F=fd B=bytes`，无绝对路径 | 新增 fd→path 缓存，从 open/creat 行提取并补全 |

### v7.1 修复
| 问题 | 修复方式 |
|------|---------|
| 筛选功能不生效，缺少执行按钮 | 改为纯前端过滤，新增「执行筛选」/「清除」按钮 |
| 刷新页面后事件不再更新 | SSE 断线 3s 自动重连 + 4s 轮询兜底 |
| 刷新后监控路径失效 | 服务端记录路径，页面刷新后自动恢复 |
| 自定义路径刷新后消失 | 自定义路径写入 `localStorage` 持久化 |

## 功能特性

- **双引擎监控**
  - `fs_usage`：捕获文件写入、新建、重命名、移入废纸篓等事件，并显示操作进程名
  - `watchdog FSEvents`：补充捕获 `rm -rf` 等命令行删除事件
- **AI 事件分析**（v7.3 新增）
  - 支持接入任意 OpenAI 兼容接口（Deepseek / 阿里通义 / Kimi / 灵芽 / n1n / OpenAI 等）
  - 本地离线规则引擎，无需 Key 即可使用
- **智能重命名识别**：区分真正的重命名 vs 移入废纸篓
- **实时推送**：SSE 毫秒级延迟，断线自动重连，轮询兜底不丢事件
- **前端筛选**：路径关键字、进程名、事件类型多维过滤
- **自定义监控路径**：支持任意目录，持久化到 localStorage
- **数据导出**：一键导出 JSON

## 目录结构

```
file_monitor_v7.3/
├── app.py              # 主程序（Flask + fs_usage + watchdog + AI 分析）
├── templates/
│   └── index.html      # Web 界面
├── requirements.txt    # Python 依赖
├── setup.sh            # 一键部署脚本
├── run.sh              # 启动脚本
├── uninstall.sh        # 彻底删除脚本
└── README.md           # 本文档
```

## 快速开始

### 1. 一键部署（首次使用）

```bash
cd /path/to/file_monitor_v7.3
chmod +x setup.sh
./setup.sh
```

setup.sh 自动完成：
- 检查 macOS 环境和 Python 3
- 创建 Python 虚拟环境
- 安装 `flask`、`watchdog` 依赖
- 配置 `fs_usage` 的 sudo 免密权限

### 2. 启动

```bash
./run.sh
```

### 3. 访问 Web 界面

打开浏览器访问：**http://localhost:5006**

### 4. 开始监控

1. 在右侧「监控路径」面板勾选要监控的目录
2. 点击「▶️ 开始监控」
3. 对文件进行操作，左侧实时显示事件
4. 点击任意事件上的「🤖 AI 分析」或「📖 离线分析」查看详细解读

## 系统要求

| 项目 | 要求 |
|------|------|
| 系统 | macOS 10.15+ |
| Python | 3.8+ |
| 权限 | sudo（用于运行 fs_usage） |

## AI 分析使用说明

### 配置 AI 接口（可选）

在右侧「AI 分析设置」面板中：

1. 点击服务商预设按钮（如 **Deepseek**），自动填入接口地址和模型名
2. 粘贴对应平台的 API Key
3. 点击「💾 保存配置」

| 服务商 | 接口地址 | 推荐模型 |
|--------|---------|---------|
| Deepseek | `https://api.deepseek.com/v1/chat/completions` | `deepseek-chat` |
| 阿里通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` | `qwen-turbo` |
| Kimi | `https://api.moonshot.cn/v1/chat/completions` | `moonshot-v1-8k` |
| 灵芽 | `https://api.lingyaai.cn/v1/chat/completions` | `claude-sonnet-4-6` |
| n1n | `https://api.n1n.ai/v1/chat/completions` | `claude-sonnet-4-6` |
| OpenAI | `https://api.openai.com/v1/chat/completions` | `gpt-4o-mini` |

### 离线分析（无需配置）

直接点击事件上的「📖 离线分析」，本地规则引擎即时分析，覆盖：
- 12 种操作类型解释
- 14 种常见进程识别（mdworker / Finder / backupd / Python / Claude 等）
- 路径特征识别（.DS_Store / .Trash / tmp / node_modules 等）
- 敏感路径风险提示（/etc / SSH 密钥 / keychain 等）

## 筛选使用说明

| 筛选项 | 说明 |
|--------|------|
| 关键字（路径） | 路径包含该字符串，不区分大小写 |
| 进程/应用 | 进程名包含该字符串，如 `Finder`、`python` |
| 事件类型 | 点击 Tag 选中（可多选），点「执行筛选」生效 |
| 执行筛选 | 过滤后计数显示「匹配数 / 总数」 |
| 清除 | 取消所有筛选，恢复显示全部事件 |

## 事件类型说明

| 事件 | 中文 | 触发场景 |
|------|------|---------|
| `create` / `creat` | 新建 | 新建文件 |
| `mkdir` | 新建目录 | 新建文件夹 |
| `write` / `wrdata` | 写入 | 文件内容修改、保存 |
| `unlink` | 删除 | `rm` 命令删除、程序内删除 |
| `rmdir` | 删除目录 | 删除空文件夹 |
| `rename` | 重命名 | Finder 重命名，显示新文件名 |
| `trash` | 删除(废纸篓) | Finder 移入废纸篓 |
| `truncate` | 截断 | 文件被清空或截短 |

## 技术说明

### 双引擎架构

```
fs_usage（sudo，内核追踪）──→ PTY → Python 解析 ──┐
                                                   ├──→ 事件入库 → SSE → 浏览器
watchdog FSEvents ──────────────────────────────────┘
```

`fs_usage` 负责写入/新建/重命名/废纸篓，`watchdog` 补充 `rm -rf` 删除（fs_usage 对 unlinkat 无法解析绝对路径）。

### fd→path 缓存（v7.2）

fs_usage 写入行（write/wrdata）只输出 `F=fd`，无路径。程序在 `open`/`creat` 行时记录 `fd→path` 映射，写入行无路径时自动补全。

### 废纸篓检测

Finder 移入废纸篓的底层是 `rename(src → ~/.Trash/filename)`。程序延迟 300ms 后检测：源文件是否消失 + `~/.Trash/` 下是否出现同名文件且 ctime 在合理时间窗口内。

### SSE 可靠性

- SSE 断线后 3s 自动重连
- 4s 轮询兜底：定期拉取 `/api/events` 按 id 去重补全
- 页面刷新时从 `/api/status` 恢复最近 200 条历史事件

### AI 分析接口（v7.3）

后端 `/api/analyze` 接受 `mode=ai`（转发到配置的外部接口）或 `mode=offline`（本地规则引擎），均返回结构化分析文本。支持任何 OpenAI Chat Completions 兼容格式。

### 端口

默认 **5006**，可在 `app.py` 末尾修改。

## 彻底删除

```bash
./uninstall.sh
```

## 常见问题

**Q: 启动后没有任何事件？**  
A: 确保已选择监控路径并点击「开始监控」。检查 sudo 免密：`sudo -n /usr/bin/fs_usage -h`

**Q: 只有删除事件，没有写入/新建？**  
A: v7.2 已修复此问题。如仍异常，可能有孤儿 fs_usage 进程占用 ktrace，执行 `sudo pkill -9 -f fs_usage` 后重新开始监控。

**Q: AI 分析提示连接失败？**  
A: 检查接口地址是否完整（需含 `/v1/chat/completions`），Key 是否正确。不想配置 AI 可直接用「📖 离线分析」。

**Q: 刷新页面后事件还在吗？**  
A: 在。页面刷新后自动从服务端拉取最近 200 条历史事件，Flask 进程不重启数据不丢失。

**Q: 端口被占用？**  
A: `lsof -ti:5006 | xargs kill -9`，或修改 `app.py` 末尾端口号。
