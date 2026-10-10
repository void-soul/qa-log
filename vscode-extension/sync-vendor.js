/**
 * 把扩展依赖的 Python 脚本从 skill 仓库 ../scripts/ 同步到本包的 scripts/。
 *
 * 单一真源是 skill 仓库的 ../scripts/；扩展只携带「内置副本」（与 vendor/marked.min.js
 * 同一机制），使扩展在任何机器上安装即可用，无需另外安装 skill（修复跨机
 * 「找不到 qa_query.py」的问题）。scriptPath() 优先使用这份内置副本，
 * 脚本版本与 extension.js 始终一致，不受磁盘上旧版 skill 安装副本影响。
 *
 * `npm run package` 前自动执行（prepackage）；也可手动 `npm run sync-vendor`。
 * 在 skill 仓库改过 Python 脚本后，必须重新同步再打 vsix。
 */
const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', 'scripts');
const DEST = path.join(__dirname, 'scripts');

// qa_query.py 的完整依赖闭包（tests 里有传递闭包 import 扫描回归测试防遗漏）：
//   qa_query.py  模块级 import db；act_recall 惰性 import memory_recall；
//                act_health 惰性 import memory_health；act_update 改 status 时
//                硬性惰性 import qa_tool（无 try/except，必须打包）
//   qa_tool.py   模块级 import db / memory_guard / stdin_io；
//                惰性 import memory_recall / memory_health
//   stdin_io.py  仅标准库（qa_tool 模块级 import，Q-0004 加的 stdin 读取守卫）
//   db.py        仅标准库
//   memory_health.py  import memory_guard / memory_recall，惰性 import db
//   memory_recall.py  import memory_guard
//   memory_guard.py   惰性 import qa_tool 在 try/except 内且有内置回退（qa_tool 已打包，走正常路径）
//   agent_log_hook.py installHooks 使用的 hook 脚本（惰性 import db，自身仅标准库）
// 0.2.2 漏收 memory_health / qa_tool / stdin_io：「记忆健康」视图报
// memory_health module not available、更新 status 报 No module named 'stdin_io'，0.2.3 补齐。
const FILES = [
  'qa_query.py',
  'qa_tool.py',
  'stdin_io.py',
  'db.py',
  'memory_health.py',
  'memory_guard.py',
  'memory_recall.py',
  'agent_log_hook.py',
];

fs.mkdirSync(DEST, { recursive: true });
let changed = 0;
for (const f of FILES) {
  const from = path.join(SOURCE, f);
  const to = path.join(DEST, f);
  if (!fs.existsSync(from)) {
    console.error(`sync-vendor: 源文件缺失 ${from}`);
    process.exit(1);
  }
  if (!fs.existsSync(to) || fs.readFileSync(from, 'utf8') !== fs.readFileSync(to, 'utf8')) {
    fs.copyFileSync(from, to);
    changed += 1;
    console.log(`sync-vendor: 更新 ${f}`);
  }
}
console.log(`sync-vendor: 完成，更新 ${changed} 个，共 ${FILES.length} 个 → ${DEST}`);
