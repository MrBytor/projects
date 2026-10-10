import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';

const source = await readFile(new URL('../assets/import-credentials.js', import.meta.url), 'utf8');

test('login download keeps Unicode, quotes CSV cells and neutralises spreadsheet formulas', async () => {
  let download, callback, blob, revoked;
  const document = {
    getElementById: () => ({ addEventListener: (event, handler) => { callback = handler; } }),
    querySelectorAll: () => [
      { cells: ['王 "Jacob", Jr', '@student', 'Start-private'].map(textContent => ({ textContent })) },
      { cells: ['  =1+1', 'normal', 'Start-second'].map(textContent => ({ textContent })) },
    ],
    createElement: () => ({ click() { download = { name: this.download, href: this.href }; } }),
  };
  runInNewContext(source, { document, Blob, URL: {
    createObjectURL: value => { blob = value; return 'blob:local'; },
    revokeObjectURL: value => { revoked = value; },
  }, setTimeout: handler => handler() });
  callback();
  assert.deepEqual(download, { name: 'student-login-details.csv', href: 'blob:local' });
  assert.equal(await blob.text(), '"name","username","initial_password"\r\n"王 ""Jacob"", Jr","\'@student","Start-private"\r\n"\'  =1+1","normal","Start-second"');
  assert.equal(revoked, 'blob:local');
});

test('pages without generated credentials need no download control', () => {
  assert.doesNotThrow(() => runInNewContext(source, { document: { getElementById: () => null } }));
});
