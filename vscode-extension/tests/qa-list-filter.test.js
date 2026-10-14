/**
 * QA 列表「状态 / 关键词」筛选回归测试。
 *
 * 运行：node --test vscode-extension/tests/
 * 或：  node vscode-extension/tests/qa-list-filter.test.js
 *
 * 缺陷背景：virtualList() 在构造时把 items 作为闭包参数固定持有，返回的 API 只有
 * render/placeholder/select/pick，没有任何替换数据源的手段；而 applyFilter 是把
 * filtered 重新绑定到一个**新数组**再调 list.render()，render() 读到的仍是旧数组。
 * 结果：计数和「无匹配条目」会变，列表行却永远不变 —— 筛选看起来完全没生效。
 *
 * 这里不只做结构断言：把 virtualList 从 views.js 源码里抽出来，用一个最小 DOM 桩
 * 真跑一遍，断言「换掉数据源后渲染出来的行确实变了」，避免再次退化成
 * 「断言里恰好包含某个字符串，但运行时行为是错的」。
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const { qaListHtml, logListHtml } = require('../src/views');

const NONCE = 'test-nonce-1234';
const ROW_H = 26; // 与 src/views.js 里的 COMMON_JS 保持一致

/** 最小 DOM 桩：只实现 virtualList 真正用到的那几个 API。 */
function makeNode(tag) {
  const el = {
    tagName: tag,
    className: '',
    style: {},
    dataset: {},
    children: [],
    parentElement: null,
    _text: '',
    _listeners: {},
    appendChild(c) {
      // 真 DOM 里 appendChild(fragment) 会把 fragment 的子节点搬进来
      if (c.isFragment) {
        for (const g of c.children) { g.parentElement = el; el.children.push(g); }
        c.children.length = 0;
        return c;
      }
      el.children.push(c);
      c.parentElement = el;
      return c;
    },
    addEventListener(type, fn) {
      (el._listeners[type] = el._listeners[type] || []).push(fn);
    },
    fire(type, ev) { for (const f of el._listeners[type] || []) f(ev || {}); },
    classList: {
      add(c) {
        if (!el.className.split(/\s+/).includes(c)) el.className = (el.className + ' ' + c).trim();
      },
      remove(c) {
        el.className = el.className.split(/\s+/).filter((x) => x && x !== c).join(' ');
      },
    },
  };
  Object.defineProperty(el, 'textContent', {
    get() { return el._text; },
    // 置空 = 清掉子节点（update() 靠这个回收旧行）
    set(v) { el._text = String(v); if (v === '') el.children.length = 0; },
    configurable: true,
  });
  Object.defineProperty(el, 'innerHTML', {
    get() { return el.innerHTML_; },
    set(v) { el.innerHTML_ = String(v); el.children.length = 0; },
    configurable: true,
  });
  return el;
}

/** 从 src/views.js 里原样抽出 virtualList 函数源码并执行（不做任何改写）。 */
function loadVirtualList() {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'views.js'), 'utf8');
  const start = src.indexOf('function virtualList(');
  assert.ok(start > 0, 'src/views.js 里应存在 virtualList');
  // 朴素括号配对：函数体内没有带花括号的字符串字面量
  let depth = 0, i = src.indexOf('{', start);
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') {
      depth--;
      if (depth === 0) {
        const body = src.slice(start, j + 1);
        // eslint-disable-next-line no-new-func
        return new Function('document', 'ROW_H', body + '\nreturn virtualList;')(
          { createElement: (t) => makeNode(t), createDocumentFragment: () => {
            const f = makeNode('#fragment');
            f.isFragment = true;
            return f;
          } },
          ROW_H,
        );
      }
    }
  }
  throw new Error('virtualList 函数体括号未闭合');
}

/** 造一个已渲染的列表，返回 { list, container, rows, items }。 */
function setup(count = 3, visibleRows = 20) {
  const container = makeNode('div');
  container.scrollTop = 0;
  container.clientHeight = ROW_H * visibleRows; // 视口高度决定一屏能放下几行
  const virtualList = loadVirtualList();
  const items = [];
  for (let i = 1; i <= count; i++) items.push({ qid: 'Q-' + String(i).padStart(4, '0') });
  const list = virtualList(container, items.slice(), (e) => {
    const row = makeNode('div');
    row.innerHTML = e.qid;
    return row;
  });
  const rows = () => container.children[0].children.map((r) => r.innerHTML);
  return { list, container, rows, items };
}

test('virtualList: 换掉数据源后渲染出的行随之改变（筛选生效）', () => {
  const { list, rows } = setup();
  list.render();
  assert.deepStrictEqual(rows(), ['Q-0001', 'Q-0002', 'Q-0003'], '初始应渲染全部 3 行');

  list.setItems([{ qid: 'Q-0002' }]);
  list.render();

  assert.deepStrictEqual(rows(), ['Q-0002'],
    'setItems + render 后只剩筛选命中的一行（旧实现会仍然渲染 3 行 → 筛选完全没生效）');
});

test('virtualList: 数据源变短时滚动位置要归零，否则列表渲染成空白', () => {
  // 复现真实操作：长列表滚到中后部，再输入关键词筛出一条
  const { list, container, rows } = setup(200, 10);
  list.render();
  container.scrollTop = ROW_H * 150;
  container.fire('scroll');
  assert.ok(rows().length > 0, '滚动后视口内应有行');

  list.setItems([{ qid: 'Q-0042' }]);
  list.render();

  assert.deepStrictEqual(rows(), ['Q-0042'],
    '换数据源后必须回到顶部渲染；否则 from 索引越界，一行都不画 → 空白列表');
});

test('virtualList: 占位与恢复来回切换后仍能正常渲染（清空搜索不残留空态）', () => {
  const { list, rows } = setup();
  list.render();
  list.setItems([]);
  list.placeholder('<div class="empty">无匹配条目</div>');
  assert.strictEqual(rows().length, 0, '空筛选应只剩占位');

  list.setItems([{ qid: 'Q-0001' }]);
  list.render();
  assert.deepStrictEqual(rows(), ['Q-0001'], '清空搜索后列表必须回得来');
});

test('qaListHtml: applyFilter 把筛选结果交给列表（不是只重绑局部变量）', () => {
  const html = qaListHtml({ entries: [{ qid: 'Q-0001', status: 'Pending', phenomenon: 'p' }] }, NONCE);
  assert.ok(/list\.setItems\(\s*filtered\s*\)/.test(html),
    'applyFilter 必须把 filtered 交给 list，否则 render() 只会重画构造时的旧数组');
  assert.ok(html.includes("$('q').addEventListener('input', applyFilter)"), '关键词输入应触发筛选');
  assert.ok(html.includes("$('st').addEventListener('change', applyFilter)"), '状态下拉应触发筛选');
});

test('logListHtml: 同一缺陷的第二个现场，关键词搜索也要接上 setItems', () => {
  const html = logListHtml({ logs: [{ title: 't', content: 'c' }] }, NONCE);
  assert.ok(/list\.setItems\(\s*filtered\s*\)/.test(html),
    'Agent 日志视图用的是同一个 virtualList，同样需要 setItems');
});
