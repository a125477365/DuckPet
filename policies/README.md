# policies/ — DuckPet 自带的动作策略模型

本目录收录 DuckPet 仿真与真机所需的全部 ONNX 策略，clone 仓库即可运行，无需再单独下载。
所有策略均为 **61D 观测 / 14 关节输出** 的统一契约（microduck 策略家族热切换规范，见
`third_party/microduck_rl/AGENTS.md`），控制频率 50 Hz。

## 官方策略（Pollen Robotics，Apache-2.0）

来源：<https://huggingface.co/pollen-robotics/microduck-policies>

| 文件 | 用途 |
| --- | --- |
| `alpha_walking.onnx` | 行走（默认行走策略，指令范围 vx ±0.3 m/s、vy ±0.2、wz ±1.5 rad/s） |
| `alpha_stand.onnx` | 站立 |
| `alpha_sitstand.onnx` | 坐下 / 站起（posture flag 编码） |
| `alpha_ground_pick.onnx` | 地面叼取（搬东西的"叼"动作，相位编码） |
| `ball_kick_left.onnx` / `ball_kick_right.onnx` | 左/右脚踢球（插曲式，0.5 s） |
| `roulade.onnx` | 前滚翻（官方版，行走中接续成功率约 86%） |

`manifest.json` 为官方策略清单（schema-2），真机侧 `robotctl policy add` 使用该格式。

## 社区策略（Apache-2.0）

| 文件 | 来源 | 用途 |
| --- | --- | --- |
| `roulade_elan.onnx` | <https://huggingface.co/langli11/microduck-tricks> | 前滚翻加强版（行走中接续成功率 200/200，优先于官方版启用） |
| `rough_walk_g.onnx` | RemiFabre（microduck 社区） | 粗糙地面行走：2 cm 台阶 / 9° 斜坡更稳；代价是转向弱（0.29 rad/s）、功耗 +17%，下 ≥2 cm 台阶仍会摔。可在配置里切换 `walking_policy = "rough_walk_g"` |

## 升级 / 新增策略

社区出了更好的策略时，下载 ONNX 放进本目录即可即插即用：

```bash
# 例：官方发布新策略时
huggingface-cli download pollen-robotics/microduck-policies --include "*.onnx" --local-dir policies/
```

新动作（后滚翻、原地跳、躺下等）的训练方法见项目根目录 `PLUGINS.md` 与
`third_party/microduck_rl/AGENTS.md`。
