# DuckPet 插件化宠物机器鸭

一只性格**调皮、听话、忠诚**的开源宠物鸭。核心设计思想：**每个功能都是一个插件，直接复用市面上最优秀的开源项目；别人更新了，鸭子就升级**。

- 本体适配：**默认 microduck 成品鸭**（[pollen-robotics/microduck](https://github.com/pollen-robotics/microduck)，自带踢球/喙叼/行走策略），也支持树莓派 DIY 的 [Open Duck Mini](https://github.com/apirrone/Open_Duck_Mini)，还可纯电脑仿真开发
- 大脑纯 Python 零依赖：优先级仲裁、行为状态机、性格引擎，不装任何第三方库就能跑仿真
- 感知/动作全部插件化：唤醒词、声纹、ASR、人脸、跟随、物体检测、TTS 都可替换

## 快速开始（无需任何硬件和依赖）

```bash
python3 -m duckpet.sim --demo     # 3 分钟演示：9 项功能全场景
python3 -m duckpet.sim            # 交互模式，输入 help 查看指令
```

交互模式里你可以直接"扮演"任何人：

```
仿真> enroll 爸爸 主人
仿真> call 爸爸 30              # 爸爸在 30° 方向喊鸭子名字
仿真> say 爸爸 跟着我            # 爸爸下达跟随指令
仿真> call 陌生人 -60            # 跟随中陌生人呼叫 -> 只礼貌转头回应
仿真> obj sports_ball 10 0.5     # 让鸭子"看到"球
仿真> say 陌生人 丫丫，踢球！
```

## 获取代码与仿真依赖

```bash
# 1. 克隆（microduck_rl 是 submodule：官方物理仿真 + 训练栈，跟随上游升级）
git clone --recurse-submodules https://github.com/a125477365/DuckPet
cd DuckPet
# 已经 clone 了的话：git submodule update --init

# 2. 仿真运行环境（仅 3D 物理仿真需要；大脑逻辑仿真零依赖）
cd third_party/microduck_rl
uv venv .venv-sim --python 3.12
uv pip install --python .venv-sim/bin/python \
  mujoco glfw numpy onnxruntime pyopengl better-actuator-models
# macOS 直播弹幕桥另需：pyobjc-framework-Vision pyobjc-framework-Quartz pyobjc-framework-Cocoa
cd ../..
```

Windows 用户：上面第 2 步不用手动做——首次运行 `tools\sim_duckpet_3d.bat`
或 `tools\live_danmaku_sim.bat` 会自动建 venv 并装齐依赖（包括弹幕桥用的
mss/pywin32/rapidocr_onnxruntime），只需先装好 [uv](https://docs.astral.sh/uv/)。

**全部动作策略模型（官方 7 个 + 社区加强 2 个，共 ~7MB）已随仓库自带在
`policies/` 目录**（走路/站立/坐卧/喙叼/左右踢球/前滚翻×2/粗糙地形行走，
来源与 License 见 `policies/README.md`），clone 即完整，无需再下载。

升级官方仿真/策略到最新版：

```bash
git submodule update --remote third_party/microduck_rl   # 拉上游最新仿真/训练代码
# 策略有新版时重下覆盖 policies/ 即可即插即用：
huggingface-cli download pollen-robotics/microduck-policies --include "*.onnx" \
  --local-dir policies/
```

## 9 项功能与开源组件映射

| # | 功能 | 实现 | 上游开源组件 | 状态 |
|---|---|---|---|---|
| 1 | 声纹认主人 | `perception/audio.py` + `core/registry.py` | sherpa-onnx + 3D-Speaker CAM++（中文声纹） | ✅ |
| 2 | 声音/界面设置家人朋友客人 | `core/brain.py`（语音"记住我"）+ `tools/enroll.py`（界面 CLI） | 同上 + InsightFace 人脸 | ✅ |
| 3 | 设置鸭子姓名 | 语音"你以后叫XX"，唤醒词热更新 | sherpa-onnx KWS（免训练自定义唤醒词） | ✅ |
| 4 | 呼叫 + 优先级仲裁 | `core/arbiter.py` + `core/brain.py` | DOA：pyroomacoustics / ODAS | ✅ |
| 5 | 跟随（仅主人/家人） | `core/behaviors.py: FollowBehavior` | YOLO + BoTSORT + OSNet ReID | ✅ |
| 6 | 空闲乱逛/避险/调皮 | `WanderBehavior` + `TeaseBehavior` + `SafetyEye` | VL53L0X 防跌 + OpenCV 光流 | ✅ |
| 7 | 踢球 | `KickBallBehavior` | 球检测：YOLO(COCO)；踢球动作策略：microduck_rl 官方 `ball_kick_left/right`（仿真实测把球踢飞 7m+） | ✅ |
| 8 | 叼/搬东西 | `CarryBehavior` | 开放词汇检测：YOLO-World；喙叼策略：microduck_rl 官方 `alpha_ground_pick` | ✅ |
| 9 | 调皮忠诚治愈性格 | `core/personality.py`（拓麻歌子式情绪引擎） | 自建（参考 Reachy Mini / 小智表情设计） | ✅ |
| 10 | 跳舞（直播彩蛋，任何人可点） | `core/behaviors.py: DanceBehavior` | 自建摇摆舞动作编排（满量程扭身+前后蹦+甩头+转圈谢幕） | ✅ |
| 11 | 前滚翻 | `core/behaviors.py: TrickBehavior` | 社区 `langli11/microduck-tricks` 的 roulade_elan（Apache-2.0，比官方版成功率高） | ✅ |
| 12 | 坐下/站起 | `SitBehavior` + 官方 `alpha_sitstand` | 官方策略（posture flag 双向切换） | ✅ |
| 13 | 后滚翻/原地跳/躺下 | 语音指令已留（会礼貌说"还没学会"） | 社区有训练代码未发布权重（Lulzx/microduck-backflip、microduck-jump），发布即接入 | ⏳ |
| 14 | 上下台阶（跟随时） | 行走策略热切换 | 社区 `RemiFabre/microduck-rough-walk-g`（Apache-2.0）：2cm 台阶/9° 斜坡/碎石；`[sim] walking_policy` 一键切换；下 ≥2cm 台阶会摔，真楼梯待社区 | ✅ 可选 |

完整组件清单、License、备选方案见 [PLUGINS.md](PLUGINS.md)。

## 架构

```
喊"丫丫！"          说话声
   │                  │
   ▼                  ▼
┌─────────────────────────────────────┐
│ 感知层（可插拔）                       │
│  sherpa-onnx: 唤醒词→中文ASR→CAM++声纹 │
│  DOA: pyroomacoustics/ODAS 声源方位角  │
│  视觉: InsightFace 人脸 / YOLO 跟踪检测 │
└──────────────┬──────────────────────┘
               ▼  CallEvent / SpeechEvent / PerceptEvent
┌──────────────────────────────────────┐
│ 大脑 duckpet/core/brain.py            │
│  仲裁器：主人>家人>客人朋友>陌生人       │
│   · 更高级别呼叫 -> 放下手头工作去找TA   │
│   · 同级/更低 -> 转头礼貌回应+继续干活   │
│   · 更低级别指令 -> 排队，忙完再执行     │
│  状态机：乱逛/找人/跟随/踢球/叼物/调皮   │
│  性格：开心度/精力/亲密度衰减+互动反馈   │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│ 硬件抽象 duckpet/hardware/            │
│  mock（仿真）| openduck | microduck   │
└──────────────────────────────────────┘
```

## 仿真测试（三层，从逻辑到物理）

```bash
# 第 1 层：大脑逻辑仿真（零依赖，本项目自带）
python3 -m duckpet.sim --demo      # 预置场景：9 项功能自动过一遍
python3 -m duckpet.sim             # 交互模式：你扮演不同角色喊它、下指令

# 第 2 层：3D 物理仿真里的自主鸭（DuckPet 大脑 × microduck 官方 MuJoCo 物理）
bash tools/sim_duckpet_3d.sh       # 3D 窗口 + 终端文字指令：鸭子自主乱逛/听声
                                   # 找人/按优先级仲裁/真的去踢场景里的物理球
bash tools/sim_duckpet_3d.sh --headless   # 无窗口自动验证：乱逛/转身/踢球/跟随全 PASS

# 场景里可以放人（有位置、身高、体型、朝向，会走动）：
#   enroll 爸爸 主人 1.8            # 登记的人会出现在场景里（绿=主人 蓝=家人 橙=客人 灰=陌生人）
#   spawn 路人甲 -1.5 -1.2 1.72     # 放一个未登记的路人（陌生人）
#   call 爸爸                       # 方向按站位几何自动计算，身份走声纹识别管线
#   say 爸爸 跟着我                 # 跟随中鸭子靠视觉方位跟踪，靠近 0.55m 自动停
#   pace 爸爸 0.5                   # 爸爸绕圈走，看鸭子持续跟随
#   move 爸爸 2 1 / stay 爸爸       # 挪动 / 停下
```

**仿真里的"认人"与真机管线同构**：`enroll` 时合成声纹/人脸 embedding 入库
（真机由 `tools/enroll.py` 录真声纹/真人脸）；呼叫时方向由站位几何计算、
身份走 `match_voice` 声纹匹配；看见人时先判视野（身体 ±100°）再认人——
正脸且 ≤2m 走人脸匹配，看不清脸就用**身高+体型**粗筛（档案里唯一匹配才算认出，
否则当陌生人）。所以你可以测试"没登记的人叫我""两个身高一样的人站在一起"
这类真实场景。

**3D 窗口操作**：相机默认**跟随鸭子**（输入 `cam` 回车可关）；滚轮=缩放画面，
左键拖动=旋转，右键拖动=平移。鸭子空闲乱逛限制在以"进入空闲模式时的位置"为圆心的
`wander_radius_m`（默认 5 米 = 方圆 10 米，`configs/duckpet.toml` 可改）内；
如果鸭子被抱走/在窗口里被拖走（Ctrl+左键可以拖动鸭子），位置跳变会被识别为
"被搬家了"，自动以新地方为圆心，**不会试图走回老窝**（真鸭子也不知道自己被搬了多远）。
另外官方走路策略几乎不会原地转，所以鸭子的转身都是
**划弧转**（边走边转，像真鸭子）——这是硬件适配层自动加的坡行速度。

# 第 2 层补充：键盘遥控版官方仿真（策略调试用，鸭子不自主）
bash tools/sim_microduck.sh        # WASD 走路，K/L 踢球，G 喙叼，R 前滚翻

# 第 3 层：自训策略验证（见 docs/TRAINING.md 第 5 步）
cd third_party/microduck_rl && uv run scripts/infer_policy.py --walking <你的.onnx>
```

> macOS 说明：3D 窗口走 mjpython 跳板（不装 Xcode 也能用，启动脚本已自动
> 处理 `PYGLFW_LIBRARY` 与跳板 argv 约定；若手动杀仿真进程用
> `pkill -f sim_duckpet_3d` 即可）。

备选平台 Open Duck Mini 的官方仿真器是
[Open_Duck_Playground](https://github.com/apirrone/Open_Duck_Playground)：
`uv run playground/open_duck_mini_v2/mujoco_infer.py -o BEST_WALK_ONNX_2.onnx`。

## 直播/弹幕接入（鸭子自己判断要不要执行）

仿真器启动后就是常驻 REPL，**每行一条**输入。除了 `say/call` 调试指令，
还支持自然聊天格式——这正好是弹幕的格式：

```
主人：请跟我。          # 角色别名自动指向已登记的主人
爸爸：丫丫，踢球！
路人丙：跳个舞          # 未注册的观众自动按陌生人处理
```

所以直播接入 = 把你的弹幕监听程序的输出**管道**进来即可：

```bash
python3 你的弹幕监听.py | bash tools/sim_duckpet_3d.sh
# 弹幕监听程序每收到一条评论就打印一行：用户名：内容
```

每条弹幕走完整的真实管线：身份识别（观众未登记=陌生人）→ 意图解析 →
优先级仲裁 → 行为执行。观众（陌生人）可以点踢球/叼东西/唱歌/**跳舞**，
但跟随等特权指令会被礼貌拒绝；主人/家人在弹幕里发话会自动抢占观众的任务。
`跳舞`就是为直播准备的：鸭子会扭身子、踩小碎步、摇头晃脑 5 秒。

### 直播伴侣评论区自动监听（macOS / Windows）

不用自己写弹幕监听程序也行——`tools/live_danmaku_sim.sh`（Windows 用
`tools/live_danmaku_sim.bat`）一键完成：
**自动打开直播伴侣 + 自动打开 3D 仿真 + 持续 OCR 评论区、把像指令的弹幕喂给鸭子**。

```bash
bash tools/live_danmaku_sim.sh        # 启动（只转发像指令的弹幕）
bash tools/live_danmaku_sim.sh --all  # 弹幕全部转发给鸭子判断
```

- 架构：弹幕桥 `tools/live_companion_danmaku.py` 作为**仿真内线程**运行
  （`--danmaku`），和终端键盘输入共用一条队列——**弹幕和你手打的指令同时生效**。
  每 2 秒截取直播伴侣窗口的评论区（右侧「互动消息」面板，已按 1280x720 实测校准），
  OCR 识别新评论，去重后以「昵称：内容」格式进仿真——和手打弹幕完全同一条路。
- **macOS**：窗口/截图用 Quartz（窗口被挡住也能截），OCR 用原生 Vision（中文）。
  首次运行会弹「屏幕录制」权限请求，给终端 App 勾选
  （系统设置 → 隐私与安全性 → 屏幕录制）。
- **Windows**：窗口查找用 pywin32，截图用 mss（**直播伴侣窗口请勿最小化/遮挡**），
  OCR 用 rapidocr_onnxruntime（自带中文模型，纯 pip 安装）。
  `.bat` 启动器会自动装齐这些依赖。
- 过滤规则：默认只转发「喊鸭子名字」或「含指令词（踢球/跳舞/跟我/捡/搬…）」的弹幕，
  过滤诊断打在终端里（stderr），不会混进鸭子的输入。
- 窗口布局不同（分辨率/面板拖拽过）时重新校准评论区位置：
  `python3 tools/live_companion_danmaku.py --dump` 会打印窗口里每行文字的
  相对坐标，然后 `bash tools/live_danmaku_sim.sh --region x,y,w,h` 即可。
- 自定义弹幕源（如 B 站/YouTube 弹幕 API 抓取的评论）同样适用：
  只要你的程序把评论按「用户名：内容」逐行打印，管道进仿真 stdin 即可
  （`你的弹幕程序 | bash tools/sim_duckpet_3d.sh`，stdin 通道一直保留）。

## 真机部署

### microduck 成品鸭（默认平台）

固件自带 `walk / kick_left / kick_right / ground_pick` 等策略（踢球、喙叼现成可用）。
`configs/duckpet.toml` 里 `hardware = "microduck"`（已是默认），
适配器通过 `robotctl` 驱动，新技能用 `sudo robotctl policy add <名字> <HF仓库>` 热插拔。

```bash
# 在鸭子上（或能 ssh 到鸭子的机器上）：
pip install -e '.[audio,vision,tts]'
python3 tools/download_models.py
python3 tools/enroll.py --name 爸爸 --role 主人 --voice 爸爸.wav --face 爸爸.jpg
python3 -m duckpet.main
```

### Open Duck Mini（树莓派 DIY 备选）

```bash
# 在鸭子上：安装行走运行时
git clone https://github.com/apirrone/Open_Duck_Mini_Runtime && cd Open_Duck_Mini_Runtime
git checkout v2 && pip install -e .

# 安装 DuckPet 及语音/视觉插件
pip install -e '.[audio,vision,tts,hw]'
python3 tools/download_models.py          # 下载 KWS/ASR/声纹/TTS 模型
python3 tools/enroll.py --name 爸爸 --role 主人 --voice 爸爸.wav --face 爸爸.jpg

# configs/duckpet.toml 里 hardware = "openduck"，然后：
python3 -m duckpet.main
```

## 持续集成上游更新（本项目核心机制）

```bash
python3 tools/update_plugins.py           # 检查所有上游组件有无新版本
python3 tools/update_plugins.py --apply   # 把最新版本写回 plugins.toml
export GITHUB_TOKEN=xxx                   # 可选，避免 GitHub 限流
```

换成更好的组件：改 `configs/duckpet.toml` 的 `[adapters]` 一行即可；
全新的组件：在 `configs/plugins.toml` 登记上游仓库 + 在 `duckpet/plugins/registry.py` 注册适配器。

## 已知待补（社区还没有现成开源方案的部分）

- **Open Duck Mini 的踢球/喙叼动作策略**：训练方法见 [docs/TRAINING.md](docs/TRAINING.md)，
  训出的 ONNX 放进 `policies/` 即可被 `hardware/openduck.py` 加载（代码里已留 TODO 接口）
- **LLM 兜底解析**：规则解析覆盖高频指令；复杂指令可在配置里开 `llm.enabled` 用本地 Qwen2.5-1.5B
- **治愈系情绪识别**（识别主人情绪低落主动安慰）：声纹侧可用 SenseVoice 情感识别，尚未接入，留了 `PerceptEvent` 扩展口

## License

AGPL-3.0（见 LICENSE 文件）。选型理由：本项目以"库调用"方式集成了 AGPL-3.0 组件
（ultralytics、boxmot）与 GPL-3.0 组件（piper、YOLO-World、edge-tts），
按 copyleft 传染性规则，整体以 AGPL-3.0 发布可同时兼容 GPL 系组件
（GPL-3.0 第 13 条明确允许与 AGPL-3.0 合并）。
你拿去改、再发布到 GitHub 完全没问题，只需同样开源并保留 AGPL-3.0。

另外两个注意项：
- **InsightFace 模型权重仅授权非商业用途**（代码 MIT）——个人项目随便玩，
  未来要卖整机的话需向 insightface.ai 购授权，或换 Hailo Model Zoo 的 arcface 模型。
- **Open_Duck_Mini_Runtime / Open_Duck_Playground 仓库未声明 License**，
  我们是"调用"而非复制其代码，发布 DuckPet 不受影响；若想把它的代码抄进来，请先向作者确认。

如果你坚持想用宽松协议（Apache-2.0）发布：把检测/跟踪换成 MIT/Apache 系
（如 PaddleDetection RT-DETR、NanoDet），TTS 换成自训或 MIT 引擎，
人脸换 Hailo 模型，并在 `configs/duckpet.toml` 改对应 `[adapters]` 即可，
架构上就是为这种替换设计的。
