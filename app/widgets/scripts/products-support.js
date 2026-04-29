(() => {
  const attach = (ctx) => {
    const { dom } = ctx;
    const { supportButton, supportLayer, supportPopup } = dom;
    const supportCloseButton = document.getElementById(
      "products-support-close",
    );
    if (
      !(supportButton instanceof HTMLElement) ||
      !(supportLayer instanceof HTMLElement) ||
      !(supportPopup instanceof HTMLElement)
    ) {
      return;
    }
    if (supportLayer.parentElement !== document.body) {
      document.body.append(supportLayer);
    }

    const copyText = (linkEl, text) => {
      const span = linkEl.querySelector("span");
      const originalText = span ? span.textContent : null;
      const showFeedback = (msg) => {
        if (!span) return;
        span.textContent = msg;
        setTimeout(() => {
          span.textContent = originalText;
        }, 1500);
      };
      try {
        const input = document.createElement("input");
        input.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0;";
        input.value = text;
        document.body.appendChild(input);
        input.focus();
        input.select();
        const ok = document.execCommand("copy");
        document.body.removeChild(input);
        showFeedback(ok ? "Скопировано!" : text);
      } catch (_error) {
        showFeedback(text);
      }
    };

    const setOpen = (nextState) => {
      const isOpen = Boolean(nextState);
      supportLayer.hidden = !isOpen;
      supportButton.setAttribute("aria-expanded", String(isOpen));
      supportPopup.classList.toggle("is-open", isOpen);
    };

    const toggle = () => setOpen(supportLayer.hidden);

    supportButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggle();
    });

    supportPopup.addEventListener("click", (event) => {
      event.stopPropagation();
    });

    const supportLinks = supportPopup.querySelectorAll("a[href]");
    for (const link of supportLinks) {
      if (!(link instanceof HTMLAnchorElement)) {
        continue;
      }
      link.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const href = link.getAttribute("href") || "";
        if (!href || href.startsWith("javascript:")) {
          return;
        }
        if (href.startsWith("mailto:")) {
          const email = href.slice("mailto:".length).split("?")[0];
          copyText(link, email);
          return;
        }
        if (href.startsWith("tel:")) {
          const phone = href.slice("tel:".length);
          copyText(link, phone);
          return;
        }
        if (typeof ctx.actions.openExternalLink === "function") {
          ctx.actions.openExternalLink(href);
        }
      });
    }

    if (supportCloseButton instanceof HTMLButtonElement) {
      supportCloseButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      });
    }

    supportLayer.addEventListener("click", (event) => {
      if (event.target === supportLayer) {
        setOpen(false);
      }
    });

    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !supportLayer.hidden) {
        setOpen(false);
      }
    });

    ctx.ui.toggleSupportPopup = (nextState) => {
      if (typeof nextState === "boolean") {
        setOpen(nextState);
        return;
      }
      toggle();
    };

    ctx.actions.openSupportPopup = () => {
      setOpen(true);
    };
  };

  window.ProductsSupport = {
    attach,
  };
})();
