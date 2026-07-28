import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizePhoneInput,
  safePostLoginPath,
  validCode,
  validPhone,
  viewFromLocation,
} from "../../web/auth-utils.js";


test("normalizes and validates mainland phone numbers", () => {
  assert.equal(normalizePhoneInput("+86 138-0013-8000"), "13800138000");
  assert.equal(normalizePhoneInput("138 0013 8000"), "13800138000");
  assert.equal(validPhone("13800138000"), true);
  assert.equal(validPhone("12800138000"), false);
});

test("requires exactly six numeric SMS code characters", () => {
  assert.equal(validCode("123456"), true);
  assert.equal(validCode("12345x"), false);
});

test("rejects open redirects and unsafe path delimiters", () => {
  assert.equal(safePostLoginPath("/#ledger"), "/#ledger");
  assert.equal(safePostLoginPath("//evil.example"), "/");
  assert.equal(safePostLoginPath("/\\evil.example"), "/");
  assert.equal(safePostLoginPath("/chat\r\nSet-Cookie:x"), "/");
});

test("restores only known application views", () => {
  assert.equal(viewFromLocation({ hash: "#receipts" }), "receipts");
  assert.equal(viewFromLocation({ hash: "#external" }), "dashboard");
});
