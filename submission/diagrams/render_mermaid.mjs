import { createRequire } from "module";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const require = createRequire("C:/Users/seele/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js");
const { chromium } = require("playwright");
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const diagramsDir = __dirname;
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const edgePath = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const mermaidCdn = "https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js";

const files = [
  "01-系统架构图.mmd",
  "02-RAG检索Pipeline.mmd",
  "03-TTS时序图.mmd",
  "04-改稿状态机.mmd",
  "05-质量门禁.mmd",
  "06-数据流向.mmd",
];

function htmlFor(definition, diagramId) {
  const escaped = JSON.stringify(definition);
  const idLit = JSON.stringify(diagramId);
  return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    html, body {
      margin: 0;
      padding: 0;
      background: #ffffff;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    }
    #stage {
      display: inline-block;
      background: #ffffff;
      padding: 28px 36px;
    }
    #target { background: #ffffff; }
  </style>
</head>
<body>
  <div id="stage"><div id="target"></div></div>
  <script src="${mermaidCdn}"></script>
  <script>
    const definition = ${escaped};
    const diagramId = ${idLit};
    window.renderDone = false;
    window.renderError = "";
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "loose",
      theme: "default",
      fontFamily: "Microsoft YaHei, PingFang SC, sans-serif",
      flowchart: { htmlLabels: true, curve: "basis", padding: 14, useMaxWidth: false },
      sequence: { actorFontFamily: "Microsoft YaHei", noteFontFamily: "Microsoft YaHei", messageFontFamily: "Microsoft YaHei", useMaxWidth: false },
      state: { useMaxWidth: false },
    });
    mermaid.render(diagramId, definition).then(({ svg }) => {
      document.getElementById("target").innerHTML = svg;
      window.renderDone = true;
    }).catch((err) => {
      window.renderError = String(err && err.message ? err.message : err);
      window.renderDone = true;
    });
  </script>
</body>
</html>`;
}

async function launchBrowser() {
  const candidates = [
    { name: "chrome", path: chromePath },
    { name: "edge", path: edgePath },
  ];
  let lastErr;
  for (const c of candidates) {
    if (!fs.existsSync(c.path)) continue;
    try {
      const browser = await chromium.launch({
        executablePath: c.path,
        headless: true,
        args: ["--disable-gpu", "--font-render-hinting=medium"],
      });
      console.log("launched", c.name);
      return browser;
    } catch (err) {
      lastErr = err;
      console.error("launch failed", c.name, err);
    }
  }
  throw lastErr || new Error("no browser");
}

async function renderOne(browser, file, index) {
  const src = path.join(diagramsDir, file);
  const dest = path.join(diagramsDir, file.replace(/\.mmd$/i, ".png"));
  const definition = fs.readFileSync(src, "utf8").trim();
  const page = await browser.newPage({
    viewport: { width: 1800, height: 1400 },
    deviceScaleFactor: 3,
  });
  page.on("pageerror", (err) => console.error("pageerror", file, err));
  try {
    await page.setContent(htmlFor(definition, "diagramSvg" + index), {
      waitUntil: "load",
      timeout: 60000,
    });
    await page.waitForFunction(() => window.renderDone === true, null, { timeout: 45000 });
    const error = await page.evaluate(() => window.renderError);
    if (error) throw new Error(file + " mermaid render failed: " + error);
    await page.waitForSelector("#target svg", { timeout: 10000 });
    await page.waitForTimeout(300);
    const stage = await page.$("#stage");
    if (!stage) throw new Error("missing stage");
    await stage.screenshot({ path: dest, type: "png" });
    const stat = fs.statSync(dest);
    if (stat.size < 2000) throw new Error(path.basename(dest) + " looks empty (" + stat.size + " bytes)");
    console.log("OK", path.basename(dest), stat.size, "bytes");
  } finally {
    await page.close();
  }
}

async function main() {
  const browser = await launchBrowser();
  try {
    for (let i = 0; i < files.length; i++) {
      await renderOne(browser, files[i], i + 1);
    }
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});