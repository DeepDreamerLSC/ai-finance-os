export function normalizePhoneInput(value) {
  const digits = String(value || "").replace(/\D/g, "");
  return (digits.startsWith("86") && digits.length === 13 ? digits.slice(2) : digits).slice(0, 11);
}

export function validPhone(value) {
  return /^1[3-9]\d{9}$/.test(value);
}

export function validCode(value) {
  return /^\d{6}$/.test(value);
}

export function safePostLoginPath(value) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  if (/[\r\n\\]/.test(value)) return "/";
  return value;
}

export function viewFromLocation(locationLike) {
  const candidate = String(locationLike?.hash || "").replace(/^#/, "");
  return ["dashboard", "chat", "ledger", "import", "receipts"].includes(candidate)
    ? candidate
    : "dashboard";
}
