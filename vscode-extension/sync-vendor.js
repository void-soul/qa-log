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

// qa_query.py 的最小依赖闭包：
//   qa_query.py  模块级 import db；act_recall 惰性 import memory_recall
//   db.py        仅标准库
//   memory_recall.py  import memory_guard
//   memory_guard.py   惰性 import qa_tool 在 try/except 内且有内置回退，不打包
//   agent_log_hook.py installHooks 使用的 hook 脚本（惰性 import db，自身仅标准库）
const FILES = [
  'qa_query.py',
  'db.py',
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
