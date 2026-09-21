"""仿真入口（等价于 python3 -m duckpet.sim）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from duckpet.sim import main

if __name__ == "__main__":
    main()
