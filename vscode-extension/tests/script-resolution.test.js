/**
 * 脚本解析回归：安装副本可能是旧版（缺 health/recall），必须被跳过而不是被选中。
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");

const VSCODE_STUB = {
  window: { createOutputChannel: () => ({ appendLine() {}, dispose() {} }) },
  workspace: {
    getConfiguration: () => ({ get: () => undefined }),
    isTrusted: true,
    workspaceFolders: [{ uri: { fsPath: process.cwd() } }],
  },
};
const origLoad = Module._load;
Module._load = function (request) {
  if (request === "vscode") return VSCODE_STUB;
  return origLoad.apply(this, arguments);
};

const src = fs.readFileSync(path.join(__dirname, "..", "src", "extension.js"), "utf8");

test('REQUIRED_ACTIONS 声明了扩展依赖的动作', () => {
  assert.ok(src.includes("REQUIRED_ACTIONS"));
  assert.ok(src.includes("health"));
  assert.ok(src.includes("recall"));
});

test('scriptSupports 会拒绝缺少 action 的旧版脚本', () => {
  const body = src.match(/function scriptSupports\(file, actions\) \{[\s\S]*?\n\}/)[0];
  const scriptSupports = new Function("fs", "_scriptSupportCache", body + "; return scriptSupports;")(fs, new Map());
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "qaold-"));
  const old = path.join(d, "qa_query.py");
  // 旧版：只有 qa-list / qa-get，没有 health / recall
  fs.writeFileSync(old, 'ACTIONS = {' + '"qa-list": act_qa_list, "qa-get": act_qa_get}');
  const fresh = path.join(d, "qa_query_new.py");
  fs.writeFileSync(fresh, 'ACTIONS = {' + '"health": act_health, "recall": act_recall, "qa-list": act_qa_list}');

  assert.strictEqual(scriptSupports(old, ['health', 'recall', 'qa-list']), false, '旧版必须被判为不支持');
  assert.strictEqual(scriptSupports(fresh, ['health', 'recall', 'qa-list']), true, '新版必须被判为支持');
});

test('scriptPath 循环会跳过不支持的候选', () => {
  assert.ok(/scriptSupports\(c, wanted\)/.test(src), '必须按 action 支持性筛选候选');
  assert.ok(/fs\.existsSync\(c\) && scriptSupports/.test(src), '存在性之外还要校验 action');
});

test('扩展内置脚本是首选候选（跨机自包含，不受旧版安装副本影响）', () => {
  const m = src.match(/const candidates = \[\n([\s\S]*?)\n  \];/);
  assert.ok(m, '应能定位 scriptPath 的 candidates 数组');
  assert.ok(
    m[1].includes("path.join(__dirname, '..', 'scripts', 'qa_query.py')"),
    '首选候选必须是扩展内置的 scripts/qa_query.py',
  );
  assert.ok(
    src.indexOf("path.join(__dirname, '..', 'scripts', 'qa_query.py')")
      < src.indexOf("'.claude', 'skills'"),
    '内置副本必须排在 ~/.claude 等家目录候选之前',
  );
});

test('扩展内置脚本与 skill 仓库源保持一致（防漂移）', () => {
  const files = ['qa_query.py', 'db.py', 'memory_guard.py', 'memory_recall.py', 'agent_log_hook.py'];
  for (const f of files) {
    const bundled = path.join(__dirname, '..', 'scripts', f);
    const source = path.join(__dirname, '..', '..', 'scripts', f);
    assert.ok(fs.existsSync(bundled), `缺少内置脚本 ${f}（先跑 npm run sync-vendor）`);
    assert.strictEqual(
      fs.readFileSync(bundled, 'utf8'),
      fs.readFileSync(source, 'utf8'),
      `内置 ${f} 与 ../scripts/${f} 不一致（先跑 npm run sync-vendor）`,
    );
  }
});
