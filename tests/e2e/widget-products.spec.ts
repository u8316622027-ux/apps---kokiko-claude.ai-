import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

const inlineWidgetAssets = (html: string) =>
  html
    .replace(
      /<link\s+[^>]*?href=(["'])(\.\/[^"']+?\.css)\1[^>]*?>/gi,
      (_match, _quote, relativePath) => {
        const assetPath = path.resolve(
          process.cwd(),
          "app/widgets",
          relativePath.replace("./", ""),
        );
        const asset = fs.readFileSync(assetPath, "utf-8");
        return `<style>\n${asset}\n</style>`;
      },
    )
    .replace(
      /<script\s+[^>]*?src=(["'])(\.\/[^"']+?\.js)\1[^>]*?>\s*<\/script>/gi,
      (_match, _quote, relativePath) => {
        const assetPath = path.resolve(
          process.cwd(),
          "app/widgets",
          relativePath.replace("./", ""),
        );
        const asset = fs.readFileSync(assetPath, "utf-8");
        return `<script>\n${asset}\n</script>`;
      },
    );

test("products widget shell renders", async ({ page }) => {
  const htmlPath = path.resolve(process.cwd(), "app/widgets/products.html");
  const html = fs.readFileSync(htmlPath, "utf-8");
  const sanitized = html.replace(/<script[\s\S]*?<\/script>/g, "");

  await page.setContent(sanitized, { waitUntil: "domcontentloaded" });

  await expect(
    page.locator('[data-widget-shell="search_products"]'),
  ).toBeVisible();
});

test("products widget falls back for tool-input-partial with direct query field", async ({
  page,
}) => {
  const htmlPath = path.resolve(process.cwd(), "app/widgets/products.html");
  const html = fs.readFileSync(htmlPath, "utf-8");
  const hostShim = `<script>
    (() => {
      const makeToolResult = (query) => ({
        content: [{ type: "text", text: "Found products for " + query }],
        structuredContent: {
          query,
          language: "ru",
          api_base_url: "https://api.apteka.md",
          products: [
            {
              id: "sku-93",
              name: "РўРµСЃС‚ partial",
              manufacturer: "KoKiKo",
              price: 95,
              slug: "partial-slug",
              image: "/images/test.png",
            },
          ],
        },
        isError: false,
      });

      window.addEventListener("message", (event) => {
        const payload = event.data;
        if (!payload || typeof payload !== "object" || !payload.method) {
          return;
        }
        if (payload.method === "ui/initialize") {
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: {
                protocolVersion: "2026-01-26",
                capabilities: {},
                hostContext: { theme: "dark" },
              },
            },
            "*",
          );
          window.postMessage(
            {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-input-partial",
              params: { query: "крем для лица" },
            },
            "*",
          );
          window.postMessage(
            {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: { content: [{ type: "text", text: "Found 10 products." }], isError: false },
            },
            "*",
          );
          return;
        }
        if (payload.method === "tools/call") {
          const query =
            typeof payload.params?.arguments?.query === "string"
              ? payload.params.arguments.query
              : "";
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: makeToolResult(query),
            },
            "*",
          );
        }
      });
    })();
  </script>`;
  const instrumentedHtml = inlineWidgetAssets(html).replace(
    "<head>",
    `<head>${hostShim}`,
  );

  await page.setContent(instrumentedHtml, {
    waitUntil: "domcontentloaded",
  });

  await expect(page.locator(".product-title").first()).toContainText(
    "РўРµСЃС‚ partial",
  );
});

test("products widget can search through MCP host postMessage bridge", async ({
  page,
}) => {
  const htmlPath = path.resolve(process.cwd(), "app/widgets/products.html");
  const html = fs.readFileSync(htmlPath, "utf-8");
  const hostShim = `<script>
    (() => {
      const requests = [];
      const makeToolResult = (query) => ({
        content: [{ type: "text", text: "Found products for " + query }],
        structuredContent: {
          query,
          language: "ru",
          api_base_url: "https://api.apteka.md",
          products: [
            {
              id: "sku-1",
              name: "Тест " + query,
              manufacturer: "KoKiKo",
              price: 120,
              slug: "test-slug",
              image: "/images/test.png",
            },
          ],
        },
        isError: false,
      });

      window.__HOST_REQUESTS__ = requests;
      window.addEventListener("message", (event) => {
        const payload = event.data;
        if (!payload || typeof payload !== "object" || !payload.method) {
          return;
        }
        requests.push(payload);
        if (payload.method === "ui/initialize") {
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: {
                protocolVersion: "2026-01-26",
                capabilities: {},
                hostContext: { theme: "light" },
              },
            },
            "*",
          );
          return;
        }
        if (payload.method === "tools/call") {
          const query =
            typeof payload.params?.arguments?.query === "string"
              ? payload.params.arguments.query
              : "";
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: makeToolResult(query),
            },
            "*",
          );
          return;
        }
        if (payload.method === "ui/open-link") {
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: { isError: false },
            },
            "*",
          );
        }
      });
    })();
  </script>`;
  const instrumentedHtml = inlineWidgetAssets(html).replace(
    "<head>",
    `<head>${hostShim}`,
  );

  await page.setContent(instrumentedHtml, {
    waitUntil: "domcontentloaded",
  });

  await expect
    .poll(async () =>
      page.evaluate(() =>
        Array.isArray(window.__HOST_REQUESTS__)
          ? window.__HOST_REQUESTS__.map((entry) => entry.method)
          : [],
      ),
    )
    .toContain("ui/initialize");

  await page.locator("#products-search-input").fill("куртка");
  await page.locator("#products-search-input").press("Enter");

  await expect(page.locator(".product-title").first()).toContainText(
    "Тест куртка",
  );
  await expect(page.locator(".buy-link").first()).toHaveAttribute(
    "href",
    /test-slug/,
  );
  await page
    .locator(".buy-link")
    .first()
    .evaluate((element) => (element as HTMLAnchorElement).click());

  const requestMethods = await page.evaluate(() =>
    Array.isArray(window.__HOST_REQUESTS__)
      ? window.__HOST_REQUESTS__.map((entry) => entry.method)
      : [],
  );
  expect(requestMethods).toContain("ui/initialize");
  expect(requestMethods).toContain("tools/call");
  expect(requestMethods).toContain("ui/notifications/size-changed");
  expect(requestMethods).toContain("ui/open-link");

  const initializePayload = await page.evaluate(() =>
    Array.isArray(window.__HOST_REQUESTS__)
      ? window.__HOST_REQUESTS__.find(
          (entry) => entry.method === "ui/initialize",
        )?.params
      : null,
  );
  expect(initializePayload?.appInfo?.name).toBe("kokiko-products-widget");
  expect(initializePayload?.appCapabilities?.availableDisplayModes).toContain(
    "inline",
  );
});

test("products widget hydrates from host tool-result notification", async ({
  page,
}) => {
  const htmlPath = path.resolve(process.cwd(), "app/widgets/products.html");
  const html = fs.readFileSync(htmlPath, "utf-8");
  const hostShim = `<script>
    (() => {
      const toolResult = {
        content: [{ type: "text", text: "Found 1 product." }],
        structuredContent: {
          query: "крем",
          language: "ru",
          api_base_url: "https://api.apteka.md",
          products: [
            {
              id: "sku-42",
              name: "Тест крем",
              manufacturer: "KoKiKo",
              price: 99,
              slug: "test-cream",
              image: "/images/test.png",
            },
          ],
        },
        isError: false,
      };

      window.addEventListener("message", (event) => {
        const payload = event.data;
        if (!payload || typeof payload !== "object" || !payload.method) {
          return;
        }
        if (payload.method === "ui/initialize") {
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: {
                protocolVersion: "2026-01-26",
                capabilities: {},
                hostContext: { theme: "light" },
              },
            },
            "*",
          );
          window.postMessage(
            {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: toolResult,
            },
            "*",
          );
        }
      });
    })();
  </script>`;
  const instrumentedHtml = inlineWidgetAssets(html).replace(
    "<head>",
    `<head>${hostShim}`,
  );

  await page.setContent(instrumentedHtml, {
    waitUntil: "domcontentloaded",
  });

  await expect(page.locator(".product-title").first()).toContainText(
    "Тест крем",
  );
});

test("products widget hydrates from host message with result.structuredContent", async ({
  page,
}) => {
  const htmlPath = path.resolve(process.cwd(), "app/widgets/products.html");
  const html = fs.readFileSync(htmlPath, "utf-8");
  const hostShim = `<script>
    (() => {
      const toolResult = {
        content: [{ type: "text", text: "Found 1 product." }],
        structuredContent: {
          query: "сыворотка",
          language: "ru",
          api_base_url: "https://api.apteka.md",
          products: [
            {
              id: "sku-77",
              name: "Тест сыворотка",
              manufacturer: "KoKiKo",
              price: 111,
              slug: "test-serum",
              image: "/images/test.png",
            },
          ],
        },
        isError: false,
      };

      window.addEventListener("message", (event) => {
        const payload = event.data;
        if (!payload || typeof payload !== "object" || !payload.method) {
          return;
        }
        if (payload.method === "ui/initialize") {
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: {
                protocolVersion: "2026-01-26",
                capabilities: {},
                hostContext: { theme: "dark" },
              },
            },
            "*",
          );
          window.postMessage(
            {
              jsonrpc: "2.0",
              result: toolResult,
            },
            "*",
          );
        }
      });
    })();
  </script>`;
  const instrumentedHtml = inlineWidgetAssets(html).replace(
    "<head>",
    `<head>${hostShim}`,
  );

  await page.setContent(instrumentedHtml, {
    waitUntil: "domcontentloaded",
  });

  await expect(page.locator(".product-title").first()).toContainText(
    "Тест сыворотка",
  );
});

test("products widget falls back to tools/call when tool-result misses structuredContent", async ({
  page,
}) => {
  const htmlPath = path.resolve(process.cwd(), "app/widgets/products.html");
  const html = fs.readFileSync(htmlPath, "utf-8");
  const hostShim = `<script>
    (() => {
      const requests = [];
      const makeToolResult = (query) => ({
        content: [{ type: "text", text: "Found products for " + query }],
        structuredContent: {
          query,
          language: "ru",
          api_base_url: "https://api.apteka.md",
          products: [
            {
              id: "sku-91",
              name: "Тест fallback",
              manufacturer: "KoKiKo",
              price: 100,
              slug: "fallback-slug",
              image: "/images/test.png",
            },
          ],
        },
        isError: false,
      });

      window.__HOST_REQUESTS__ = requests;
      window.addEventListener("message", (event) => {
        const payload = event.data;
        if (!payload || typeof payload !== "object" || !payload.method) {
          return;
        }
        requests.push(payload);
        if (payload.method === "ui/initialize") {
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: {
                protocolVersion: "2026-01-26",
                capabilities: {},
                hostContext: { theme: "dark" },
              },
            },
            "*",
          );
          window.postMessage(
            {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-input",
              params: { arguments: { query: "крем для лица", language: "ru" } },
            },
            "*",
          );
          window.postMessage(
            {
              jsonrpc: "2.0",
              method: "ui/notifications/tool-result",
              params: { content: [{ type: "text", text: "Found 6 products." }], isError: false },
            },
            "*",
          );
          return;
        }
        if (payload.method === "tools/call") {
          const query =
            typeof payload.params?.arguments?.query === "string"
              ? payload.params.arguments.query
              : "";
          window.postMessage(
            {
              jsonrpc: "2.0",
              id: payload.id,
              result: makeToolResult(query),
            },
            "*",
          );
        }
      });
    })();
  </script>`;
  const instrumentedHtml = inlineWidgetAssets(html).replace(
    "<head>",
    `<head>${hostShim}`,
  );

  await page.setContent(instrumentedHtml, {
    waitUntil: "domcontentloaded",
  });

  await expect(page.locator(".product-title").first()).toContainText(
    "Тест fallback",
  );
});
