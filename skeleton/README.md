# 当前交付：图片与视频双流程（新增功能开发中）

本轮在原图片页外保留双tab共用壳，并加入千问AI `wan3.0-video-prime` 真实关键帧到视频流程。启动方式不变。最新范围和验证证据见 `../delivery/PRD.md`、`../delivery/评测报告.md`。以下旧骨架介绍仅保留作背景，不代表本轮要做原生应用或本地模型。

视频配置见 `.env.example`：密钥只放根目录 `demo-api.env`。真实流程支持角色参考、分镜节点画布、前镜头末帧衔接、每段5秒/480P生成及本地合并成片；已有14.9秒真实成片证据。前端保留明确区分的真实模型与本地原型入口。新增“只写本次修改”、要求继承及关键帧确认已经过功能检查，尚未重新进行付费模型效果验证。整剧质量仍待验收，本包不是正式上线版本。

任务保存至 `data/video/`，关键帧至 `data/video_frames/`，画布至 `data/video_board/`，参考图至 `data/video_assets/`，成片至 `data/video_merges/`。交付包提供源码、测试、文档和精选验证证据，不包含本机运行数据、密钥或虚拟环境。解压后配置自己的服务凭据，并按下文启动。

# 端侧AIStudio 后端骨架（skeleton/）

> 按 `../方案.md` 生成的可独立运行后端骨架。正式产品为原生 macOS 桌面画布应用
> （Swift/SwiftUI）作为前端，本包作为「本地推理与图像处理管线」Python 后端，
> 通过本地 HTTP 接口通信。骨架阶段以 FastAPI 服务承载后端能力。

## 最小商品生图 demo（当前重点）

单页 Web demo：上传商品参考图 → 写创作意图 → 选场景预设 → 生成 4 张场景图 →
放大对比 → 选一张导出 / 打包 zip。参考图**真正参与生成**（图生图，非纯文生图）。

一条命令启动（自动建 venv、装依赖、加载 `../demo-api.env`）：

```bash
./scripts/dev.sh serve
```

然后浏览器打开 **http://127.0.0.1:8765** 即可使用。

接口（异步任务模型）：
- `GET /api/demo/presets` —— 场景预设列表（6 个，带缩略图与 prompt 片段）
- `POST /api/demo/generate` —— `images`(1–5 张) + `primary_index` + `prompt` + `scene` + `count`(1/2/4/8) + `lock_product` + `negative_prompt` + `size` + `sku` + `seed_base`，返回 `job_id` + 每张质检 `qa`
- `GET /api/demo/jobs/{job_id}` —— 轮询状态/进度（每张图完成即返回）
- `POST /api/demo/jobs/{job_id}/cancel` —— 取消（保留已完成图）
- `POST /api/demo/jobs/{job_id}/retry` —— 重试/重绘（`indices` + `seed_mode`=new/same）
- `GET /api/demo/export?session_id=job_id` —— 全部成功图 + `manifest.json` + `manifest.csv` 打包 zip（命名 `{SKU}_{场景}_{序号}_{宽}x{高}.{ext}`）

生图：demo 期走豆包 Seedream flash 图生图（并行，支持 `size`/`strength` 参考强度）；
模型当前仅支持 1:1 方图（1024/1536/2048），其余比例前端置灰说明原因。
失败不静默回退：每张图独立 success/failed，失败可单张重试；未配 key 才走本地抠图+合成。
前端支持：参考图对照、锁定商品、SKU、尺寸/比例/分辨率、数量 1/2/4/8、prompt 预览/高级编辑、
生成进度条、取消、失败重试、Lightbox 放大/缩放/原图对比、单张导出、打包 zip。

## 运行

```bash
cd skeleton
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 离线跑通电商闭环（stub provider，无需任何密钥）
.venv/bin/python -m aiside demo

# 启动本地 HTTP 服务（默认 127.0.0.1:8765）
.venv/bin/python -m aiside serve
```

一条命令版（自动建 venv、装依赖、加载 demo-api.env）：

```bash
./scripts/dev.sh demo      # 离线闭环
./scripts/dev.sh serve     # HTTP 服务
```

## demo 期生图（豆包 Seedream）

- 真实 key 在本目录的上一级 `../demo-api.env`（即项目根目录的 `demo-api.env`），
  **不入库、不进 git、不进日志、不进 PRD、不写进代码**。
