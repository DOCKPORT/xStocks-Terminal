/**
 * @file Render the asset table and filter it by name or symbol. The file also
 * holds the shared row rules: the row logo, and the grouped table that draws the
 * sector table and the region table.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} ListNamespace
 * @property {(asset: Asset) => HTMLImageElement} [buildLogo] - Build the row logo, with a letter tile as the fallback.
 * @property {(assets: Asset[], refs: ListRefs) => () => void} [renderList] - Draw the table.
 * @property {(config: GroupTableConfig) => (totals: SectorTotals | RegionTotals, refs: { body: HTMLElement }) => void} [createGroupTable] - Build the renderer for the sector table or the region table.
 */

/**
 * The config for one grouped table.
 * @typedef {object} GroupTableConfig
 * @property {string} name - The table name. It drives every class name and every detail id, for example "sector" gives "sector-row" and "sector__item".
 * @property {(row: SectorRow | RegionRow) => string} labelOf - The reader for the label of one group row.
 */

/**
 * @typedef {object} ListRefs
 * @property {HTMLElement} body - The table body that holds the rows.
 * @property {HTMLElement} status - The live region that reports the filter result.
 * @property {HTMLInputElement} input - The search field.
 */

/**
 * @typedef {object} Row
 * @property {HTMLTableRowElement} element - The table row.
 * @property {AssetDetail} detail - The collapsible detail that pairs with the row.
 * @property {string} haystack - The lower-case name and symbol.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: ListNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  const LOGO_DIR = "data/logos";
  const LOGO_SIZE = 40;
  const ORDER = new Intl.Collator("en", { sensitivity: "base", numeric: true });

  /** The asset list holds one column, so the detail cell spans one column. */
  const COLUMN_COUNT = 1;

  /**
   * Build the logo for one row. The image loads when the row nears the viewport,
   * so a table of 730 rows holds no 730 image requests at load. If the file is
   * missing, a letter tile takes its place, so a broken logo stays visible
   * instead of vanishing.
   * @param {Asset} asset - The asset for the row.
   * @returns {HTMLImageElement} The logo image.
   */
  const buildLogo = (asset) => {
    const image = document.createElement("img");
    image.className = "table__logo";
    image.src = `${LOGO_DIR}/${asset.symbol}.png`;
    image.alt = "";
    image.width = LOGO_SIZE;
    image.height = LOGO_SIZE;
    image.decoding = "async";
    /* The mode is a hint. A browser that holds no support loads the image at
       once, the same rule as before. */
    image.loading = "lazy";
    image.addEventListener("error", () => {
      const fallback = document.createElement("span");
      fallback.className = "table__logo table__logo--empty";
      fallback.setAttribute("aria-hidden", "true");
      fallback.textContent = asset.symbol.charAt(0).toUpperCase();
      image.replaceWith(fallback);
    });
    return image;
  };

  /**
   * Build the content of one row: the logo, the name, and the symbol. One flex
   * row keeps the logo at full size, whatever width the column takes.
   * @param {Asset} asset - The asset for the row.
   * @returns {HTMLDivElement} The content of the row.
   */
  const buildAssetContent = (asset) => {
    const wrapper = document.createElement("div");
    wrapper.className = "table__asset";

    const label = document.createElement("span");
    label.className = "table__name";
    label.textContent = asset.name;

    const separator = document.createElement("span");
    separator.className = "table__sep";
    separator.setAttribute("aria-hidden", "true");
    separator.textContent = "\u2014";

    const symbol = document.createElement("span");
    symbol.className = "table__sym";
    symbol.textContent = asset.symbol;

    wrapper.append(buildLogo(asset), label, separator, symbol);

    return wrapper;
  };

  /**
   * Build one row and its detail panel. Text goes in as a text node, never as
   * markup. The whole row toggles the panel below it.
   * @param {Asset} asset - The asset for the row.
   * @param {(trigger: HTMLElement, options?: AssetDetailOptions) => AssetDetail} createDetail - The shared detail builder.
   * @returns {Row} The row, its detail, and its search text.
   */
  const buildRow = (asset, createDetail) => {
    const element = document.createElement("tr");
    element.className = "asset-row";

    const detail = createDetail(element, {
      columns: COLUMN_COUNT,
      asset,
    });

    const cell = document.createElement("td");
    cell.className = "col-asset";
    detail.toggle.append(buildAssetContent(asset));
    cell.append(detail.toggle);
    element.append(cell);

    return {
      element,
      detail,
      haystack: `${asset.name} ${asset.symbol}`.toLowerCase(),
    };
  };

  /**
   * Copy the list into alphabetical order by name, then by symbol.
   * @param {Asset[]} assets - The asset list in file order.
   * @returns {Asset[]} A new list in display order.
   */
  const sortAssets = (assets) =>
    [...assets].sort(
      (a, b) => ORDER.compare(a.name, b.name) || ORDER.compare(a.symbol, b.symbol),
    );

  /**
   * Render every asset row and wire the search field.
   * @param {Asset[]} assets - The asset snapshot.
   * @param {ListRefs} refs - The elements that the list writes to.
   * @returns {() => void} A function that applies the current query.
   */
  const renderList = (assets, refs) => {
    const createDetail = ns.createAssetDetail;

    if (typeof createDetail !== "function") {
      throw new Error(
        "The asset detail builder from js/asset-detail.js did not load.",
      );
    }

    const total = assets.length;
    const fragment = document.createDocumentFragment();

    /** @type {Row[]} */
    const rows = [];

    for (const asset of sortAssets(assets)) {
      const row = buildRow(asset, createDetail);
      rows.push(row);
      fragment.append(row.element, row.detail.element);
    }

    refs.body.replaceChildren(fragment);

    const logoTotal = refs.body.querySelectorAll(".table__logo").length;
    if (logoTotal !== total) {
      throw new Error(`The rows hold ${logoTotal} logos for ${total} assets.`);
    }

    const detailTotal = refs.body.querySelectorAll("tr.asset__detail").length;
    if (detailTotal !== total) {
      throw new Error(
        `The rows hold ${detailTotal} details for ${total} assets.`,
      );
    }

    /**
     * Show the rows that match the current query. Rows are toggled, not rebuilt,
     * so the browser never reloads a logo. A row that leaves the list closes its
     * detail, so no panel stays open on its own.
     * @returns {void}
     */
    const applyQuery = () => {
      const query = refs.input.value.trim().toLowerCase();
      let visible = 0;

      for (const row of rows) {
        const matches = query === "" || row.haystack.includes(query);
        row.element.hidden = !matches;

        if (matches) {
          visible += 1;
        } else {
          row.detail.close();
        }
      }

      if (query === "") {
        refs.status.textContent = `Showing all ${total} assets.`;
        return;
      }

      if (visible === 0) {
        refs.status.textContent = `No assets match "${query}".`;
        return;
      }

      refs.status.textContent = `Showing ${visible} of ${total} assets.`;
    };

    refs.input.addEventListener("input", applyQuery);

    refs.input.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && refs.input.value !== "") {
        refs.input.value = "";
        applyQuery();
      }
    });

    applyQuery();

    return applyQuery;
  };

  /** A dash marks a value that the snapshot does not hold, so a reader sees a gap and not a zero. */
  const NO_VALUE = "\u2014";

  /** The asset line separates the name from the symbol with a dash. */
  const SEPARATOR = "\u2014";

  /** The grouped table holds three columns: the group, the market cap, and the weight. */
  const GROUP_COLUMN_COUNT = 3;

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
   * Build one line of the asset list of one group: the logo, the name, the
   * symbol, and the market cap. A missing value shows a dash, so a reader sees a
   * gap and not a zero. The whole line toggles a detail panel below it.
   * @param {MarketCapRow} row - The asset for the line and its market cap.
   * @param {string} itemClass - The class for the list item.
   * @param {(asset: Asset) => HTMLImageElement} sharedLogo - The shared logo builder.
   * @param {(trigger: HTMLElement, options?: AssetDetailOptions) => AssetDetail} createDetail - The shared detail builder.
   * @returns {{ element: HTMLLIElement, detail: AssetDetail }} The line and its detail.
   */
  const buildAssetLine = (row, itemClass, sharedLogo, createDetail) => {
    const asset = row.asset;
    const item = document.createElement("li");
    item.className = itemClass;

    const detail = createDetail(item, { asset });

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

    const cap = document.createElement("span");
    cap.className = "table__cap";
    cap.textContent =
      row.marketCap === null ? NO_VALUE : CAP.format(row.marketCap);

    wrapper.append(sharedLogo(asset), label, separator, symbol);
    detail.toggle.append(wrapper, cap);
    item.append(detail.toggle);

    return { element: item, detail };
  };

  /**
   * Build the renderer for one grouped table: the sector table or the region
   * table. Both tables read the same rule, so the markup stays in one place and
   * one fix lands in both.
   * @param {GroupTableConfig} config - The table name and the label reader.
   * @returns {(totals: SectorTotals | RegionTotals, refs: { body: HTMLElement }) => void} The renderer for one totals object.
   */
  const createGroupTable = (config) => {
    const name = config.name;
    const labelOf = config.labelOf;
    const itemClass = `${name}__item`;
    const toggleClass = `${name}__toggle`;

    /**
     * Draw the table. One row holds the group label, the market cap of the
     * group, and the part of the snapshot total that the group takes. A click on
     * the row, or on its button, opens the assets of the group below the row.
     * @param {SectorTotals | RegionTotals} totals - The rows in market cap order and the total value.
     * @param {{ body: HTMLElement }} refs - The element that the table writes to.
     * @returns {void}
     */
    return (totals, refs) => {
      const sharedLogo = ns.buildLogo;
      const createDetail = ns.createAssetDetail;

      if (typeof sharedLogo !== "function") {
        throw new Error("The logo builder from js/render-list.js did not load.");
      }

      if (typeof createDetail !== "function") {
        throw new Error(
          "The asset detail builder from js/asset-detail.js did not load.",
        );
      }

      const fragment = document.createDocumentFragment();

      totals.rows.forEach((row, index) => {
        const element = document.createElement("tr");
        element.className = `${name}-row`;

        const detailId = `${name}-assets-${index}`;

        const caret = document.createElement("span");
        caret.className = `${name}__caret`;
        caret.setAttribute("aria-hidden", "true");
        caret.textContent = CARET;

        const label = document.createElement("span");
        label.className = `${name}__label`;
        label.textContent = labelOf(row);

        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = toggleClass;
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
        detail.className = `${name}__detail`;
        detail.id = detailId;
        detail.hidden = true;

        const detailCell = document.createElement("td");
        detailCell.className = `${name}__cell`;
        detailCell.colSpan = GROUP_COLUMN_COUNT;

        const list = document.createElement("ul");
        list.className = `${name}__assets`;

        /** @type {AssetDetail[]} */
        const assetDetails = [];

        row.assets.forEach((entry) => {
          const line = buildAssetLine(entry, itemClass, sharedLogo, createDetail);
          assetDetails.push(line.detail);
          list.append(line.element, line.detail.element);
        });

        detailCell.append(list);
        detail.append(detailCell);

        /**
         * Open or close the asset list of one group. A list that closes takes
         * its open asset panels with it.
         * @param {boolean} open - True shows the list.
         * @returns {void}
         */
        const setOpen = (open) => {
          toggle.setAttribute("aria-expanded", open ? "true" : "false");
          detail.hidden = !open;

          if (!open) {
            for (const line of assetDetails) {
              line.close();
            }
          }
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
            target.closest(`.${toggleClass}`) !== null
          ) {
            return;
          }

          setOpen(toggle.getAttribute("aria-expanded") !== "true");
        });

        fragment.append(element, detail);
      });

      refs.body.replaceChildren(fragment);

      const built = refs.body.querySelectorAll(`tr.${name}-row`).length;
      const details = refs.body.querySelectorAll(`tr.${name}__detail`).length;

      if (built !== totals.rows.length || details !== totals.rows.length) {
        throw new Error(
          `The ${name} table holds ${built} rows and ${details} lists for ${totals.rows.length} ${name}s.`,
        );
      }

      const listed = refs.body.querySelectorAll(`.${itemClass}`).length;
      const expected = totals.rows.reduce((sum, row) => sum + row.assetCount, 0);

      if (listed !== expected) {
        throw new Error(
          `The ${name} lists hold ${listed} assets for ${expected} assets.`,
        );
      }
    };
  };

  ns.buildLogo = buildLogo;
  ns.renderList = renderList;
  ns.createGroupTable = createGroupTable;
})();

