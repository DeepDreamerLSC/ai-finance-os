export function insertTextAtCursor(input, text) {
  const value = String(text || "").trim();
  if (!value) return false;
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
  const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;
  const spacer = start > 0 && !/\s$/.test(input.value.slice(0, start)) ? " " : "";
  input.setRangeText(`${spacer}${value}`, start, end, "end");
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.focus();
  return true;
}

export function isWeChatBrowser(userAgent = "") {
  return /MicroMessenger/i.test(userAgent);
}

export function createVoiceInputController({
  input,
  button,
  notify,
  navigatorRef = navigator,
  windowRef = window,
}) {
  let recognition = null;

  const setListening = (listening) => {
    button.classList.toggle("listening", listening);
    button.setAttribute("aria-pressed", String(listening));
    button.title = listening ? "正在听…" : "语音输入";
  };

  const readClipboard = async () => {
    if (!navigatorRef.clipboard?.readText) return false;
    try {
      const text = await navigatorRef.clipboard.readText();
      if (!insertTextAtCursor(input, text)) return false;
      notify("已把微信语音结果放入输入框");
      return true;
    } catch {
      return false;
    }
  };

  const startBrowserRecognition = () => {
    const Recognition = windowRef.SpeechRecognition || windowRef.webkitSpeechRecognition;
    if (!Recognition) return false;
    if (recognition) {
      recognition.stop();
      return true;
    }
    recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onstart = () => setListening(true);
    recognition.onresult = (event) => {
      const transcript = [...event.results]
        .map((result) => result[0]?.transcript || "")
        .join("");
      if (insertTextAtCursor(input, transcript)) notify("语音已写入输入框");
    };
    recognition.onerror = () => notify("语音识别未完成，请再试一次");
    recognition.onend = () => {
      recognition = null;
      setListening(false);
    };
    recognition.start();
    return true;
  };

  const activate = async () => {
    input.focus();
    if (isWeChatBrowser(navigatorRef.userAgent) && await readClipboard()) return;
    if (startBrowserRecognition()) return;
    if (await readClipboard()) return;
    notify("输入框已聚焦；完成微信语音后，再点一次麦克风即可粘贴");
  };

  button.addEventListener("click", activate);
  return { activate };
}
