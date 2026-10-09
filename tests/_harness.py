#!/usr/bin/env python3
"""测试 harness 桥接 —— 让「脚本式」自测也能被 pytest / unittest 收集。

本目录下的 4 个自测文件原本都是「模块级 main() + 自制 check() 计数器」的独立
脚本（`python tests/test_memory_guard.py` 直接运行）。它们的断言写在 main() 里，
模块级没有任何 test_* 函数 / TestCase，因此：

* `python -m unittest discover -s tests` → **"Ran 0 tests ... OK"**（退出码 0，假绿）
* `pytest tests` → 0 collected

`make_script_test_case(__name__)` 把该模块的 main() 包装成一个 TestCase，
直接运行与标准 runner 两种方式都覆盖，且断言失败会以断言错误（而非静默退出码）呈现。
"""
import contextlib
import io
import sys
import unittest


def make_script_test_case(module_name):
    """返回包装该模块 main() 的 TestCase 类；模块没有 main() 时返回 None。"""
    module = sys.modules[module_name]
    main = getattr(module, "main", None)
    if main is None:
        return None

    class ScriptChecks(unittest.TestCase):
        maxDiff = None

        def test_script_checks(self):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main()
            out = buf.getvalue()
            self.assertIn("passed", out, msg="main() 未输出用例统计:\n" + out[-2000:])
            self.assertEqual(rc, 0, msg="自测存在失败项:\n" + out[-4000:])

    short = module_name.rsplit(".", 1)[-1]
    pretty = "".join(w.capitalize() for w in short.replace("_", " ").split())
    ScriptChecks.__name__ = "Test%sChecks" % pretty
    ScriptChecks.__qualname__ = ScriptChecks.__name__
    ScriptChecks.__module__ = module_name
    ScriptChecks.__doc__ = "由 %s.main() 生成的脚本式自测" % short
    return ScriptChecks