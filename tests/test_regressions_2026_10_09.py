#!/usr/bin/env python3
"""回归自测：锁定 2026-10-09 代码审查修复的缺陷（防回退）。

标准 unittest 写法，可被 pytest 与 `python -m unittest discover -s tests` 收集：

    python -m unittest discover -s tests -v

覆盖：
1. qid 归一化：短号（Q-3 / q-1）必须补零；非法输入必须报错而非落到 Q-0001
2. legacy schema 迁移在事务内完成且幂等
3. setup_hooks 只摘自己的 hook，用户自己挂在同一事件上的 hook 必须保留
4. stdin 读取有超时保护（宿主给的「永不 EOF 的 PIPE」不会永久挂死）
5. qa_query qa-update 走状态机校验：非法 status 拒绝写入，date 为只读字段
6. health_report 复用 O(n^2) 扫描缓存（库未变化时不重跑）
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import db as qa_db  # noqa: E402
import memory_health as MH  # noqa: E402
import setup_hooks  # noqa: E402


def run_cli(args, payload=None, cwd=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_tool.py")] + args,
                          cwd=cwd, input=(json.dumps(payload, ensure_ascii=False) if payload else None),
                          capture_output=True, text=True, encoding="utf-8")


def run_query(args, payload=None, cwd=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "qa_query.py")] + args,
                          cwd=cwd, input=(json.dumps(payload, ensure_ascii=False) if payload else None),
                          capture_output=True, text=True, encoding="utf-8")


class TestQidNormalize(unittest.TestCase):
    def test_short_forms_are_padded(self):
        for raw, want in [("3", "Q-0003"), ("Q-3", "Q-0003"), ("q-1", "Q-0001"),
                          ("Q-001", "Q-0001"), (" 12 ", "Q-0012"), ("Q3", "Q-0003"),
                          ("Q-0003", "Q-0003"), ("10000", "Q-10000")]:
            self.assertEqual(qa_db.normalize_id(raw), want, "normalize_id(%r)" % raw)

    def test_invalid_raises_instead_of_defaulting_to_first(self):
        # 历史 bug：normalize_id("Q") / normalize_id("") 都静默返回 Q-0001
        for raw in ("Q", "", "  ", "abc", "Q-", "Q-abc", "-", None):
            with self.assertRaises(ValueError, msg="normalize_id(%r) 应报错" % raw):
                qa_db.normalize_id(raw)

    def test_cli_rejects_invalid_id_with_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run_cli(["setup"], cwd=d).returncode, 0)
            r = run_cli(["get", "Q"], cwd=d)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            r = run_cli(["get", "Q-1"], cwd=d)
            self.assertEqual(r.returncode, 1, "合法短号应报 not found 而非参数错误")
            self.assertIn("Q-0001", r.stdout + r.stderr)

    def test_query_get_uses_same_normalization(self):
        with tempfile.TemporaryDirectory() as d:
            run_cli(["setup"], cwd=d)
            r = run_query(["qa-get", "--qid", "Q-1"], cwd=d)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Q-0001", r.stdout, "插件与 CLI 必须解析成同一个 qid")


class TestLegacyMigration(unittest.TestCase):
    def _make_legacy(self, path):
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE qa_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qid TEXT UNIQUE, date TEXT, category TEXT, status TEXT,
                phenomenon TEXT, root_cause TEXT, solution TEXT, files TEXT, created_at TEXT
            );
            INSERT INTO qa_entries
                (qid, date, category, status, phenomenon, root_cause, solution, files, created_at)
            VALUES ('Q-0001','2026-01-01','Bug Fix','已验证','旧记录','rc','sol','f','2026-01-01');
            """
        )
        conn.commit()
        conn.close()

    def test_migration_preserves_rows_and_columns(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "qa.db")
            self._make_legacy(path)
            conn = qa_db.connect(path)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(qa_entries)")}
            self.assertNotIn("id", cols, "legacy id 列应被迁移掉")
            for col, _ddl in qa_db.MEMORY_COLUMNS:
                self.assertIn(col, cols)
            row = conn.execute("SELECT * FROM qa_entries WHERE qid='Q-0001'").fetchone()
            self.assertIsNotNone(row, "迁移必须保留原有记录")
            self.assertEqual(row["phenomenon"], "旧记录")
            conn.close()

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "qa.db")
            self._make_legacy(path)
            for _ in range(3):
                conn = qa_db.connect(path)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM qa_entries").fetchone()[0], 1)
                conn.close()


