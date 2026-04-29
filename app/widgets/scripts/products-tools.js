(() => {
  const attach = (ctx) => {
    const LAST_SEARCH_QUERY_KEY = "apteka_widget_last_query";
    const { state, dom, constants, utils, theme } = ctx;
    const { input } = dom;
    const { INITIAL_PAYLOAD_WAIT_MS, INITIAL_PAYLOAD_POLL_MS } = constants;
    const {
      normalizeText,
      normalizeLanguage,
      getActiveLanguage,
      extractItems,
      mapProduct,
      setLoading,
      debugLog,
    } = utils;
    const HOST_PROTOCOL_VERSION = "2026-01-26";

    const createHostBridge = () => {
      const targetWindow =
        window.parent && window.parent !== window ? window.parent : window;
      let nextRequestId = 1;
      let initializePromise = null;

      const sendNotification = (method, params) => {
        try {
          targetWindow.postMessage(
            { jsonrpc: "2.0", method, params: params || {} },
            "*",
          );
        } catch (error) {
          debugLog("host_notification_error", {
            method,
            message: String(error?.message ? error.message : error),
            level: "warn",
          });
        }
      };

      const sendRequest = (method, params) =>
        new Promise((resolve, reject) => {
          const requestId = `mcp-ui-${nextRequestId++}`;
          const onMessage = (event) => {
            const payload = event?.data;
            if (
              !payload ||
              typeof payload !== "object" ||
              payload.id !== requestId
            ) {
              return;
            }
            window.removeEventListener("message", onMessage);
            if (payload.error) {
              reject(
                new Error(
                  typeof payload.error.message === "string"
                    ? payload.error.message
                    : "MCP host request failed",
                ),
              );
              return;
            }
            resolve(payload.result || {});
          };
          window.addEventListener("message", onMessage, { passive: true });
          targetWindow.postMessage(
            {
              jsonrpc: "2.0",
              id: requestId,
              method,
              params: params || {},
            },
            "*",
          );
        });

      const initialize = () => {
        if (typeof window.openai?.callTool === "function") {
          return Promise.resolve({});
        }
        if (initializePromise) {
          return initializePromise;
        }
        initializePromise = sendRequest("ui/initialize", {
          protocolVersion: HOST_PROTOCOL_VERSION,
          clientInfo: {
            name: "kokiko-products-widget",
            version: "0.1.0",
          },
          appCapabilities: {
            tools: {},
            availableDisplayModes: ["inline", "fullscreen"],
          },
        })
          .then((result) => {
            sendNotification("ui/notifications/initialized", {});
            return result;
          })
          .catch((error) => {
            initializePromise = null;
            throw error;
          });
        return initializePromise;
      };

      const callTool = async (name, argumentsPayload) => {
        if (typeof window.openai?.callTool === "function") {
          return window.openai.callTool(name, argumentsPayload);
        }
        await initialize();
        return sendRequest("tools/call", {
          name,
          arguments: argumentsPayload || {},
        });
      };

      return {
        initialize,
        callTool,
      };
    };

    const hostBridge = createHostBridge();

    const extractToolPage = (payload) => {
      if (!payload || typeof payload !== "object") {
        return "";
      }
      const widgetNode =
        payload.widget && typeof payload.widget === "object"
          ? payload.widget
          : {};
      const openNode =
        widgetNode.open && typeof widgetNode.open === "object"
          ? widgetNode.open
          : {};
      return (
        normalizeText(openNode.page) ||
        normalizeText(payload.widget_page) ||
        normalizeText(payload.page)
      ).toLowerCase();
    };

    const hasSearchResultsPayload = (payload) => {
      if (!payload || typeof payload !== "object") {
        return false;
      }
      return (
        Array.isArray(payload.products) ||
        Array.isArray(payload.results) ||
        Object.prototype.hasOwnProperty.call(payload, "no_results") ||
        Object.prototype.hasOwnProperty.call(payload, "query")
      );
    };

    const extractInitialToolPayload = () => {
      const candidates = [
        window.__APTEKA_WIDGET_PAYLOAD__,
        window.__MCP_STRUCTURED_CONTENT__,
        window.__MCP_TOOL_RESULT__,
        window.__OPENAI_TOOL_RESULT__,
        window.__INITIAL_TOOL_RESULT__,
        window.openai?.structuredContent,
        window.openai?.toolResult?.structuredContent,
        window.openai?.toolResult,
        window.openai?.toolOutput?.structuredContent,
        window.openai?.toolOutput,
        window.openai?.lastToolResult?.structuredContent,
        window.openai?.lastToolResult,
      ];
      for (const candidate of candidates) {
        if (!candidate || typeof candidate !== "object") {
          continue;
        }
        return candidate.structuredContent &&
          typeof candidate.structuredContent === "object"
          ? candidate.structuredContent
          : candidate;
      }
      return null;
    };

    const extractPayloadFromMessage = (rawMessage) => {
      if (!rawMessage || typeof rawMessage !== "object") {
        return null;
      }
      const candidates = [
        rawMessage.payload,
        rawMessage.data,
        rawMessage.params,
        rawMessage.params?.structuredContent,
        rawMessage.result,
        rawMessage.result?.structuredContent,
        rawMessage.structuredContent,
        rawMessage,
      ];
      for (const candidate of candidates) {
        if (!candidate || typeof candidate !== "object") {
          continue;
        }
        return candidate.structuredContent &&
          typeof candidate.structuredContent === "object"
          ? candidate.structuredContent
          : candidate;
      }
      return null;
    };

    const applyInitialToolPayload = (payload) => {
      if (!payload || typeof payload !== "object") {
        return false;
      }
      const requestedPage = extractToolPage(payload);
      const hasWidgetPayload =
        hasSearchResultsPayload(payload) ||
        Boolean(normalizeText(payload.api_base_url)) ||
        Boolean(normalizeLanguage(payload.language)) ||
        Boolean(requestedPage) ||
        isThemePayload(payload);
      if (!hasWidgetPayload) {
        return false;
      }
      if (normalizeText(payload.api_base_url)) {
        state.apiBaseUrl = normalizeText(payload.api_base_url);
      }
      const language = normalizeLanguage(payload.language);
      if (language) {
        state.language = language;
      }
      if (requestedPage) {
        state.requestedPage = requestedPage;
      }
      theme?.updateFromPayload(payload);
      const query = normalizeText(payload.query);
      if (query) {
        try {
          window.localStorage.setItem(LAST_SEARCH_QUERY_KEY, query);
        } catch (_error) {
          // ignore storage write errors
        }
      }
      const isSearchPayload =
        hasSearchResultsPayload(payload) ||
        !requestedPage ||
        requestedPage === "search";
      if (isSearchPayload) {
        const mapped = extractItems(payload)
          .map(mapProduct)
          .filter((product) => product.id);
        if (query && input) {
          input.value = query;
        }
        state.products = mapped;
        state.lastQuery = query;
        state.loadedOnce = true;
        return true;
      }
      state.loadedOnce = true;
      return true;
    };

    const isThemePayload = (payload) => {
      if (!payload || typeof payload !== "object") {
        return false;
      }
      return (
        typeof payload.theme === "string" ||
        typeof payload.theme_mode === "string" ||
        typeof payload.mode === "string" ||
        typeof payload.auto_disabled === "boolean"
      );
    };

    const listenForThemeUpdates = () => {
      if (!theme || typeof theme.updateFromPayload !== "function") {
        return;
      }
      const extractThemePayloadFromGlobals = () => {
        const candidates = [
          window.__APTEKA_WIDGET_PAYLOAD__,
          window.__MCP_STRUCTURED_CONTENT__,
          window.__MCP_TOOL_RESULT__,
          window.__OPENAI_TOOL_RESULT__,
          window.__INITIAL_TOOL_RESULT__,
          window.openai?.structuredContent,
          window.openai?.toolResult?.structuredContent,
          window.openai?.toolResult,
          window.openai?.toolOutput?.structuredContent,
          window.openai?.toolOutput,
          window.openai?.lastToolResult?.structuredContent,
          window.openai?.lastToolResult,
        ];
        for (const candidate of candidates) {
          if (!candidate || typeof candidate !== "object") {
            continue;
          }
          const payloads = [
            candidate,
            candidate.structuredContent,
            candidate.result,
            candidate.result?.structuredContent,
            candidate.payload,
            candidate.data,
          ];
          for (const payload of payloads) {
            if (
              payload &&
              typeof payload === "object" &&
              isThemePayload(payload)
            ) {
              return payload;
            }
          }
        }
        return null;
      };

      const getThemeSignature = (payload) => {
        if (!payload || typeof payload !== "object") {
          return "";
        }
        const themeValue = normalizeText(payload.theme);
        const modeValue = normalizeText(payload.theme_mode || payload.mode);
        const autoValue =
          typeof payload.auto_disabled === "boolean"
            ? String(payload.auto_disabled)
            : "";
        return [themeValue, modeValue, autoValue].join("|");
      };

      const MAX_STABLE_THEME_TICKS = 50;
      let lastThemeSignature = "";
      const pollThemeUpdates = () => {
        const payload = extractThemePayloadFromGlobals();
        if (!payload) {
          return false;
        }
        const signature = getThemeSignature(payload);
        if (!signature || signature === lastThemeSignature) {
          return false;
        }
        lastThemeSignature = signature;
        theme.updateFromPayload(payload);
        return true;
      };

      const onMessage = (event) => {
        const messagePayload = extractPayloadFromMessage(event?.data);
        if (!isThemePayload(messagePayload)) {
          return;
        }
        theme.updateFromPayload(messagePayload);
      };
      window.addEventListener("message", onMessage, { passive: true });
      let stableTicks = 0;
      const themeIntervalId = window.setInterval(() => {
        const changed = pollThemeUpdates();
        if (changed) {
          stableTicks = 0;
          return;
        }
        stableTicks += 1;
        if (stableTicks >= MAX_STABLE_THEME_TICKS) {
          window.clearInterval(themeIntervalId);
        }
      }, INITIAL_PAYLOAD_POLL_MS);
      pollThemeUpdates();
    };

    const tryHydrateInitialPayload = () => {
      const payload = extractInitialToolPayload();
      if (!payload) {
        return false;
      }
      if (!applyInitialToolPayload(payload)) {
        return false;
      }
      setLoading(false);
      ctx.ui.renderProducts();
      return true;
    };

    const waitForInitialPayload = () =>
      new Promise((resolve) => {
        if (tryHydrateInitialPayload()) {
          resolve(true);
          return;
        }

        const onMessage = (event) => {
          const messagePayload = extractPayloadFromMessage(event?.data);
          if (!messagePayload) {
            return;
          }
          if (!applyInitialToolPayload(messagePayload)) {
            return;
          }
          window.clearInterval(intervalId);
          window.clearTimeout(timeoutId);
          window.removeEventListener("message", onMessage);
          setLoading(false);
          ctx.ui.renderProducts();
          resolve(true);
        };

        window.addEventListener("message", onMessage, { passive: true });

        hostBridge.initialize().catch((error) => {
          debugLog("host_initialize_error", {
            message: String(error?.message ? error.message : error),
            level: "warn",
          });
        });

        const intervalId = window.setInterval(() => {
          if (!tryHydrateInitialPayload()) {
            return;
          }
          window.clearInterval(intervalId);
          window.clearTimeout(timeoutId);
          window.removeEventListener("message", onMessage);
          resolve(true);
        }, INITIAL_PAYLOAD_POLL_MS);

        const timeoutId = window.setTimeout(() => {
          window.clearInterval(intervalId);
          window.removeEventListener("message", onMessage);
          resolve(false);
        }, INITIAL_PAYLOAD_WAIT_MS);
      });

    const searchProducts = async (query) => {
      const normalized = normalizeText(query);
      if (!normalized) {
        return;
      }
      if (state.isSearching) {
        return;
      }

      const language = getActiveLanguage();
      state.language = language;
      state.isSearching = true;
      state.lastQuery = normalized;
      try {
        window.localStorage.setItem(LAST_SEARCH_QUERY_KEY, normalized);
      } catch (_error) {
        // ignore storage write errors
      }
      setLoading(true);

      try {
        const toolResult = await hostBridge.callTool("search_products", {
          query: normalized,
          language,
        });
        const payload =
          (toolResult &&
            typeof toolResult === "object" &&
            toolResult.structuredContent) ||
          toolResult ||
          {};
        if (normalizeText(payload.api_base_url)) {
          state.apiBaseUrl = normalizeText(payload.api_base_url);
        }
        const responseLanguage = normalizeLanguage(payload.language);
        if (responseLanguage) {
          state.language = responseLanguage;
        }
        theme?.updateFromPayload(payload);
        state.requestedPage = "search";
        state.products = extractItems(payload)
          .map(mapProduct)
          .filter((product) => product.id);
      } catch (error) {
        debugLog("search_products_error", {
          message: String(error?.message ? error.message : error),
          level: "error",
        });
        state.products = [];
      } finally {
        state.isSearching = false;
        state.loadedOnce = true;
        setLoading(false);
        ctx.ui.renderProducts();
      }
    };

    ctx.actions.searchProducts = searchProducts;
    ctx.tools.waitForInitialPayload = waitForInitialPayload;
    ctx.tools.listenForThemeUpdates = listenForThemeUpdates;
  };

  window.ProductsTools = {
    attach,
  };
})();
