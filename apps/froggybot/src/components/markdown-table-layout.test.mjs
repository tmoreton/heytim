import assert from 'node:assert/strict';
import test from 'node:test';

import { fitTableColumns, tableColumnWidths } from './markdown-table-layout.ts';

const node = (type, children = [], content = '') => ({ type, children, content });
const table = (rows) => node('table', [node('tbody', rows.map((row) => node('tr',
  row.map((text) => node('td', [node('textgroup', [node('text', [], text)])])),
)))]);

test('table columns accommodate all rows, with compact identifiers and readable prose', () => {
  const widths = tableColumnWidths(table([
    ['#', 'Task', 'Owner', 'Effort', 'Rationale / source'],
    ['1', 'Publish the hackathon deadline with a verified source link.', 'tmoreton89', 'Low', 'x'.repeat(600)],
  ]));
  assert.deepEqual(widths, [56, 300, 120, 120, 300]);
  assert.deepEqual(fitTableColumns(widths, 280), widths);
});

test('table fills wider desktops without compressing narrow screens', () => {
  assert.deepEqual(fitTableColumns([120, 300], 840), [240, 600]);
  assert.deepEqual(fitTableColumns([120, 300], 420), [120, 300]);
  assert.deepEqual(fitTableColumns([], 840), []);
});

test('font scaling increases column space instead of shrinking text', () => {
  const content = table([['#', 'Rationale / source']]);
  assert.deepEqual(tableColumnWidths(content, 2), tableColumnWidths(content).map((width) => width * 2));
  assert.deepEqual(tableColumnWidths(content, 0.8), tableColumnWidths(content));
});

test('nested formatting and link labels contribute to shared column widths', () => {
  const content = node('table', [node('thead', [node('tr', [node('th', [
    node('strong', [node('text', [], 'A long formatted heading')]),
    node('link', [node('text', [], ' and source')]),
  ])])])]);
  assert.deepEqual(tableColumnWidths(content), [300]);
});