- `scripts/dev.sh` 启动时自动 `source ../demo-api.env`；也可手动 `export` 环境变量。
- 未提供 key 时自动回退 `stub` 离线 provider，全链路仍可跑通。
- 网络出口白名单默认只放行 `DEMO_BASE_URL` 域名，其余出网请求一律拒绝（默认不出网红线）。
- 正式版切本地推理（Apple MLX/Core ML），Seedream provider 仅为原型验证链路。

## 理解层 LLM（可选，S2 Agent Loop 用）

Agent Loop（`aiside/loop.py`）需要一个 OpenAI 兼容的 LLM 端点，正式版指向本地 Qwen3。
不配则 `/projects/{pid}/agent` 返回 501，demo 仍可用确定性 `pipeline.py` 跑通。

```bash
export LLM_BASE_URL=http://127.0.0.1:11434/v1   # Ollama / LM Studio / MLX server
# export LLM_API_KEY=ollama
export LLM_MODEL=qwen3:8b
```

## 目录结构

```
skeleton/
├── aiside/                 # 后端包
│   ├── main.py             # FastAPI 入口
│   ├── api.py              # REST 路由
│   ├── workspace.py        # 聚合：项目/调度/权限/观测
│   ├── dispatch.py         # 工具分发（loop + hooks + 权限 + 重试）
│   ├── pipeline.py         # 确定性电商闭环 demo
│   ├── prompt.py           # 系统提示词草案
│   ├── core/               # 项目图(DAG)、资产库、journal、调度、审计
│   ├── tools/              # 8 个领域工具
│   ├── providers/          # stub / seedream 双 provider
│   ├── permissions/        # 默认拒绝 + ask 确认
│   ├── hooks/              # Pre/PostToolUse + 网络出口审计
│   └── observability/      # 指标
├── config/                 # 渠道规格/质检阈值/命名/模型注册表/调度降级（可编辑）
├── tests/                  # 核心循环、权限边界、降级链、provider 单测
├── scripts/dev.sh          # 一条命令启动
├── requirements.txt
├── .env.example
└── .gitignore
```

## 组件选型映射（对应 方案.md Step 3）

| 引擎组件 | 骨架落地 |
|---|---|
| s01 Agent Loop | `loop.py`（OpenAI 兼容 LLM 循环）+ `dispatch.py` 分派；未配 LLM 时用确定性 `pipeline.py` |
| s02 工具系统 | `tools/registry.py` + 8 个工具 |
| s03 权限系统 | `permissions/policy.py`（默认拒绝上传、ask 确认、审计） |
| s04 钩子系统 | `hooks/manager.py`（Pre/PostToolUse + 网络出口审计） |
| s05 任务规划 | `plan.py` TodoList + `pipeline.py` 确定性计划 |
| s10 任务系统 | `core/project_graph.py` + `core/job_journal.py`（checkpoint/续跑） |
| s11 后台任务 | `core/scheduler.py`（单执行道 + 优先级队列 + step 边界抢占） |
| s15 集成 Harness | `workspace.py` + `dispatch.py` 归一到单一循环 |

## 8 个领域工具

`ingest_and_qa_photos`、`build_consistency_anchor`、`generate_image`、
`score_fidelity_and_batch_qa`、`postprocess_and_package`、`project_graph_edit`、
`asset_store`、`model_manager`。完整 schema 见 `GET /tools`。

## 红线落地

1. **默认不出网**：网络出口白名单，仅放行 demo 生图 API 域名；其余 deny + 审计。
2. **无云端兜底**：provider 抽象，正式版只写本地推理；demo 走 Seedream 仅原型。
3. **不静默失败**：生成失败自动重试 1 次，仍失败按降级链（降分辨率→降步数→换轻量模型）
   逐级尝试并标 `degraded`；导出/破坏性操作需确认，未确认不落盘。

## 已确认决策（2026-10-22，见 PRD 第 6 节）

- **原型前端**：demo 期 Web 原型；量产换原生 macOS 壳。
- **前后端通信**：本地 HTTP（127.0.0.1:8765），后端作为本地子进程起 FastAPI 服务。
- **渠道规格**：`config/channels.yaml` 已回填抖音真实规格（商品主图 1000×1000 / 场景主图 1000×1000 / 详情页 750×1000×3–5 屏 / 商品卡 800×800）；其余 4 平台暂缓。
- **本地模型**：MVP 生图走 Seedream demo；FLUX/Qwen-Image 本地推理放 S2 硬化阶段再接。

## ⚠️ 仍为占位 / 待实测（不阻塞 demo 链路）

