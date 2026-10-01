"""每个测试脚本的第一行 import：把 tools\\ 和 src\\ 放进 sys.path。

    import bootstrap          # noqa: F401  ← 必须在最前面
    import testconfig as C
    import fixtures

这样 `python tests\\test_xxx.py` 和 `python -m tests.test_xxx` 都能跑。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "tools"), os.path.join(ROOT, "src"), os.path.dirname(os.path.abspath(__file__))):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
