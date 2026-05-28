"""具体工具模块 — 导入以触发 ``registry.register()`` 调用。

此包中的每个 ``.py`` 文件在模块导入时通过
``abstract.tools.registry.registry.register()`` 注册其工具。
仅导入此包即可填充全局 ToolRegistry。
"""

from . import filesystem  # noqa: F401 — 副作用：注册文件系统工具
from . import code        # noqa: F401 — 副作用：注册代码工具
from . import frontend    # noqa: F401 — 副作用：注册前端工具
from . import shell       # noqa: F401 — 副作用：注册 shell 工具
from . import skills      # noqa: F401 — 副作用：注册 skill 工具
from . import run_python  # noqa: F401 — 副作用：注册 run_python 工具
from . import read_image  # noqa: F401 — 副作用：注册 read_image 工具