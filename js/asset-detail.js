/**
 * @file Build an asset row that opens a detail panel below it. One panel stays
 * open at a time. The module owns the collapse mechanics only. The content
 * module builds the panel body at the first open.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} AssetDetailNamespace
 * @property {(trigger: HTMLElement, options?: AssetDetailOptions) => AssetDetail} [createAssetDetail] - Build a collapsible detail for one asset row.
 */

/**
 * The options for one asset detail.
 * @typedef {object} AssetDetailOptions
 * @property {number} [columns] - The column count that the detail cell spans. Omit it for a drawer line, and the detail becomes a list item.
 * @property {Asset} [asset] - The asset for the panel. The content module reads it and builds the field list.
 * @property {HTMLElement} [body] - A ready body. This value wins over the asset.
 */

/**
 * One collapsible asset detail.
 * @typedef {object} AssetDetail
 * @property {HTMLElement} element - The hidden detail node. Insert it after the trigger row.
 * @property {HTMLButtonElement} toggle - The button that carries the state. The row content goes inside it.
 * @property {HTMLElement} content - The slot for the detail body.
 * @property {(open: boolean) => void} setOpen - Open or close the detail.
 * @property {() => void} close - Close the detail.
 * @property {() => boolean} isOpen - True while the detail shows.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: AssetDetailNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** The id counter, so every detail node takes a unique id. */
  let nextId = 0;

  /** The detail that shows. A new open closes this one, so one panel stays open. */
  let openDetail = null;

  /**
   * Build the panel body for one detail. A ready body wins. Without one, the
   * content module builds the field list from the asset.
   * @param {AssetDetailOptions} options - The caller options.
   * @returns {HTMLElement} The body for the panel.
   * @throws {Error} When no body arrives and the content module is absent.
   */
  const buildBody = (options) => {
    if (options.body instanceof HTMLElement) {
      return options.body;
    }

    const buildFields = ns.buildAssetDetailBody;
    if (options.asset === undefined || typeof buildFields !== "function") {
      throw new Error(
        "The asset detail body builder from js/render-asset-detail.js did not load.",
      );
    }

    return buildFields(options.asset);
  };

  /**
   * Build the collapsible detail for one asset row, and wire the row to it. A
   * press on the row, on any cell, or on the button toggles the panel. A press
   * on the button does not run twice, because the row handler skips it.
   * @param {HTMLElement} trigger - The row that the user presses.
   * @param {AssetDetailOptions} [options] - The shape of the detail node.
   * @returns {AssetDetail} The detail and its controls.
   */
  const createAssetDetail = (trigger, options = {}) => {
    const columns = options.columns;
    const inTable = typeof columns === "number";

    nextId += 1;
    const detailId = `asset-detail-${nextId}`;

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "asset__toggle";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", detailId);

    const content = document.createElement("div");
    content.className = "asset__body";

    /* The body builds at the first open, so a table of 730 rows holds no field
       list until the reader opens one panel. */
    let built = false;

    const element = document.createElement(inTable ? "tr" : "li");
    element.className = "asset__detail";
    element.id = detailId;
    element.hidden = true;

    if (inTable) {
      const cell = document.createElement("td");
      cell.className = "asset__cell";
      cell.colSpan = columns;
      cell.append(content);
      element.append(cell);
    } else {
      element.append(content);
    }

    /**
     * Report whether the panel shows.
     * @returns {boolean} True while the detail shows.
     */
    const isOpen = () => !element.hidden;

    /**
     * Write the open state onto the detail and the button.
     * @param {boolean} open - True shows the panel.
     * @returns {void}
     */
    const setOpen = (open) => {
      if (open) {
        /* One panel at a time. The previous panel closes before this one opens. */
        if (openDetail !== null && openDetail !== detail) {
          openDetail.setOpen(false);
        }
        openDetail = detail;

        if (!built) {
          content.append(buildBody(options));
          built = true;
        }
      } else if (openDetail === detail) {
        openDetail = null;
      }

      element.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };

    /** @type {AssetDetail} */
    const detail = {
      element,
      toggle,
      content,
      setOpen,
      close: () => {
        setOpen(false);
      },
      isOpen,
    };

    /**
     * Swap the open state of this panel.
     * @returns {void}
     */
    const flip = () => {
      setOpen(!isOpen());
    };

    toggle.addEventListener("click", flip);

    /* The whole row takes a press, so the target stays large. The button
       handles its own press and must not run twice. */
    trigger.addEventListener("click", (event) => {
      const target = event.target;

      if (
        target instanceof HTMLElement &&
        target.closest(".asset__toggle") !== null
      ) {
        return;
      }

      flip();
    });

    return detail;
  };

  ns.createAssetDetail = createAssetDetail;
})();
