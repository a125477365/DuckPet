# microduck_runtime — 仓库内置的 microduck 仿真运行时副本

从上游 [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl)
（Apache-2.0，LICENSE 已附上）**裁剪复制**的运行必需文件，让 DuckPet 在
`third_party/microduck_rl` 子模块没初始化（比如网络原因克隆超时）时也能直接跑 3D 仿真。

- 上游版本：`develop` 分支 `cb70b79`（2026-09-22 裁剪）
- 包含：`scripts/infer_policy.py`（策略推理引擎 PolicyInference）、
  `src/mjlab_microduck/robot/microduck/` 下的 `scene_ball.xml` 场景闭包
  （scene_ball.xml + robot_groundcontact.xml + ball.xml + 38 个 STL 网格）
- 不含：训练栈（mjlab/torch/warp）、其他场景、测试——这些需要完整子模块

## 加载优先级

`duckpet/hardware/mujoco_duck.py` 优先使用完整子模块
（`third_party/microduck_rl/scripts/infer_policy.py` 存在时），否则用本目录。
做训练/追上游最新仿真代码的，初始化子模块即可自动切换：

```bash
git submodule update --init --depth 1 third_party/microduck_rl
```

## 同步上游更新

升级子模块后（`git submodule update --remote`），把本目录重新裁剪一遍即可：

```bash
bash tools/sync_microduck_runtime.sh
```
