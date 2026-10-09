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
