"""SVG 页面模式对照实验的度量脚本。

两组页面（HTML、SVG）用同一套信号与指标：越界、压叠、文本超框、空白带、等大矩形组、
stage 覆盖率。SVG 页直接复用 ``landppt.services.slide.svg_page`` 的检查器；HTML 页用
Playwright 渲染后读取包围盒，再交给同一批几何函数计算，保证两组可比。

用法见 README.md。
"""
