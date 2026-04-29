(() => {
  const root = document.querySelector("[data-widget-shell]");
  if (!root || typeof window.ProductsState?.createContext !== "function") {
    return;
  }

  const ctx = window.ProductsState.createContext(root);
  window.ProductsRender.attach(ctx);
  if (typeof window.ProductsTheme?.attach === "function") {
    window.ProductsTheme.attach(ctx);
  }
  window.ProductsTools.attach(ctx);
  if (typeof window.ProductsSupport?.attach === "function") {
    window.ProductsSupport.attach(ctx);
  }
  if (typeof ctx.tools?.listenForThemeUpdates === "function") {
    ctx.tools.listenForThemeUpdates();
  }

  const { state, dom, ui, actions, tools, utils } = ctx;
  const { input, searchButton, logoLink, track, leftArrow, rightArrow } = dom;

  const scrollTrack = (direction) => {
    if (!track) {
      return;
    }
    const firstCard = track.querySelector(".product-card");
    const step =
      firstCard instanceof HTMLElement ? firstCard.offsetWidth + 14 : 280;
    track.scrollBy({ left: direction * step, behavior: "smooth" });
    window.setTimeout(ui.updateCarouselControls, 280);
  };

  leftArrow?.addEventListener("click", () => scrollTrack(-1));
  rightArrow?.addEventListener("click", () => scrollTrack(1));
  track?.addEventListener("scroll", ui.updateCarouselControls, {
    passive: true,
  });
  track?.addEventListener("click", (event) => {
    const target =
      event.target instanceof Element
        ? event.target.closest("[data-action]")
        : null;
    if (!(target instanceof HTMLElement)) {
      return;
    }
    if (target.dataset.action === "support-contact") {
      event.preventDefault();
      event.stopPropagation();
      actions.openSupportPopup();
    }
  });

  logoLink?.addEventListener("click", (event) => {
    event.preventDefault();
    if (!(logoLink instanceof HTMLAnchorElement)) {
      return;
    }
    actions.openExternalLink?.(logoLink.href);
  });

  searchButton?.addEventListener("click", (event) => {
    event.preventDefault();
    actions.searchProducts(
      input instanceof HTMLInputElement ? input.value : "",
    );
  });

  input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      actions.searchProducts(input.value);
    }
  });

  window.addEventListener("resize", ui.updateCarouselControls, {
    passive: true,
  });
  if (typeof utils?.setLoading === "function") {
    utils.setLoading(true);
  }
  ui.renderProducts();
  tools.waitForInitialPayload().then(() => {
    if (!state.loadedOnce) {
      state.loadedOnce = true;
      if (typeof utils?.setLoading === "function") {
        utils.setLoading(false);
      }
      ui.renderProducts();
    }
    ui.updateCarouselControls();
  });
})();
