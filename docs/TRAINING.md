# 训练指南：怎么给鸭子"教"新动作

核心概念先说清楚：**强化学习不是写动作，而是写"奖励"**。
你不告诉鸭子"左腿抬 30°、右腿蹬地"——你定义什么叫好（球被踢远加分、
摔倒扣分、动作太猛扣分），PPO 算法在几千个并行仿真里试错几百万人次，
自己学会动作。你的工作是：**写任务环境（奖励函数），训练，导出 ONNX，部署**。

## 路线 A：不训练，直接用官方策略（默认）

microduck 固件自带 7 个策略 slot，踢球/喙叼都是现成的：

```bash
robotctl policy list                  # 看当前装的是什么策略
robotctl policy check                 # 查官方策略仓库有没有新版
sudo robotctl policy update           # 一键更新官方策略
robotctl robot do kick_right          # 手动触发踢球
robotctl robot do ground_pick         # 手动触发喙叼
```

DuckPet 已经接好这两个动作（`duckpet/hardware/microduck.py`）。

## 路线 B：自训一个新技能（比如"鞠躬""跳舞"）

### 1. 准备训练环境

```bash
git clone https://github.com/pollen-robotics/microduck_rl && cd microduck_rl
uv run list-envs                       # 看所有现成任务模板
```

需要 NVIDIA 显卡（训练走 MuJoCo Warp）；没有就在训练命令后加 `--hf-jobs`
用 Hugging Face 云端训练。

### 2. 写任务环境 = 告诉鸭子"什么叫做得好"

复制一个最接近的任务模板改（都在 `src/mjlab_microduck/tasks/`）：

- `microduck_ball_kick_env_cfg.py` —— 踢球：奖励脚对球的速度、球飞出的距离
- `microduck_ground_pick_env_cfg.py` —— 喙叼：奖励喙尖接近并触碰地面目标点
- `microduck_roulade_env_cfg.py` —— 前滚翻：奖励翻转角速度和落地站稳

奖励项的积木在 `tasks/mdp.py`；新任务在 `tasks/__init__.py` 注册。
**奖励设计的经验教训（摔倒惩罚权重、域随机化怎么开）都浓缩在仓库的
[CLAUDE.md](https://github.com/pollen-robotics/microduck_rl/blob/main/CLAUDE.md)，
动手前必读**——这是他们趟出来的 sim2real 配方（BAM 舵机电压级建模、
齿隙模拟、电量/摩擦随机化），直接决定真机能不能复现仿真动作。

### 3. 训练

```bash
# 4096 个并行仿真环境，GPU 上几十分钟到几小时
uv run train Mjlab-MySkill-Flat-MicroDuck --env.scene.num-envs 4096

# 中途看效果（3D 查看器重放训练中的策略）
uv run play Mjlab-MySkill-Flat-MicroDuck --wandb-run-path <entity/project/run_id>
```

### 4. 导出 ONNX

```bash
uv run scripts/export.py Mjlab-MySkill-Flat-MicroDuck --wandb-run-path <run路径>
```

**必须用官方 export 脚本**：它把观测归一化器烘进 ONNX 计算图，
手工转换的 checkpoint 在真机上会看到未归一化的观测而翻车。

### 5. 先在模拟器里验证（不用真机）

```bash
uv run scripts/infer_policy.py --walking policies/alpha_walking.onnx \
    --new-cmd-obs        # 键盘驱动；本项目 bash tools/sim_microduck.sh 亦可
```

所有策略共享 `obs[1,61] -> actions[1,14]` 契约（48 维本体感知 +
twist3 + head4 + body_pose6 指令位），不用的指令位补零——
这正是固件能热插拔策略的原因。

### 6. 部署到鸭子：作为 skill（推荐）

把你的 ONNX 传到 Hugging Face 仓库（比如 `你的名/microduck-my-skill`，
附 `manifest.json`），然后在鸭子上：

```bash
sudo robotctl policy add my-skill 你的名/microduck-my-skill
robotctl robot do my-skill                      # 触发
sudo robotctl pad bind x my-skill               # 绑到手柄 X 键
```

manifest 最小写法（一次性动作）：

```json
{ "file": "policy.onnx", "kind": "episodic", "duration_s": 4.0 }
```

- `episodic` + `duration_s` = 跑 N 秒自动交还行走策略 → 就是 skill
- `perpetual` = 持续型行为（如新步态），要 `policy load walk ...` 装进 slot
- 形状不是 `obs[1,61] -> actions[1,14]` 的策略**加载时直接拒绝**，安全

### 7. 接进 DuckPet

在 `duckpet/hardware/microduck.py` 加一行映射即可，例如：

```python
def bow(self) -> bool:
    return self._do("robot", "do", "polite-bow")
```

再在 `core/commands.py` 加中文触发词、`core/behaviors.py` 加一个行为类，
鸭子就会"听口令做新动作"了。

## 路线 C：Open Duck Mini 自训踢球/喙叼（备选平台）

microduck 和 Open Duck Mini 身体不同（15 vs 14 自由度、61 vs 54 维观测），
ONNX 不通用。参照上面同样的方法，在
[Open_Duck_Playground](https://github.com/apirrone/Open_Duck_Playground)
里新增 BallKick 任务（抄 microduck_rl 的 reward），按 54 维观测训练导出。
导出后放 `policies/` 目录，`duckpet/hardware/openduck.py` 已留加载接口。
偷懒方案：舵机关键帧手写踢球动作（参考 Petoi OpenCat 的技能组织），
精度要求低、半天见效。
