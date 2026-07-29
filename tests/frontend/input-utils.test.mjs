import assert from "node:assert/strict";
import test from "node:test";

import { insertTextAtCursor, isWeChatBrowser } from "../../web/input-utils.js";


test("insertTextAtCursor writes clipboard speech text into the composer", () => {
  let inputEventCount = 0;
  const input = {
    value: "停车",
    selectionStart: 2,
    selectionEnd: 2,
    setRangeText(text, start, end) {
      this.value = `${this.value.slice(0, start)}${text}${this.value.slice(end)}`;
      this.selectionStart = start + text.length;
      this.selectionEnd = this.selectionStart;
    },
    dispatchEvent() {
      inputEventCount += 1;
    },
    focus() {},
  };
  assert.equal(insertTextAtCursor(input, "112元"), true);
  assert.equal(input.value, "停车 112元");
  assert.equal(inputEventCount, 1);
});


test("WeChat browser detection is explicit", () => {
  assert.equal(isWeChatBrowser("Mozilla/5.0 MicroMessenger/8.0.50"), true);
  assert.equal(isWeChatBrowser("Mozilla/5.0 Safari/605.1.15"), false);
});
