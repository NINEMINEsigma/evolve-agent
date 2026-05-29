"""Extools — 外部工具集（网络搜索、网页抓取等）。

每个 ``.py`` 文件在模块导入时通过
``abstract.tools.registry.registry.register()`` 注册其工具。
仅导入此包即可注册 extools 工具。
"""

from . import web_fetch  # noqa: F401 — 副作用：注册 web_fetch 工具
from . import web_search  # noqa: F401 — 副作用：注册 web_search 工具
from . import csv_tools  # noqa: F401 — 副作用：注册 read_csv / write_csv
from . import excel_tools  # noqa: F401 — 副作用：注册 read_excel / write_excel
from . import docx_tools  # noqa: F401 — 副作用：注册 read_docx
from . import pdf_tools  # noqa: F401 — 副作用：注册 read_pdf
from . import ffmpeg_tools  # noqa: F401 — 副作用：注册 ffmpeg 工具集
from . import diff_tools  # noqa: F401 — 副作用：注册 diff_origin 工具
from . import web_browser  # noqa: F401 — 副作用：注册 browser_* 工具集
from . import diagram  # noqa: F401 — 副作用：注册 draw_diagram / render_diagram
from . import docgen_tools  # noqa: F401 — 副作用：注册 write_docx / write_xlsx / write_pptx / write_pdf
from . import display  # noqa: F401 — 副作用：注册 display_image / publish_file
from . import pip  # noqa: F401 — 副作用：注册 install_package