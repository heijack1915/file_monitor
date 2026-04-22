# macOS 文件监控 v8

基于 `watchdog FSEvents` + `lsof` 异步进程补查的 macOS 文件系统监控工具，通过 Web 界面实时展示文件操作事件及操作进程，内置 AI 事件分析功能。

## 版本历史

### v8 架构重写（当前版本）
| 变更 | 说明 |
|------|------|
| 主引擎替换 | 废弃 `fs_usage` 常驻方案，改用 `watchdog FSEvents` 作为主引擎 |
| 进程识别方式 | 改为 `lsof` 异步补查 + 路径规则兜底，不再解析 fs_usage 输出 |
| 不再需要 sudo | FSEvents 无需内核权限，无需配置 sudo 免密 |
| CPU 大幅降低 | 从 v7.x 的 40~75% 降至 < 5% |
| 无 ktrace 冲突 | 不再独占 ktrace 资源，无 "Resource busy" 问题 |

### v7.3 新增
| 功能 | 说明 |
|------|------|
| AI 事件分析 | 每条日志可点击「🤖 AI 分析」，调用任意 OpenAI 兼容接口解读事件 |
| 离线规则分析 | 点击「📖 离线分析」，本地规则引擎无需网络即时给出解读 |
| 服务商快速预设 | 一键填写主流平台接口地址和模型名 |

### v7.2 修复
| 问题 | 修复方式 |
|------|---------|
| 只能记录删除事件 | 修复 `creat` syscall 识别、ANSI 码过滤、fd→path 缓存三个根因 |

### v7.1 修复
| 问题 | 修复方式 |
|------|---------|
| 筛选不生效 | 改为纯前端过滤 |
| 刷新后事件不更新 | SSE 自动重连 + 轮询兜底 |
| 刷新后路径失效 | 服务端持久化路径 + localStorage |

## 功能特性

- **FSEvents 主引擎**（v8 重写）
  - 基于 macOS FSEvents API，与 Finder/Spotlight 同级，CPU < 2%
  - `lsof` 异步补查进程名，准确率约 85%
  - 路径特征规则兜底（.DS_Store → Finder、.git/ → git 等）
- **AI 事件分析**
  - 支持接入任意 OpenAI 兼容接口（Deepseek / 阿里通义 / Kimi / 灵芽 / n1n / OpenAI 等）
  - 本地离线规则引擎，无需 Key 即可使用
- **智能重命名识别**：区分真正的重命名 vs 移入废纸篓
- **实时推送**：SSE 毫秒级延迟，断线自动重连，轮询兜底不丢事件
- **前端筛选**：路径关键字、进程名、事件类型多维过滤
- **自定义监控路径**：支持任意目录，持久化到 localStorage
- **数据导出**：一键导出 JSON

## 目录结构

```
file_monitor_v8/
├── app.py              # 主程序（Flask + watchdog FSEvents + lsof + AI 分析）
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
cd /path/to/file_monitor_v8
chmod +x setup.sh
./setup.sh
```

setup.sh 自动完成：
- 检查 macOS 环境和 Python 3
- 创建 Python 虚拟环境
- 安装 `flask`、`watchdog` 依赖

> v8 不再需要配置 sudo 免密权限。

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
| 权限 | 普通用户权限即可（无需 sudo） |

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

直接点击事件上的「📖 离线分析」，覆盖：
- 12 种操作类型解释
- 14 种常见进程识别（mdworker / Finder / backupd / Python / Claude 等）
- 路径特征识别（.DS_Store / .Trash / tmp / node_modules 等）
- 敏感路径风险提示（/etc / SSH 密钥 / keychain 等）

## 事件类型说明

| 事件 | 中文 | 触发场景 |
|------|------|---------|
| `create` | 新建文件 | 新建文件 |
| `mkdir` | 新建目录 | 新建文件夹 |
| `modify` | 写入 | 文件内容修改、保存 |
| `delete` | 删除文件 | 任意方式删除文件 |
| `rmdir` | 删除目录 | 删除文件夹 |
| `move` | 重命名/移动 | Finder 重命名，显示新文件名 |
| `trash` | 删除(废纸篓) | Finder 移入废纸篓 |

## 技术说明

### v8 新架构

```
watchdog FSEvents（主引擎，零 sudo）
    │
    ├─ on_created  → lsof 异步补查进程名 → 事件入库
    ├─ on_modified → lsof 异步补查进程名 → 事件入库
    ├─ on_deleted  → lsof 异步补查进程名 → 事件入库
    └─ on_moved    → 延迟 300ms 判断重命名/废纸篓 → 事件入库
                                    ↓
                              SSE → 浏览器
```

### 与 v7.x 的资源对比

| 指标 | v7.x（fs_usage） | v8（FSEvents） |
|------|----------------|----------------|
| CPU（活跃监控） | 40~75% | **0.0%**（实测噪声底线） |
| 内存占用 | ~15 MB | **7~18 MB** |
| 线程数 | 较多 | **12**（watchdog + lsof 池 + Flask） |
| 需要 sudo | 是 | 否 |
| ktrace 独占锁 | 是（偶发冲突） | 否 |
| 进程名准确率 | ~95% | ~85% |

> 实测环境：macOS，持续监控期间触发写入/删除事件，1 秒采样间隔，CPU 始终显示 0.0%。lsof 子进程调用速度足够快，不在采样窗口内体现。

### lsof 进程补查

每个文件系统事件触发后，在线程池（max_workers=8）中异步执行 `lsof -F cn -- <path>`，查询当前持有该文件的进程名。lsof 超时设为 1.5s，不阻塞事件流。

进程已关闭文件时 lsof 查不到（时序盲区），此时回退到路径特征规则推断（如 `.DS_Store` → Finder、`.git/` → git）。

### 废纸篓检测

Finder 移入废纸篓的底层是 `rename(src → ~/.Trash/filename)`，watchdog 触发 `on_moved` 事件。程序延迟 300ms 后检测源文件是否消失、`~/.Trash/` 下是否出现同名文件。

### SSE 可靠性

- SSE 断线后 3s 自动重连
- 4s 轮询兜底：定期拉取 `/api/events` 按 id 去重补全
- 页面刷新时从 `/api/status` 恢复最近 200 条历史事件

### 端口

默认 **5006**，可在 `app.py` 末尾修改。

## 彻底删除

```bash
./uninstall.sh
```

## 常见问题

**Q: 启动后没有任何事件？**  
A: 确保已选择监控路径并点击「开始监控」。v8 不再需要 sudo，直接启动即可。

**Q: 进程名显示 unknown？**  
A: lsof 有时序限制，进程写完立即关闭文件时查不到。可点击「📖 离线分析」，规则引擎会根据路径特征推断进程。

**Q: AI 分析提示连接失败？**  
A: 检查接口地址是否完整（需含 `/v1/chat/completions`），Key 是否正确。不想配置 AI 可直接用「📖 离线分析」。

**Q: 刷新页面后事件还在吗？**  
A: 在。页面刷新后自动从服务端拉取最近 200 条历史事件，Flask 进程不重启数据不丢失。

**Q: 和 v7.x 相比少了哪些事件类型？**  
A: v8 不再区分 `write`/`wrdata`/`pwrite` 等写入子类型，统一为 `modify`。其他事件类型覆盖不变。如需细粒度 syscall 级别追踪，可继续使用 v7.3。

**Q: 端口被占用？**  
A: `lsof -ti:5006 | xargs kill -9`，或修改 `app.py` 末尾端口号。
