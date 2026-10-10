/**
 * 记忆健康视图（P4）结构自测。
 *
 * 运行：node --test vscode-extension/tests/
 * 或：  node vscode-extension/tests/health-view.test.js
 *
 * 这里只测「生成的 HTML 结构」而不是文本是否出现——之前统计卡的 .num 被写成了
 * .stat 的兄弟节点（多一个 </div>），纯文本断言完全测不出来，只能靠 DOM 层级断言。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { healthHtml, statCardHtml } = require('../src/views');

const NONCE = 'test-nonce-1234';

function countOf(html, re) {
  return (html.match(re) || []).length;
}

test('statCardHtml: .num 必须嵌在 .stat 内部且 div 闭合平衡', () => {
  const html = statCardHtml('总条目', 42);
  assert.ok(html.startsWith('<div class="stat '), '应以 .stat 开头');
  assert.ok(html.endsWith('</div></div>'), '应以两层 </div> 结尾');
  assert.strictEqual(countOf(html, /<div/g), countOf(html, /<\/div>/g),
    'div 开合数量必须相等');
  // .num 出现在 .stat 关闭之前 => 是子节点而非兄弟节点
  assert.ok(html.indexOf('<div class="num">') < html.lastIndexOf('</div>'),
    '.num 必须在 .stat 内部');
  assert.ok(html.includes('>42</div>'), '数值应渲染在 .num 里');
});

test('statCardHtml: 标签与数值都要转义', () => {
  const html = statCardHtml('<img src=x onerror=1>', '<script>');
  assert.ok(!html.includes('<img'), '标签文本必须转义');
  assert.ok(!html.includes('<script>'), '数值文本必须转义');
  assert.ok(html.includes('&lt;img'), '应转义为 &lt;');
});

test('statCardHtml: cls 传入时带样式类', () => {
  assert.ok(statCardHtml('待审冲突', 3, 'warn').includes('class="stat warn"'));
});

test('healthHtml: 把统计卡函数注入 webview 脚本（单一实现）', () => {
  const html = healthHtml({ total: 1 }, NONCE);
  assert.ok(html.includes('const card = function statCardHtml'),
    '应以 statCardHtml.toString() 注入，避免两份实现');
});

test('healthHtml: 渲染 7 张统计卡（含 7 天新增与 7 天召回）', () => {
  const html = healthHtml({ total: 10, added_7d: 2, recalled_7d: 5 }, NONCE);
  assert.ok(html.includes("card('7天新增'"), '应渲染 7 天新增');
  assert.ok(html.includes("card('7天召回'"), '应渲染 7 天召回（recalled_7d）');
  assert.ok(html.includes("card('孤立条目'"), '应渲染孤立条目');
});

test('healthHtml: 重复对 / 冲突行渲染与筛选能力', () => {
  const html = healthHtml({
    duplicate_pairs: [{ a: 'Q-0001', b: 'Q-0002', score: 0.9, keep_hint: 'Q-0001' }],
    conflicts: [{ a: 'Q-0003', b: 'Q-0004', reason: '现象相似但结论不同' }],
  }, NONCE);
  assert.ok(html.includes('近似重复对'), '应有重复对区块');
  assert.ok(html.includes('冲突待审'), '应有冲突区块');
  // 注意：healthHtml 返回的是「webview 脚本源码」，A ↔ B 在运行时才拼出来，
  // 因此这里断言渲染模板而不是最终字符串。
  assert.ok(
    html.includes('↔ </span><span class="qm qid">'),
    '重复对/冲突行应按 A ↔ B 渲染，且两个 QID 各自独立成 span',
  );
  assert.ok(html.includes('esc(x.reason'), '冲突原因应经 esc 渲染');
  assert.ok(html.includes("querySelectorAll('.row')"), '应支持关键字筛选行');
});

test('healthHtml: 所有区块的 QID 都可点击（.qid）并回传 gotoEntry', () => {
  const html = healthHtml({
    duplicate_pairs: [{ a: 'Q-0001', b: 'Q-0002', score: 0.9, keep_hint: 'Q-0001' }],
    conflicts: [{ a: 'Q-0003', b: 'Q-0004', reason: 'r' }],
    stale_pending: ['Q-0005'],
    orphans: ['Q-0006'],
  }, NONCE);
  // 四个区块（重复对/冲突各 2 个 QID + 积压 + 孤立）的模板都要带 .qid
  const qidTpl = '<span class="qm qid">';
  assert.strictEqual(
    countOf(html, new RegExp(qidTpl.replace(/"/g, '\\"'), 'g')),
    6,
    '重复对 a/b、冲突 a/b、积压、孤立 共 6 处 QID 模板',
  );
  // 点击委托：#list 上 closest('.qid') 并 postMessage gotoEntry
  assert.ok(html.includes("closest('.qid')"), '应有 #list 点击委托');
  assert.ok(html.includes("type: 'gotoEntry'"), '应回传 gotoEntry');
  assert.ok(html.includes('cursor:pointer'), 'QID 应有可点击样式提示');
});

test('宿主: gotoEntry 路由到 QaViewProvider.openDetail（与列表视图同一入口）', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'extension.js'), 'utf8');
  assert.ok(src.includes("msg.type === 'gotoEntry'"), 'HealthViewProvider 应处理 gotoEntry');
  assert.ok(
    /gotoEntry[\s\S]{0,200}qaProvider\.openDetail/.test(src),
    'gotoEntry 应路由到 qaProvider.openDetail',
  );
  assert.ok(
    src.includes('new HealthViewProvider(context, qaProvider)'),
    'HealthViewProvider 构造时应注入 qaProvider',
  );
});

test('healthHtml: 刷新消息与错误分支', () => {
  const html = healthHtml({}, NONCE);
  assert.ok(html.includes("type: 'healthRefresh'"), '刷新应回传 healthRefresh');

  const err = healthHtml({ error: 'boom' }, NONCE);
  assert.ok(err.includes('class="err"'), 'error 应渲染成错误块');
  assert.ok(err.includes('boom'), '错误信息应可见');
});

test('healthHtml: 数据经 jsonScript 转义，不会提前闭合 script', () => {
  const html = healthHtml({ conflicts: [{ reason: '</script><img>' }] }, NONCE);
  assert.ok(!html.includes('</script><img>'), '数据中的 </script> 必须被转义');
  assert.ok(html.includes('\\u003c/script>'), '`<` 应转义为 \\u003c（截断 </script 即可）');
});
