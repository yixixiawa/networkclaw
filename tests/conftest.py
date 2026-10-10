"""pytest 全局配置：把项目根加进 sys.path（tests 在子目录也能 import core/tools）。"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
