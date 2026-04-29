(() => {
  const createContext = (root) => {
    const INITIAL_PAYLOAD_WAIT_MS = 10000;
    const INITIAL_PAYLOAD_POLL_MS = 140;
    const FALLBACK_IMAGE_PATH = "/assets/images/placeholder-600x600.png";

    const state = {
      loadedOnce: false,
      isSearching: false,
      isLoading: true,
      products: [],
      lastQuery: "",
      apiBaseUrl: "",
      requestedPage: "search",
      language: "",
    };

    const input = document.getElementById("products-search-input");
    const searchButton = document.getElementById("products-search-button");
    const logoLink = root.querySelector(".search-logo-link");
    const track = document.getElementById("product-track");
    const leftArrow = document.getElementById("products-arrow-left");
    const rightArrow = document.getElementById("products-arrow-right");
    const loadingOverlay = document.getElementById("products-loading-overlay");
    const supportButton = document.getElementById("products-support-button");
    const supportLayer = document.getElementById("products-support-layer");
    const supportPopup = document.getElementById("products-support-popup");

    const normalizeText = (value) => String(value || "").trim();
    const normalizeLanguage = (value) => {
      const normalized = normalizeText(value).toLowerCase();
      if (normalized.startsWith("ro")) {
        return "ro";
      }
      if (normalized.startsWith("ru")) {
        return "ru";
      }
      return "";
    };
    const escapeHtml = (value) =>
      String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    const debugLog = (eventName, payload) => {
      const name = normalizeText(eventName) || "event";
      const safePayload = payload && typeof payload === "object" ? payload : {};
      const record = {
        ts: new Date().toISOString(),
        event: name,
        payload: safePayload,
      };
      try {
        const prev = Array.isArray(window.__APTEKA_WIDGET_LOGS__)
          ? window.__APTEKA_WIDGET_LOGS__
          : [];
        const next = prev.concat(record).slice(-250);
        window.__APTEKA_WIDGET_LOGS__ = next;
      } catch (_error) {
        // ignore logging storage errors
      }
      try {
        const level = normalizeText(
          String(safePayload.level || ""),
        ).toLowerCase();
        if (level === "error") {
          console.error("[products-widget]", name, safePayload);
          return;
        }
        if (level === "warn") {
          console.warn("[products-widget]", name, safePayload);
          return;
        }
        console.info("[products-widget]", name, safePayload);
      } catch (_error) {
        // ignore console errors
      }
    };

    const toMoney = (value) => {
      if (typeof value !== "number" || Number.isNaN(value)) {
        return "";
      }
      return `${value.toFixed(2)} MDL`;
    };

    const computeDiscount = (price, discountPrice) => {
      if (
        typeof price !== "number" ||
        typeof discountPrice !== "number" ||
        Number.isNaN(price) ||
        Number.isNaN(discountPrice) ||
        price <= 0 ||
        discountPrice >= price
      ) {
        return null;
      }
      return Math.max(1, Math.round(((price - discountPrice) / price) * 100));
    };

    const resolveImageUrl = (rawUrl) => {
      const imageUrl = normalizeText(rawUrl);
      if (!imageUrl) {
        return "";
      }
      if (imageUrl.startsWith("data:")) {
        return imageUrl;
      }
      if (/^https?:\/\//i.test(imageUrl)) {
        return imageUrl;
      }
      const baseUrl = normalizeText(state.apiBaseUrl);
      if (!baseUrl) {
        return imageUrl;
      }
      try {
        return new URL(imageUrl, baseUrl).href;
      } catch (_error) {
        return imageUrl;
      }
    };

    const resolveUrl = (rawUrl, fallbackBase) => {
      const value = normalizeText(rawUrl);
      if (!value) {
        return "";
      }
      if (/^https?:\/\//i.test(value)) {
        return value;
      }
      try {
        return new URL(value, fallbackBase).href;
      } catch (_error) {
        return value;
      }
    };

    const getPreferredLanguage = () => {
      const docLang = normalizeLanguage(document.documentElement?.lang);
      if (docLang) {
        return docLang;
      }
      const navLang = normalizeLanguage(window.navigator?.language);
      if (navLang) {
        return navLang;
      }
      return "ru";
    };
    const getActiveLanguage = (candidate) =>
      normalizeLanguage(candidate) ||
      normalizeLanguage(state.language) ||
      getPreferredLanguage();

    const getSiteBaseUrl = () => "https://www.kokiko.md";

    const normalizeAptekaHost = (url) => {
      const normalized = normalizeText(url);
      if (!normalized) {
        return "";
      }
      return normalized
        .replace("https://api.apteka.md", "https://www.kokiko.md")
        .replace("http://api.apteka.md", "https://www.kokiko.md")
        .replace("https://www.apteka.md", "https://www.kokiko.md")
        .replace("http://www.apteka.md", "https://www.kokiko.md");
    };

    const buildProductUrl = (rawUrl, slug, language) => {
      const base = getSiteBaseUrl();
      const lang = language === "ro" ? "ro" : "ru";
      const normalizedSlug = normalizeText(slug);
      if (normalizedSlug) {
        return `${base}/${lang}/product/${encodeURIComponent(normalizedSlug)}`;
      }
      const resolved = normalizeAptekaHost(resolveUrl(rawUrl, base));
      if (resolved) {
        return resolved;
      }
      return `${base}/${lang}`;
    };

    const getFallbackImage = () => {
      const baseUrl = normalizeText(state.apiBaseUrl);
      if (!baseUrl) {
        return FALLBACK_IMAGE_PATH;
      }
      try {
        return new URL(FALLBACK_IMAGE_PATH, baseUrl).href;
      } catch (_error) {
        return FALLBACK_IMAGE_PATH;
      }
    };

    const setLoading = (nextValue) => {
      state.isLoading = Boolean(nextValue);
      if (state.isLoading) {
        root.classList.add("is-loading");
        return;
      }
      root.classList.remove("is-loading");
      if (loadingOverlay) {
        loadingOverlay.setAttribute("aria-hidden", "true");
      }
    };

    const extractItems = (payload) => {
      if (Array.isArray(payload?.items)) {
        return payload.items.filter((item) => item && typeof item === "object");
      }
      if (Array.isArray(payload?.results)) {
        return payload.results.filter(
          (item) => item && typeof item === "object",
        );
      }
      if (Array.isArray(payload?.products)) {
        return payload.products.filter(
          (item) => item && typeof item === "object",
        );
      }
      if (Array.isArray(payload?.data?.items)) {
        return payload.data.items.filter(
          (item) => item && typeof item === "object",
        );
      }
      if (Array.isArray(payload?.data?.results)) {
        return payload.data.results.filter(
          (item) => item && typeof item === "object",
        );
      }
      if (Array.isArray(payload?.data?.products)) {
        return payload.data.products.filter(
          (item) => item && typeof item === "object",
        );
      }
      if (Array.isArray(payload)) {
        return payload.filter((item) => item && typeof item === "object");
      }
      return [];
    };

    const mapProduct = (item) => {
      const itemTranslations =
        typeof item.translations === "object" && item.translations
          ? item.translations
          : {};
      const ro =
        typeof itemTranslations.ro === "object" && itemTranslations.ro
          ? itemTranslations.ro
          : {};
      const ru =
        typeof itemTranslations.ru === "object" && itemTranslations.ru
          ? itemTranslations.ru
          : {};
      const preferredLanguage = getActiveLanguage(item.language);
      const fallbackLanguage = preferredLanguage === "ru" ? "ro" : "ru";
      const namePreferred =
        normalizeText(item[`name_${preferredLanguage}`]) ||
        normalizeText(preferredLanguage === "ru" ? ru.name : ro.name);
      const nameFallback =
        normalizeText(item[`name_${fallbackLanguage}`]) ||
        normalizeText(fallbackLanguage === "ru" ? ru.name : ro.name);
      const name =
        namePreferred || nameFallback || normalizeText(item.name) || "?????";
      const manufacturer =
        normalizeText(item.manufacturer) || "Производитель не указан";

      const priceRaw = item.price;
      const discountRaw = item.discountPrice ?? item.discount_price;
      const price = Number(priceRaw);
      const discountPrice = Number(discountRaw);

      let imageUrl =
        resolveImageUrl(item.image) ||
        resolveImageUrl(item.image_url) ||
        resolveImageUrl(item.imageUrl) ||
        resolveImageUrl(item.picture) ||
        resolveImageUrl(item.photo) ||
        resolveImageUrl(item.thumbnail);

      const extractFromObjects = (value) => {
        if (Array.isArray(value)) {
          for (const row of value) {
            if (typeof row === "string") {
              const fromString = resolveImageUrl(row);
              if (fromString) {
                return fromString;
              }
              continue;
            }
            if (!row || typeof row !== "object") {
              continue;
            }
            const fromObject =
              resolveImageUrl(row.full) ||
              resolveImageUrl(row.preview) ||
              resolveImageUrl(row.url) ||
              resolveImageUrl(row.image) ||
              resolveImageUrl(row.src) ||
              resolveImageUrl(row.path);
            if (fromObject) {
              return fromObject;
            }
          }
        }
        if (value && typeof value === "object") {
          return (
            resolveImageUrl(value.full) ||
            resolveImageUrl(value.preview) ||
            resolveImageUrl(value.url) ||
            resolveImageUrl(value.image) ||
            resolveImageUrl(value.src) ||
            resolveImageUrl(value.path)
          );
        }
        return "";
      };

      if (!imageUrl && typeof item.meta === "object" && item.meta) {
        imageUrl =
          resolveImageUrl(item.meta.image) ||
          resolveImageUrl(item.meta.image_url) ||
          resolveImageUrl(item.meta.thumbnail) ||
          extractFromObjects(item.meta.images);
      }
      if (!imageUrl) {
        imageUrl =
          extractFromObjects(item.images) ||
          extractFromObjects(item.gallery) ||
          extractFromObjects(item.photos) ||
          extractFromObjects(item.media);
      }
      if (!imageUrl) {
        imageUrl = getFallbackImage();
      }

      const productId =
        normalizeText(item.id) ||
        normalizeText(item.product_id) ||
        normalizeText(item.productId) ||
        normalizeText(item.item_id) ||
        normalizeText(item.sku);
      const rawUrl =
        normalizeText(item.product_url) ||
        normalizeText(item.productUrl) ||
        normalizeText(item.url) ||
        normalizeText(item.link) ||
        normalizeText(item.permalink) ||
        normalizeText(item.slug);
      const meta = item.meta && typeof item.meta === "object" ? item.meta : {};
      const metaTranslations =
        meta && typeof meta.translations === "object" && meta.translations
          ? meta.translations
          : {};
      const fallbackLang = preferredLanguage === "ru" ? "ro" : "ru";
      const metaTranslationLang =
        metaTranslations &&
        typeof metaTranslations[preferredLanguage] === "object"
          ? metaTranslations[preferredLanguage]
          : {};
      const metaTranslationFallback =
        metaTranslations && typeof metaTranslations[fallbackLang] === "object"
          ? metaTranslations[fallbackLang]
          : {};
      const translationLang =
        typeof itemTranslations[preferredLanguage] === "object" &&
        itemTranslations[preferredLanguage]
          ? itemTranslations[preferredLanguage]
          : {};
      const translationFallback =
        typeof itemTranslations[fallbackLang] === "object" &&
        itemTranslations[fallbackLang]
          ? itemTranslations[fallbackLang]
          : {};
      const slug =
        normalizeText(item.slug_ru) ||
        normalizeText(item.slug_ro) ||
        normalizeText(metaTranslationLang.slug) ||
        normalizeText(metaTranslationFallback.slug) ||
        normalizeText(translationLang.slug) ||
        normalizeText(translationFallback.slug) ||
        normalizeText(item.slug);
      if (!slug && !rawUrl) {
        debugLog("product_link_missing", {
          productId,
          preferredLanguage,
          metaTranslationKeys: Object.keys(metaTranslations || {}),
          translationKeys: Object.keys(itemTranslations || {}),
        });
      }

      return {
        id: productId,
        name,
        manufacturer,
        price: Number.isNaN(price) ? null : price,
        discountPrice: Number.isNaN(discountPrice) ? null : discountPrice,
        imageUrl,
        productSlug: slug,
        productUrl: buildProductUrl(rawUrl, slug, preferredLanguage),
      };
    };

    return {
      root,
      state,
      constants: {
        INITIAL_PAYLOAD_WAIT_MS,
        INITIAL_PAYLOAD_POLL_MS,
      },
      dom: {
        input,
        searchButton,
        logoLink,
        track,
        leftArrow,
        rightArrow,
        loadingOverlay,
        supportButton,
        supportLayer,
        supportPopup,
      },
      ui: {
        renderProducts: () => {},
        updateCarouselControls: () => {},
        toggleSupportPopup: (_nextState) => {},
      },
      actions: {
        searchProducts: (_query) => Promise.resolve(),
        openSupportPopup: () => {},
        openExternalLink: (_url) => {},
      },
      tools: {
        waitForInitialPayload: () => Promise.resolve(false),
      },
      utils: {
        normalizeText,
        normalizeLanguage,
        escapeHtml,
        debugLog,
        toMoney,
        computeDiscount,
        resolveImageUrl,
        resolveUrl,
        getPreferredLanguage,
        getActiveLanguage,
        buildProductUrl,
        getFallbackImage,
        setLoading,
        extractItems,
        mapProduct,
      },
    };
  };

  window.ProductsState = {
    createContext,
  };
})();
