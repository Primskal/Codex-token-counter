const test=require('node:test');
const assert=require('node:assert/strict');
const {formatTokens}=require('../src/codex_token_monitor/web/format.js');

test('formatTokens keeps sub-thousand values exact and compacts larger token counts',()=>{
  assert.equal(formatTokens(0),'0');
  assert.equal(formatTokens(999),'999');
  assert.equal(formatTokens(1000),'1.0K');
  assert.equal(formatTokens(999949),'999.9K');
  assert.equal(formatTokens(999950),'1.0M');
  assert.equal(formatTokens(1e6),'1.0M');
  assert.equal(formatTokens(1e9),'1.0B');
});

test('formatTokens handles non-finite display input safely',()=>{
  assert.equal(formatTokens(undefined),'0');
  assert.equal(formatTokens(Number.NaN),'0');
});
