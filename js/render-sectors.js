/**
 * @file Draw the sector table: the market cap and the weight of every sector
 * that the snapshot holds. A sector row toggles the list of its assets.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} SectorsNamespace
 * @property {(asset: Asset) => HTMLImageElement} [buildLogo] - Build a logo from js/render-list.js.
 * @property {(totals: SectorTotals, refs: SectorRefs) => void} [renderSectors] - Draw the sector table.
 */

/**
 * The element that the sector table writes to.
 * @typedef {object} SectorRefs
 * @property {HTMLElement} body - The table body that holds the rows.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: SectorsNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** A dash marks a value that the snapshot does not hold, so a reader sees a gap and not a zero. */
  const NO_VALUE = "\u2014";

  /** The asset line separates the name from the symbol with a dash. */
  const SEPARATOR = "\u2014";

  /** The table holds three columns: the sector, the market cap, and the weight. */
  const COLUMN_COUNT = 3;

  /** The arrow turns down when the list opens. The stylesheet turns it. */
  const CARET = "\u25B8";

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
    item.className = "sector__item";

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
   * Draw the sector table. One row holds the sector name, the market cap of the
   * sector, and the part of the snapshot total that the sector takes. A click on
   * the row, or on its button, opens the assets of the sector below the row.
   * @param {SectorTotals} totals - The rows in market cap order and the total value.
   * @param {SectorRefs} refs - The element that the table writes to.
   * @returns {void}
   */
  const renderSectors = (totals, refs) => {
    const buildLogo = ns.buildLogo;

    if (typeof buildLogo !== "function") {
      throw new Error("The logo builder from js/render-list.js did not load.");
    }

    const fragment = document.createDocumentFragment();

    totals.rows.forEach((row, index) => {
      const element = document.createElement("tr");
      element.className = "sector-row";

      const detailId = `sector-assets-${index}`;

      const caret = document.createElement("span");
      caret.className = "sector__caret";
      caret.setAttribute("aria-hidden", "true");
      caret.textContent = CARET;

      const label = document.createElement("span");
      label.className = "sector__label";
      label.textContent = row.sector;

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "sector__toggle";
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
      detail.className = "sector__detail";
      detail.id = detailId;
      detail.hidden = true;

      const detailCell = document.createElement("td");
      detailCell.className = "sector__cell";
      detailCell.colSpan = COLUMN_COUNT;

      const list = document.createElement("ul");
      list.className = "sector__assets";

      row.assets.forEach((asset) => {
        list.append(buildAssetLine(asset, buildLogo));
      });

      detailCell.append(list);
      detail.append(detailCell);

      /**
       * Open or close the asset list of one sector.
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
          target.closest(".sector__toggle") !== null
        ) {
          return;
        }

        setOpen(toggle.getAttribute("aria-expanded") !== "true");
      });

      fragment.append(element, detail);
    });

    refs.body.replaceChildren(fragment);

    const built = refs.body.querySelectorAll("tr.sector-row").length;
    const details = refs.body.querySelectorAll("tr.sector__detail").length;

    if (built !== totals.rows.length || details !== totals.rows.length) {
      throw new Error(
        `The sector table holds ${built} rows and ${details} lists for ${totals.rows.length} sectors.`,
      );
    }

    const listed = refs.body.querySelectorAll(".sector__item").length;
    const expected = totals.rows.reduce((sum, row) => sum + row.assetCount, 0);

    if (listed !== expected) {
      throw new Error(
        `The sector lists hold ${listed} assets for ${expected} assets.`,
      );
    }
  };

  ns.renderSectors = renderSectors;
})();
