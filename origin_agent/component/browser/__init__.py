"""browser 工具组 — 通过 CDP 接管用户真实浏览器，读取 JS 渲染后的页面。

四个工具（connect / list_tabs / read_page / screenshot）共享
``_connection`` 模块中的连接单例与标签页定位逻辑。
"""