class TestSetupHooks(unittest.TestCase):
    def _write_user_hook(self, d):
        p = os.path.join(d, "settings.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"hooks": {"UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "my-own-checker --strict"}]}]},
                "other": {"keep": True}}, f)
        return p

    @staticmethod
    def _cmds(cfg, event):
        return [h["command"] for g in cfg.get("hooks", {}).get(event, []) for h in g["hooks"]]

    def test_install_preserves_foreign_hook(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_user_hook(d)
            old, setup_hooks.SETTINGS = setup_hooks.SETTINGS, p
            try:
                setup_hooks.do_install()
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f)
            finally:
                setup_hooks.SETTINGS = old
            cmds = self._cmds(cfg, "UserPromptSubmit")
            self.assertTrue(any("my-own-checker" in c for c in cmds), "用户 hook 被删: %r" % cmds)
            self.assertTrue(any("agent_log_hook.py" in c for c in cmds), "本脚本 hook 未写入")
            self.assertEqual(cfg.get("other"), {"keep": True})

    def test_remove_preserves_foreign_hook(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._write_user_hook(d)
            old, setup_hooks.SETTINGS = setup_hooks.SETTINGS, p
            try:
                setup_hooks.do_install()
                setup_hooks.do_remove()
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f)
            finally:
                setup_hooks.SETTINGS = old
            cmds = self._cmds(cfg, "UserPromptSubmit")
            self.assertTrue(any("my-own-checker" in c for c in cmds), "卸载误删用户 hook: %r" % cmds)
            self.assertFalse(any("agent_log_hook.py" in c for c in cmds))


