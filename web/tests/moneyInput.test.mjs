import assert from 'node:assert/strict';
import test from 'node:test';
import {parseWon} from '../src/lib/moneyInput.ts';

test('검색 예산의 소수·복합 단위를 원으로 환산한다', () => {
  for (const [input, expected] of [
    ['2.5억', 250000000], ['2억 5000만', 250000000], ['250,000,000원', 250000000],
    ['5천만', 50000000], ['10000만', 100000000], ['0', 0],
  ]) assert.equal(parseWon(input), expected);
});

test('음수·잘못된 입력·안전한 정수 범위 초과를 다른 금액으로 바꾸지 않는다', () => {
  for (const input of ['-2억', 'abc', '2억abc', '9007199254740992']) assert.ok(Number.isNaN(parseWon(input)));
});