- **质检/一致性阈值**：`config/qa_thresholds.yaml` 为占位值，真实模型接入后实测。
- **本地模型推理**：`StubProvider` 占位；FLUX/Qwen-Image 的 MLX/Core ML 接入待硬化。
- **模型下载/热切换**：`model_manager` 仅实现注册表查询与校验占位，真实下载待硬化。

## 测试

```bash
.venv/bin/python -m pytest -q
```

覆盖：项目图增量重算、资产去重、调度优先级/取消、权限边界（网络 deny、导出 ask、
破坏性 ask、审计留痕）、工具链路、provider stub/seedream 解析、电商闭环端到端。

## API 速览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 + 当前 provider |
| GET | `/tools` | 工具清单（schema/权限/副作用） |
| GET | `/metrics` | 指标快照（对齐 PRD 成功指标） |
| POST | `/projects` | 新建项目 |
| GET | `/projects/{pid}` | 项目图（DAG） |
| POST | `/projects/{pid}/jobs` | 提交异步任务（走队列） |
| POST | `/projects/{pid}/tools/{tool}` | 同步调用工具 |
| GET | `/projects/{pid}/jobs/{jid}` | 任务状态 |
| POST | `/jobs/{jid}/confirm` | 用户确认（ask 类操作） |
| POST | `/projects/{pid}/agent` | Agent Loop（s01，需本地 LLM） |
| GET | `/projects/{pid}/jobs/incomplete` | 扫描本项目未完成任务 |
| POST | `/projects/{pid}/jobs/{jid}/resume` | 从 checkpoint 续跑任务 |
| GET | `/recovery/incomplete` | 启动恢复扫描（全部项目） |
| GET | `/projects/{pid}/assets/{cid}` | 取资产字节 |

## 2026-10-23 稳定性更新

- 历史入口：`GET /api/demo/jobs` 返回最近 100 次任务；页面刷新自动恢复最近查看的任务。
- 新任务保存 `reference.bin` 和逐张更新的 manifest。重启后可查看、导出、重绘；中断任务不会自动重新调用模型，用户可手动重试。旧版本未保存参考图的任务仅可查看、导出。
- `POST /api/demo/jobs/{id}/retry` 现在立即返回，前端继续轮询；相同任务运行中再次重绘返回 409。新 seed 每次递增分配；同 seed 不保证云端模型像素级一致。
- 任务状态增加 `canceling`、`interrupted`。每任务最多 2 张同时生成；取消停止尚未开始的图片，等待已发出的请求返回并保留成功图片，最终标为 `canceled`。
- 多图上传是候选参考图选择，本次实际只发送主参考图。界面已明确说明，尚未实现多参考共同约束。
- ZIP 仅包含当前成功图和两个 manifest，不包含主参考图；下载名称使用生成时保存的文件名。
- “保持商品外观”通过提示词控制，不是蒙版锁定；必须人工检查商品形状、文字和材质。
- 测试：51 项通过。浏览器验收使用隔离模拟 provider，不代表真实 API 出图质量已通过；R12 和 10 商品内测仍待完成。

## 双线演示版（2026-10-23）

当前入口为一个工作区中的「电商图片」「短剧视频」两个 tab，项目名称、素材区、底部任务队列与导出区共用。图片页保留原实现；视频页是**原型 / 验证中**，仅使用本地预置关键帧和 MP4，所有生成按钮走模拟进度，未接入真实视频模型。

- 视频：分镜编辑 → 生成示例关键帧 → 勾选镜头 → 生成示例视频（模拟） → 播放 → 底部导出 MP4 / 演示 ZIP。
- `POST /api/demo/video/export` 打包所选镜头、示例关键帧、分镜记录与原型说明。
- 切换 tab 不重建 DOM；图片后台任务照常进行，视频的模拟任务也不因切换中断。
- 单项目名称与视频分镜保存在当前浏览器；上传候选文件在刷新后需重选，历史图片通过后端恢复。
- 本地示例已随源码提供；运行演示不需要 FFmpeg。仅重新制作示例时，额外安装 `imageio-ffmpeg` 并运行 `scripts/build_prototype_media.py`（脚本字体路径适配 macOS）。
- 自动测试：54 项通过；隔离前端故障测试服务：`PYTHONPATH=. .venv/bin/python tests/ui_fixture_server.py`，监听8876，不改生产服务的provider或数据。
- 本轮不新增 Agent、DeepSeek、本地模型、多 SKU、队列抢占。
- 文档与截图：项目根目录 `delivery/`。包含一页PRD、MVP矩阵、两章评测报告、评分草案及执行步骤。图片质量待人工评分，视频真实能力待验证。
