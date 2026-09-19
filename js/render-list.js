/**
 * @file Render the asset table and filter it by name or symbol. The file also
 * builds the row logo, so every view draws the same logo rule.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} ListNamespace
 * @property {(asset: Asset) => HTMLImageElement} [buildLogo] - Build the row logo, with a letter tile as the fallback.
 * @property {(assets: Asset[], refs: ListRefs) => () => void} [renderList] - Draw the table.
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
   * Build the logo for one row. If the file is missing, a letter tile takes its
   * place, so a broken logo stays visible instead of vanishing.
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

  ns.buildLogo = buildLogo;
  ns.renderList = renderList;
})();

