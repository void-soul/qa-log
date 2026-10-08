/**
 * Python 定位逻辑自测（`qaLog.pythonPath` 三态：裸命令 / 路径 / 带参数命令）。
 *
 * 运行：node --test vscode-extension/tests/python-path.test.js
 *
 * extension.js 顶层就要用 vscode.window.createOutputChannel，所以这里用 Module._load
 * 打桩注入一个最小的 vscode 假实现，只测纯函数，不启动扩展宿主。
 */
const test = require('node:test');
const assert = require('node:assert');
const Module = require('module');
const fs = require('fs');
const os = require('os');
const path = require('path');

const VSCODE_STUB = {
  window: { createOutputChannel: () => ({ appendLine() {}, dispose() {} }) },
  workspace: { getConfiguration: () => ({ get: () => undefined }) },
};

const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'vscode') return VSCODE_STUB;
  return origLoad.apply(this, arguments);
};
const ext = require('../src/extension');
Module._load = origLoad;

const { isPythonPath, pythonArgv, pythonCmdForHook } = ext;

test('isPythonPath: 只有含路径分隔符才算路径', () => {
  assert.strictEqual(isPythonPath('python'), false, '裸命令不是路径');
  assert.strictEqual(isPythonPath('py -3'), false, '带参数命令不是路径');
  assert.strictEqual(isPythonPath('D:\\sdk\\python\\python.exe'), true);
  assert.strictEqual(isPythonPath('/usr/bin/python3'), true);
  assert.strictEqual(isPythonPath('./.venv/bin/python'), true);
});

test('pythonArgv: 裸命令 → 单元素数组', () => {
  assert.deepStrictEqual(pythonArgv('python'), ['python']);
  assert.deepStrictEqual(pythonArgv('python3'), ['python3']);
});

test('pythonArgv: `py -3` → 拆成命令 + 前置参数', () => {
  assert.deepStrictEqual(pythonArgv('py -3'), ['py', '-3']);
});

test('pythonArgv: 路径 → 整体作为一个 cmd（含空格也不拆）', () => {
  const p = path.join('C:', 'Program Files', 'Python', 'python.exe');
  assert.deepStrictEqual(pythonArgv(p), [p]);
});

test('pythonArgv: 空值兜底为 python', () => {
  assert.deepStrictEqual(pythonArgv('   '), ['python']);
  assert.deepStrictEqual(pythonArgv(''), ['python']);
});

test('pythonCmdForHook: 路径加引号，命令不加', () => {
  const p = path.join('D:', 'any-versions sdk', 'python', 'python.exe');
  assert.strictEqual(pythonCmdForHookFor(p), `"${p}"`, '路径必须加引号（进 shell / settings.json）');
  assert.strictEqual(pythonCmdForHookFor('py -3'), 'py -3', '带参数的命令不能整体加引号');
  assert.strictEqual(pythonCmdForHookFor('python'), 'python');
});

function pythonCmdForHookFor(value) {
  // pythonCmdForHook 读的是配置，这里临时把配置值塞进 stub 再调用
  VSCODE_STUB.workspace.getConfiguration = () => ({ get: () => value });
  try {
    return pythonCmdForHook();
  } finally {
    VSCODE_STUB.workspace.getConfiguration = () => ({ get: () => undefined });
  }
}

test('回归：工作区里存在名为 python 的文件也不会被当成路径', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qalog-py-'));
  const decoy = path.join(dir, 'python');
  fs.writeFileSync(decoy, '');
  const cwd = process.cwd();
  try {
    process.chdir(dir);
    assert.strictEqual(fs.existsSync('python'), true, '前置条件：cwd 下确实有 python 文件');
    assert.strictEqual(isPythonPath('python'), false, '裸命令不能因同名文件被判成路径');
    assert.deepStrictEqual(pythonArgv('python'), ['python']);
    assert.strictEqual(pythonCmdForHookFor('python'), 'python', 'hook 命令也不该变成相对路径');
  } finally {
    process.chdir(cwd);
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
