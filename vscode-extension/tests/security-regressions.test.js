/**
 * 安全回归自测：锁定 2026-10-09 代码审查修复的缺陷（防回退）。
 * 运行：npm test（= node --test "tests/*.test.js"）
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', 'src');
const viewsSrc = fs.readFileSync(path.join(SRC, 'views.js'), 'utf8');
const extSrc = fs.readFileSync(path.join(SRC, 'extension.js'), 'utf8');
const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));

/** 执行页面内联脚本，捕获 document 上注册的 click 委托。 */
function clickHandlerOf(html, postMessage) {
  const m = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/);
  assert.ok(m, '页面应包含内联脚本');
  const stubEl = () => ({
    value: '', textContent: '', addEventListener() {}, querySelectorAll: () => [],
    classList: { add() {}, remove() {} }, style: {}, dataset: {}, children: [],
    appendChild() {}, set innerHTML(v) { this._h = v; }, get innerHTML() { return this._h || ''; },
  });
  const doc = {
    addEventListener(t, h) { if (t === 'click') doc.__click = h; },
    getElementById: stubEl, querySelectorAll: () => [], createElement: stubEl,
    createTreeWalker: () => ({ nextNode: () => null }),
  };
  const api = { postMessage, setState() {}, getState: () => undefined };
  // 参数名不能与脚本内的 `const vscode = ...` 冲突，故用 __ 前缀再在序言里别名
  const prologue = 'const document = __document, marked = __marked, console = __console;';
  const sandbox = {
    __document: doc,
    __marked: { parse: (t) => t },
    __console: console,
    acquireVsCodeApi: () => api,
    NodeFilter: { SHOW_TEXT: 4, FILTER_ACCEPT: 1, FILTER_REJECT: 2 },
    window: {},
  };
  const names = Object.keys(sandbox);
  // eslint-disable-next-line no-new-func
  new Function(...names, prologue + m[1])(...names.map((n) => sandbox[n]));
  assert.strictEqual(typeof doc.__click, 'function', '页面应注册 click 委托');
  return doc.__click;
}

test('security: markdown 只放行 http(s)，command:/javascript:/file: 被拦截', () => {
  const entry = {
    qid: 'Q-0001', date: '2026-01-01', category: 'Bug Fix', status: '已验证',
    phenomenon: '链接协议', root_cause: 'rc', solution: 'sol', files: '',
  };
  const html = require(path.join(SRC, 'views.js')).qaDetailHtml(entry, 'n1', '');
  const sent = [];
  const click = clickHandlerOf(html, (msg) => sent.push(msg));
  const ev = (href) => ({
    target: { closest: (s) => (s === 'a.filelink' ? null : { getAttribute: () => href, href, dataset: {} }) },
    preventDefault() { this.__prevented = true; },
  });

  click(ev('https://example.com/a'));
  assert.strictEqual(sent.length, 1, 'http(s) 应转发 openExternal');

  for (const bad of ['command:workbench.action.terminal.sendSequence', 'javascript:alert(1)',
    'file:///c:/Windows/System32/calc.exe', 'vscode://ms-vscode.remote/x']) {
    sent.length = 0;
    const e = ev(bad);
    click(e);
    assert.strictEqual(e.__prevented, true, bad + ' 必须被 preventDefault');
    assert.strictEqual(sent.length, 0, bad + ' 不得触发任何消息');
  }
});

test('security: 属性上下文里的引号被转义（esc 行为验证）', () => {
  // 详情编辑表单把 date/category 用 esc() 拼进 value="…"，不转义引号即可注入属性
  const evil = 'x" onfocus="alert(1)';
  const entry = {
    qid: 'Q-0001', date: evil, category: evil, status: 'Pending',
    phenomenon: 'p', root_cause: 'r', solution: 's', files: '',
  };
  const html = require(path.join(SRC, 'views.js')).qaDetailHtml(entry, 'n2', '');
  assert.ok(html.includes('&quot;'), '双引号必须被转义成 &quot;');
  assert.ok(!/value="[^"]*"[^>]*onfocus=/i.test(html), '不得出现注入的 onfocus 属性');
});

test('views: virtualList 有 placeholder，且不覆盖 container.innerHTML', () => {
  assert.ok(viewsSrc.includes('placeholder(html)'), '缺 placeholder() 会导致空态后列表永久空白');
  assert.ok(!viewsSrc.includes("$('list').innerHTML"), '覆盖 container 会让 spacer 脱钩');
});

test('security: shellSafe 拒绝 shell 元字符', () => {
  const shellSafe = new Function(extSrc.match(/function shellSafe\(s\) \{[\s\S]*?\n\}/)[0]
    + '; return shellSafe;')();
  for (const bad of ['x" ; calc ; echo "', 'a && b', 'a | b', 'a>b', 'a$b', "a'b"]) {
    assert.strictEqual(shellSafe(bad), null, bad + ' 应判为不安全');
  }
  for (const ok of ['python', 'py -3', 'D:\\any-versions\\sdk\\python\\python.exe']) {
    assert.strictEqual(shellSafe(ok), ok, ok + ' 应判为安全');
  }
});

test('hooks: 只摘自己的 group，保留用户 hook', () => {
  assert.ok(extSrc.includes('stripOurs'), '必须有 stripOurs');
  assert.ok(!/hooks\[ev\] = hookEntry\(\);/.test(extSrc), '不得整体覆盖 hooks[ev]');
  assert.ok(!/isOurHook\(cfg, ev\)\) delete cfg\.hooks\[ev\]/.test(extSrc), '卸载不得整键 delete');
});

test('capabilities: 不受信/虚拟工作区均声明不支持', () => {
  assert.strictEqual(pkg.capabilities.untrustedWorkspaces.supported, false);
  assert.strictEqual(pkg.capabilities.virtualWorkspaces.supported, false);
  assert.ok(pkg.scripts.test, '必须有 npm test 入口');
});

test('活动栏容器标题不含字面引号', () => {
  for (const c of pkg.contributes.viewsContainers.activitybar) {
    assert.ok(!/^"|"$/.test(c.title), c.id + ' 标题带引号：' + c.title);
  }
});