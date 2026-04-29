(() => {
  const attach = (ctx) => {
    const { state, dom, utils } = ctx;
    const { track, leftArrow, rightArrow } = dom;
    const {
      normalizeText,
      escapeHtml,
      toMoney,
      computeDiscount,
      getFallbackImage,
      getActiveLanguage,
      debugLog,
    } = utils;

    const updateCarouselControls = () => {
      if (!track || !leftArrow || !rightArrow) {
        return;
      }
      const canScroll = track.scrollWidth > track.clientWidth + 2;
      const maxScroll = Math.max(0, track.scrollWidth - track.clientWidth);
      leftArrow.disabled = !canScroll || track.scrollLeft <= 2;
      rightArrow.disabled = !canScroll || track.scrollLeft >= maxScroll - 2;
    };

    const renderProducts = () => {
      if (!track) {
        return;
      }

      if (state.isLoading || !state.loadedOnce) {
        track.innerHTML = `
          <article class="skeleton-card" aria-hidden="true">
            <div class="skeleton-block skeleton-image"></div>
            <div class="skeleton-block skeleton-title"></div>
            <div class="skeleton-block skeleton-title"></div>
            <div class="skeleton-block skeleton-meta"></div>
            <div class="skeleton-block skeleton-price"></div>
            <div class="skeleton-block skeleton-button"></div>
          </article>
          <article class="skeleton-card" aria-hidden="true">
            <div class="skeleton-block skeleton-image"></div>
            <div class="skeleton-block skeleton-title"></div>
            <div class="skeleton-block skeleton-title"></div>
            <div class="skeleton-block skeleton-meta"></div>
            <div class="skeleton-block skeleton-price"></div>
            <div class="skeleton-block skeleton-button"></div>
          </article>
          <article class="skeleton-card" aria-hidden="true">
            <div class="skeleton-block skeleton-image"></div>
            <div class="skeleton-block skeleton-title"></div>
            <div class="skeleton-block skeleton-title"></div>
            <div class="skeleton-block skeleton-meta"></div>
            <div class="skeleton-block skeleton-price"></div>
            <div class="skeleton-block skeleton-button"></div>
          </article>
        `;
        updateCarouselControls();
        return;
      }

      if (!state.products.length) {
        const language = getActiveLanguage();
        const emptyCopy =
          language === "ro"
            ? {
                title: "Produsul nu a fost găsit",
              }
            : {
                title: "Товар не найден",
              };
        track.innerHTML = `
          <article class="product-card product-card--empty" role="status" aria-live="polite">
            <div class="empty-state">
              <div class="empty-state-icon" aria-hidden="true">
                <svg viewBox="0 0 64 64" aria-hidden="true">
                  <path d="M20 16h18l10 10v22a4 4 0 0 1-4 4H20a4 4 0 0 1-4-4V20a4 4 0 0 1 4-4z"></path>
                  <path d="M38 16v10h10"></path>
                  <circle cx="28" cy="42" r="6.5"></circle>
                  <path d="M33 46l6 6"></path>
                  <path d="M24 28h12"></path>
                  <path d="M24 32h16"></path>
                </svg>
              </div>
              <h3 class="empty-state-title">${escapeHtml(emptyCopy.title)}</h3>
            </div>
          </article>
        `;
        track.classList.add("product-track--empty");
        updateCarouselControls();
        return;
      }

      track.classList.remove("product-track--empty");
      track.innerHTML = state.products
        .map((product) => {
          const hasBasePrice =
            typeof product.price === "number" && product.price > 0;
          const hasDiscountPrice =
            typeof product.discountPrice === "number" &&
            product.discountPrice > 0;
          const hasDiscount =
            hasBasePrice &&
            hasDiscountPrice &&
            product.discountPrice < product.price;
          const effectivePrice = hasDiscount
            ? product.discountPrice
            : hasBasePrice
              ? product.price
              : null;
          const discount = hasDiscount
            ? computeDiscount(product.price, product.discountPrice)
            : null;
          const discountBadge = discount
            ? `<span class="discount">-${discount}%</span>`
            : "";
          const oldPriceLine = hasDiscount
            ? `<p class="old-price">${toMoney(product.price)} ${discountBadge}</p>`
            : "";
          const inStock = typeof effectivePrice === "number";
          const priceLine = inStock
            ? `<p class="new-price">${toMoney(effectivePrice)}</p>`
            : '<p class="new-price is-unavailable">Нет в наличии</p>';
          const safeProductUrl = escapeHtml(
            normalizeText(product.productUrl) || "https://www.kokiko.md/",
          );
          const actionButton = inStock
            ? `<a class="buy-link" href="${safeProductUrl}" target="_blank" rel="noopener noreferrer">Купить</a>`
            : `<button class="add-to-cart-button add-to-cart-button--ghost" data-action="support-contact" data-product-id="${escapeHtml(product.id)}">Уточнить наличие</button>`;
          const safeImageUrl = escapeHtml(product.imageUrl);
          const safeName = escapeHtml(product.name);
          const safeManufacturer = escapeHtml(product.manufacturer);
          const safeFallbackImage = escapeHtml(getFallbackImage());
          const safeProductId = escapeHtml(product.id);

          return `
            <article class="product-card ${inStock ? "" : "is-unavailable"}" data-product-id="${safeProductId}">
              <img
                class="product-image"
                src="${safeImageUrl}"
                alt="${safeName}"
                loading="lazy"
                onerror="this.onerror=null;this.src='${safeFallbackImage}'"
              />
              <h3 class="product-title">${safeName}</h3>
              <div class="product-manufacturer-row">
                <p class="manufacturer">${safeManufacturer}</p>
              </div>
              <div class="product-price-row">${oldPriceLine}</div>
              ${priceLine}
              ${actionButton}
            </article>
          `;
        })
        .join("");

      const supportButtons = track.querySelectorAll(
        '[data-action="support-contact"]',
      );
      for (const button of supportButtons) {
        if (!(button instanceof HTMLElement)) {
          continue;
        }
        button.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          if (typeof ctx.actions.openSupportPopup === "function") {
            ctx.actions.openSupportPopup(button);
          }
        });
      }

      const buyLinks = track.querySelectorAll(".buy-link");
      for (const link of buyLinks) {
        if (!(link instanceof HTMLAnchorElement)) {
          continue;
        }
        link.addEventListener("click", (event) => {
          event.preventDefault();
          if (typeof ctx.actions.openExternalLink === "function") {
            ctx.actions.openExternalLink(link.href);
          }
          debugLog("buy_link_click", { url: link.href });
        });
      }

      updateCarouselControls();
    };

    ctx.ui.updateCarouselControls = updateCarouselControls;
    ctx.ui.renderProducts = renderProducts;
  };

  window.ProductsRender = {
    attach,
  };
})();