class TestStdinTimeout(unittest.TestCase):
    def test_unclosed_pipe_does_not_hang(self):
        """写端不关闭 → read() 永远等不到 EOF；必须在超时后放弃而不是挂死。"""
        import stdin_io
        r, w = os.pipe()
        try:
            os.write(w, b'{"question":"from pipe"}')
            stream = open(r, "rb", buffering=0, closefd=False)
            box = {}
            th = threading.Thread(
                target=lambda: box.update(v=stdin_io.read_text_stdin(timeout=1.0, stream=stream)))
            th.start()
            th.join(6)
            self.assertFalse(th.is_alive(), "read_text_stdin 被永不 EOF 的管道挂死")
            self.assertEqual(box.get("v"), "", "无 EOF 时应视作「没有 stdin 输入」")
        finally:
            os.close(w)
            # 不 close 读端：close() 会等阻塞中的读线程（那会把测试挂死）；
            # 包装对象由 GC 回收，fd 由下面显式关闭。
            os.close(r)

    def test_closed_pipe_yields_payload(self):
        """正常场景：写端关闭 → 读到完整 JSON（管道用法不能被破坏）。"""
        import stdin_io
        r, w = os.pipe()
        try:
            os.write(w, b'{"question":"from pipe"}')
            os.close(w)
            stream = open(r, "rb", buffering=0, closefd=False)
            self.assertEqual(stdin_io.read_text_stdin(timeout=3.0, stream=stream),
                             '{"question":"from pipe"}')
            stream.close()
        finally:
            try:
                os.close(r)
            except OSError:
                pass

    def test_append_with_stdin_pipe_writes_entry(self):
        with tempfile.TemporaryDirectory() as d:
            run_cli(["setup"], cwd=d)
            proc = subprocess.Popen(
                [sys.executable, os.path.join(SCRIPTS, "qa_tool.py"), "append", "--json", "-c", "Bug Fix"],
                cwd=d, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8")
            payload = json.dumps({"question": "宿主通过 stdin 管道传入的问题描述，足够长以通过闸门"},
                                 ensure_ascii=False)
            try:
                out, err = proc.communicate(input=payload, timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                self.fail("qa_tool append 在 stdin 管道下挂死")
            self.assertEqual(proc.returncode, 0, err)
            self.assertIn("Created Q-0001", out)


class TestQueryUpdateGuards(unittest.TestCase):
    def _seed(self, d):
        self.assertEqual(run_cli(["setup"], cwd=d).returncode, 0)
        # 内容必须够长：写入闸门会拒绝「去重后有效字符 < 40」的草稿（low_information）
        r = run_cli(["append", "--json", "-c", "Bug Fix"], cwd=d,
                    payload={"question": "插件通道的状态机收口：非法 status 必须被拒绝，避免库中混入非规范状态值",
                             "root_cause": "qa_query act_qa_update 此前只依赖写入闸门，而 force 可绕过状态校验",
                             "solution": "在 act_qa_update 里复用 qa_tool.VALID_STATUSES 做白名单校验，force 只跳内容类 reject"})
        self.assertIn("Created", r.stdout, r.stderr)

    def test_invalid_status_rejected_even_with_force(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            r = run_query(["qa-update", "--qid", "Q-0001"], cwd=d,
                          payload={"status": "已解决", "force": True})
            self.assertNotEqual(r.returncode, 0, "非法状态必须被拒绝，即使带 force")
            self.assertIn("invalid status", r.stdout)

    def test_valid_status_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            r = run_query(["qa-update", "--qid", "1"], cwd=d, payload={"status": "已验证"})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(json.loads(r.stdout)["ok"])

    def test_date_is_readonly(self):
        with tempfile.TemporaryDirectory() as d:
            self._seed(d)
            r = run_query(["qa-update", "--qid", "Q-0001"], cwd=d, payload={"date": "1999-01-01"})
            # date 被剥离后没有可更新字段 → 明确报错，而不是静默写入审计基准
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("no fields to update", r.stdout)
            got = run_query(["qa-get", "--qid", "Q-0001"], cwd=d)
            self.assertNotEqual(json.loads(got.stdout)["data"]["entry"]["date"], "1999-01-01")


class TestHealthScanCache(unittest.TestCase):
    def test_second_call_reuses_cache(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "qa.db")
            run_cli(["setup"], cwd=d)
            conn = qa_db.connect(path)
            conn.execute("INSERT INTO qa_entries (qid,date,category,status,phenomenon) "
                         "VALUES ('Q-0001','2026-01-01','Bug Fix','Pending','记录')")
            conn.commit()
            calls = []
            real_dup, real_conf = MH.MR.find_near_duplicates, MH.find_conflicts
            MH.MR.find_near_duplicates = lambda c, *a, **k: (calls.append("dup"), real_dup(c, *a, **k))[1]
            MH.find_conflicts = lambda c, *a, **k: (calls.append("conf"), real_conf(c, *a, **k))[1]
            try:
                MH.health_report(conn)
                self.assertEqual(len(calls), 2, "首次应各跑一次")
                MH.health_report(conn)
                self.assertEqual(len(calls), 2, "库未变化时不应重跑 O(n^2) 扫描")
                conn.execute("UPDATE qa_entries SET updated_at=datetime('now','localtime') WHERE qid='Q-0001'")
                conn.commit()
                MH.health_report(conn)
                self.assertEqual(len(calls), 4, "库变化后应重算")
            finally:
                MH.MR.find_near_duplicates, MH.find_conflicts = real_dup, real_conf
                conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)