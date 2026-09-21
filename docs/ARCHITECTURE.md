# DuckPet 架构：功能是怎么"合并"的？性能够吗？

## 不是一个巨型模型，而是"一个小大脑 + 一堆小模型"

DuckPet 没有把所有功能塞进一个模型，而是**调度架构**：
一个零依赖的规则大脑（状态机 + 优先级仲裁），按需调用一堆各司其职的小模型。
每个小模型只做一件事，而且**绝大部分时间它们是关着的**。

```
                ┌────────────────────────────┐
                │  大脑（纯 Python，~0 算力）   │
                │  状态机 + 优先级仲裁 + 性格    │
                └───────┬────────────────────┘
        ┌───────────────┼────────────────┬──────────────┐
        ▼               ▼                ▼              ▼
   常驻低功耗        触发式(秒级)      按需调用         固件自带
   唤醒词 KWS       ASR / 声纹       视觉/LLM        运动策略槽
   (3.3M 参数)      (唤醒后才跑)     (做事时才跑)     (50Hz 小MLP)
```

## 运动策略：microduck 的 slot/skill 机制（官方设计，不是我们发明的）

microduck 固件（Rust 守护进程 `robotd`）本身就支持**策略热插拔**：

- **7 个 slot**（常驻默认行为）：`walk / stand / sitstand / ground_pick / kick_left / kick_right / roulade`
- **skill**（被叫才跑的一次性技能）：`sudo robotctl policy add polite-bow <HF仓库>`，然后 `robotctl robot do polite-bow`
- 所有策略共享同一份**观测契约 `obs[1,61] -> actions[1,14]`**——所以任何时刻只有一个策略在驱动关节，踢球的瞬间踢球策略接管，踢完 0.5 秒自动还给行走策略
- 每个策略 ONNX 只有 **~775KB**（小 MLP），50Hz 推理在 RK3566 上毫无压力

DuckPet 的 `KickBallBehavior` / `CarryBehavior` 只是"决定什么时候踢"，真正的动作由固件 slot 执行（`duckpet/hardware/microduck.py` 里 `kick()` 就是 `robotctl robot do kick_right`）。**不存在"装多个模型性能不够"的问题——策略是换着上的，不是同时跑的。**

## DuckPet 加装的感知模型，性能预算（RK3566 / 4 核 A55）

| 模型 | 大小 | 运行时机 | CPU 占用估计 |
|---|---|---|---|
| KWS 唤醒词 | 19MB (3.3M 参数) | **常驻**，唯一一直听着的 | 单核 ~5-10% |
| 流式中文 ASR | ~100MB int8 | 仅唤醒后 3-5 秒 | 瞬时 1-2 核 |
| CAM++ 声纹 | 27MB (7M 参数) | 仅唤醒后一次 | 瞬时 <1 核秒 |
| YOLO11n 检测 | ~10MB | 跟随/找球时 ~5-10 FPS | 期间 1-2 核 |
| InsightFace buffalo_sc | 16MB | 检测到人脸才识别一次 | 可忽略 |
| YOLO-World | ~100MB | 仅"搬东西"找抹布时 | 秒级一次 |
| piper TTS | ~60MB | 说话时 | 瞬时 |
| RL 运动策略 | 775KB | 常驻 50Hz | 单核 <5% |

**结论：够用，但要守规矩**——DuckPet 的架构保证了"同一时刻只干一件事"
（优先级仲裁器的副作用），所以峰值负载 = 1 个策略 + 1 个感知模型，RK3566 扛得住。
真不够时还有两条退路：重活（Grounding DINO、LLM）走 WiFi 放家里服务器上
（`[llm] enabled` 就是为这留的），或者只在你开发机上跑感知、鸭子只跑运动。

## 人物识别：不只靠声音（多模态融合）

"认出是谁"由三路特征融合，档案存在 `PersonRegistry`（声纹/人脸 embedding + 身高体型）：

| 特征 | 真机模型 | 何时用 | 局限 |
|---|---|---|---|
| 声纹 | CAM++ / ECAPA-TDNN（`match_voice`） | 有人呼叫、说话时——**认人的第一入口** | 远场、嘈杂环境会掉 |
| 人脸 | InsightFace/MobileFaceNet（`match_face`） | 人正脸且 ≤2m 时 | 背对、侧脸、戴口罩不行 |
| 身高体型 / ReID | 姿态估计（RTMPose）+ OSNet 行人重识别 | 看不清脸时的粗筛：档案里唯一匹配才算认出 | 只能区分体格差异大的人 |

规则与仿真实现（`duckpet/hardware/mujoco_vision.py`）一致：**任何一路单独认出就算；
都认不出就是陌生人**——陌生人照样能叫鸭子玩（踢球/叼东西），但跟随等
特权指令只认主人/家人。3D 仿真里这些特征是由名字确定性生成的合成向量，
不跑真模型，但"视野是否可见、距离够不够近、是不是正脸"全部按真实几何判定，
所以可以测试"未登记的路人叫我""两个身高相同的人站在一起认不出"等场景。

## DuckPet 与 microduck 固件的关系

```
DuckPet 大脑(Python, 本项目)
   │  robotctl CLI / JSON-RPC socket
   ▼
microduck 固件(Rust 守护进程: robotd/mediad/tofd/padd)
   │  50Hz 控制环 + 策略 slot/skill + ToF + 相机 + 声音
   ▼
硬件(15 舵机 / VL53L8 ToF / 摄像头 / 麦克风 / 扬声器)
```

DuckPet 不动固件，所有"升级"都走官方通道：新策略 = `robotctl policy add`，
官方策略更新 = `sudo robotctl policy update`（固件自带）。
