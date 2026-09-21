# DuckPet 插件手册

机器可读注册表在 [`configs/plugins.toml`](configs/plugins.toml)，
用 `python3 tools/update_plugins.py` 检查上游更新。
本文件说明每个能力的选型理由、备选与集成方式。

## 语音管线

### 首选：sherpa-onnx 一体化（Apache-2.0）

一个框架覆盖三个能力，全部有树莓派实测，模型 int8 小体积：

| 能力 | 模型 | 说明 |
|---|---|---|
| 唤醒词 | `sherpa-onnx-kws-zipformer-wenetspeech-3.3M` | **免训练自定义**：把鸭子名字按字写进 `keywords.txt` 即可 |
| 中文 ASR | `streaming-zipformer-small-bilingual-zh-en` | 流式中英双语 |
| 声纹 | `3dspeaker_speech_campplus_sv_zh-cn_16k` | 中文说话人 20 万数据，阈值 0.5 |

适配器：`duckpet/perception/audio.py: SherpaAudioPipeline`（喊名字 → CallEvent；指令 → SpeechEvent，自动带声纹身份）。

### 备选

- 唤醒词：[openWakeWord](https://github.com/dscripka/openWakeWord)（Apache-2.0，需 Colab 训练自定义词）
- ASR：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)（MIT，非流式）
- 声纹：[SpeechBrain ECAPA-TDNN](https://github.com/speechbrain/speechbrain)（Apache-2.0，PyTorch 较重）
- ❌ Mycroft Precise / Resemblyzer：均已停更，不推荐

### 声源定位（DOA）

- 首选：`pyroomacoustics` SRP-PHAT + ReSpeaker 4-Mic 阵列 → 方位角，用于"转头/转身找呼叫者"
- 高性能：[ODAS](https://github.com/introlab/odas)（MIT，C 实现，socket JSON 接入 `OdasDirectionFinder`）

### TTS

- 首选：piper 中文音色 `zh_CN-huayan-medium`（注意：piper 已迁仓 OHF-Voice/piper1-gpl，协议 GPL-3.0）
- 联网高音质：edge-tts（GPL-3.0，离线不可用）

## 视觉

| 能力 | 组件 | License | 说明 |
|---|---|---|---|
| 人脸识别 | InsightFace `buffalo_sc` | 代码 MIT / **权重仅非商业** | SCRFD 检测 + MobileFaceNet 识别，CPU 数 FPS |
| 人体跟踪跟随 | Ultralytics YOLO11n + boxmot BoTSORT + OSNet | AGPL-3.0 | NCNN 格式 Pi5 约 15FPS；ReID 用于跟丢后找回主人 |
| 球检测 | YOLO COCO `sports ball`(class 32) | AGPL-3.0 | 建议自采数据微调 |
| 开放物体（抹布等） | YOLO-World | GPL-3.0 | `model.set_classes(["rag"])`，低频按需调用 |
| 防跌 | VL53L0X ToF ×2-3（腹部朝下） | MIT 驱动 | 毫秒级悬崖响应，远比视觉可靠 |
| 避障辅助 | OpenCV 光流 | Apache-2.0 | 检测前方快速逼近 |
| 深度（可选） | DepthAnything V2 | Apache-2.0 | CPU 太慢，仅建议有 Hailo-8L 时用 scdepthv3 HEF |

适配器：`duckpet/perception/vision.py`，统一收敛到 `VisionFacade` 接口，行为层不感知具体实现。

## 运动 / 技能策略

| 能力 | 组件 | 状态 |
|---|---|---|
| 行走 | Open Duck Mini 预训练 `BEST_WALK_ONNX_2.onnx`（50Hz RL 策略） | ✅ 现成 |
| 踢球 | microduck_rl `Mjlab-BallKick-Flat-MicroDuck` 训练管线 | ⚠️ 需按本鸭观测维度重训 |
| 喙叼东西 | microduck_rl `Mjlab-GroundPick` 训练管线 | ⚠️ 同上 |
| microduck 成品鸭 | 固件自带 `kick_left/right`、`ground_pick` 策略 slot | ✅ 现成（robotctl 调用） |

Open Duck Mini 行走控制：实例化 `RLWalk(commands=False)`，写
`rl_walk.last_commands = [vx, vy, wz, neck_pitch, head_pitch, head_yaw, head_roll]`。
适配器：`duckpet/hardware/openduck.py`。

## 指令理解

两层：`core/commands.py` 规则解析（毫秒级，覆盖 跟着/踢球/捡起/放到/停下/改名/登记 等高频指令）
→ 未命中可选本地 LLM（Ollama + Qwen2.5-1.5B，`format=` JSON Schema 强制结构化输出，Pi5 约 10 token/s）。

## 音效

- 叫声/提示音素材：Freesound（按 `license:"Creative Commons 0"` 过滤）+ Kenney.nl（CC0），
  一次性下载固化到 `assets/sounds/`（quack/ack/happy/helpless/giggle/melody.wav）
- 不要随仓库分发 CC-BY-NC 或 BBC RemArc 素材

## License 风险速查

- 可直接商用：sherpa-onnx、pyroomacoustics、ODAS、faster-whisper、DepthAnything、VL53L0X 驱动、Ollama/Qwen
- 传染性（GPL 系，DuckPet 作为开源项目兼容；闭源商用不行）：ultralytics、boxmot、YOLO-World、piper、edge-tts
- 仅非商业：InsightFace 全部模型权重（商用需向 insightface.ai 购授权，或换 Hailo Model Zoo 的 arcface）
- Open_Duck_Mini_Runtime / Open_Duck_Playground 仓库**未声明 License**，再分发前建议先向作者确认
