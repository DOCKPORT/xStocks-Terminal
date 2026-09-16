/**
 * @file Draw the region table: the market cap and the weight of every listing
 * country that the snapshot holds. A region row toggles the list of its assets.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} RegionsNamespace
 * @property {(asset: Asset) => HTMLImageElement} [buildLogo] - Build a logo from js/render-list.js.
 * @property {(totals: RegionTotals, refs: RegionRefs) => void} [renderRegion] - Draw the region table.
 */

/**
 * The element that the region table writes to.
 * @typedef {object} RegionRefs
 * @property {HTMLElement} body - The table body that holds the rows.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: RegionsNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** A dash marks a value that the snapshot does not hold, so a reader sees a gap and not a zero. */
  const NO_VALUE = "\u2014";

  /** The asset line separates the name from the symbol with a dash. */
  const SEPARATOR = "\u2014";

  /** The table holds three columns: the region, the market cap, and the weight. */
  const COLUMN_COUNT = 3;

  /** The arrow turns down when the list opens. The stylesheet turns it. */
  const CARET = "\u25B8";

  /** The word that marks an asset without a listing country. js/metrics.js writes the same word. */
  const UNKNOWN_REGION = "unknown";

  /* The column drops trailing zeros, so a round value reads "$5K" and not
     "$5.00K". A long value keeps two decimals, for example "$143.99M". */
  const CAP = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });

  const WEIGHT = new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  /* The country names come from the browser, so no list goes stale when the API
     adds a country. A browser without the API shows the code itself. */
  const REGION_NAMES =
    typeof Intl.DisplayNames === "function"
      ? new Intl.DisplayNames(["en"], { type: "region" })
      : null;

  /**
   * Turn one country code into a display name.
   * @param {string} code - The country code from the snapshot, or "unknown".
   * @returns {string} The country name. A code that the browser does not know stays as it stands.
   */
  const regionLabel = (code) => {
    if (REGION_NAMES === null || code === UNKNOWN_REGION) {
      return code;
    }

    try {
      return REGION_NAMES.of(code) || code;
    } catch {
      /* The API holds a code that the browser rejects. Show the code. */
      return code;
    }
  };

  /**
   * Build one cell that holds a number.
   * @param {string} className - The classes for the cell.
   * @param {string} text - The text for the cell.
   * @returns {HTMLTableCellElement} The cell.
   */
  const buildNumberCell = (className, text) => {
    const cell = document.createElement("td");
    cell.className = className;
    cell.textContent = text;
    return cell;
  };

  /**
   * Build one line of the asset list: the logo, the name, and the symbol. The
   * stylesheet draws the line with the same rule as the asset table.
   * @param {Asset} asset - The asset for the line.
   * @param {(asset: Asset) => HTMLImageElement} buildLogo - The shared logo builder.
   * @returns {HTMLLIElement} The line.
   */
  const buildAssetLine = (asset, buildLogo) => {
    const item = document.createElement("li");
    item.className = "region__item";

    const wrapper = document.createElement("div");
    wrapper.className = "table__asset";

    const label = document.createElement("span");
    label.className = "table__name";
    label.textContent = asset.name;

    const separator = document.createElement("span");
    separator.className = "table__sep";
    separator.setAttribute("aria-hidden", "true");
    separator.textContent = SEPARATOR;

    const symbol = document.createElement("span");
    symbol.className = "table__sym";
    symbol.textContent = asset.symbol;

    wrapper.append(buildLogo(asset), label, separator, symbol);
    item.append(wrapper);

    return item;
  };

  /**
   * Draw the region table. One row holds the country, the market cap of the
   * region, and the part of the snapshot total that the region takes. A click on
   * the row, or on its button, opens the assets of the region below the row.
   * @param {RegionTotals} totals - The rows in market cap order and the total value.
   * @param {RegionRefs} refs - The element that the table writes to.
   * @returns {void}
   */
  const renderRegion = (totals, refs) => {
    const buildLogo = ns.buildLogo;

    if (typeof buildLogo !== "function") {
      throw new Error("The logo builder from js/render-list.js did not load.");
    }

    const fragment = document.createDocumentFragment();

    totals.rows.forEach((row, index) => {
      const element = document.createElement("tr");
      element.className = "region-row";

      const detailId = `region-assets-${index}`;

      const caret = document.createElement("span");
      caret.className = "region__caret";
      caret.setAttribute("aria-hidden", "true");
      caret.textContent = CARET;

      const label = document.createElement("span");
      label.className = "region__label";
      label.textContent = regionLabel(row.region);

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "region__toggle";
      toggle.setAttribute("aria-expanded", "false");
      toggle.setAttribute("aria-controls", detailId);
      toggle.append(caret, label);

      const nameCell = document.createElement("td");
      nameCell.className = "col-asset";
      nameCell.append(toggle);

      const capText =
        row.marketCap === null ? NO_VALUE : CAP.format(row.marketCap);
      const weightText =
        row.marketCap === null || totals.total === 0
          ? NO_VALUE
          : WEIGHT.format(row.marketCap / totals.total);

      element.append(
        nameCell,
        buildNumberCell("is-numeric table__cap", capText),
        buildNumberCell("is-numeric table__share", weightText),
      );

      const detail = document.createElement("tr");
      detail.className = "region__detail";
      detail.id = detailId;
      detail.hidden = true;

      const detailCell = document.createElement("td");
      detailCell.className = "region__cell";
      detailCell.colSpan = COLUMN_COUNT;

      const list = document.createElement("ul");
      list.className = "region__assets";

      row.assets.forEach((asset) => {
        list.append(buildAssetLine(asset, buildLogo));
      });

      detailCell.append(list);
      detail.append(detailCell);

      /**
       * Open or close the asset list of one region.
       * @param {boolean} open - True shows the list.
       * @returns {void}
       */
      const setOpen = (open) => {
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        detail.hidden = !open;
      };

      toggle.addEventListener("click", () => {
        setOpen(toggle.getAttribute("aria-expanded") !== "true");
      });

      /* The whole row takes a click, so the target stays large. The button
         handles its own click and must not run twice. */
      element.addEventListener("click", (event) => {
        const target = event.target;

        if (
          target instanceof HTMLElement &&
          target.closest(".region__toggle") !== null
        ) {
          return;
        }

        setOpen(toggle.getAttribute("aria-expanded") !== "true");
      });

      fragment.append(element, detail);
    });

    refs.body.replaceChildren(fragment);

    const built = refs.body.querySelectorAll("tr.region-row").length;
    const details = refs.body.querySelectorAll("tr.region__detail").length;

    if (built !== totals.rows.length || details !== totals.rows.length) {
      throw new Error(
        `The region table holds ${built} rows and ${details} lists for ${totals.rows.length} regions.`,
      );
    }

    const listed = refs.body.querySelectorAll(".region__item").length;
    const expected = totals.rows.reduce((sum, row) => sum + row.assetCount, 0);

    if (listed !== expected) {
      throw new Error(
        `The region lists hold ${listed} assets for ${expected} assets.`,
      );
    }
  };

  ns.renderRegion = renderRegion;
})();
