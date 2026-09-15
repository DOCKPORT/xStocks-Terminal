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
   * Build the one cell of the row. The cell holds the logo, the name, and the
   * symbol. One flex row keeps the logo at full size, whatever width the column
   * takes.
   * @param {Asset} asset - The asset for the row.
   * @returns {HTMLTableCellElement} The cell that holds the whole entry.
   */
  const buildAssetCell = (asset) => {
    const cell = document.createElement("td");
    cell.className = "col-asset";

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
    cell.append(wrapper);

    return cell;
  };

  /**
   * Build one row. Text goes in as a text node, never as markup.
   * @param {Asset} asset - The asset for the row.
   * @returns {Row} The row and its search text.
   */
  const buildRow = (asset) => {
    const element = document.createElement("tr");
    element.append(buildAssetCell(asset));
    return { element, haystack: `${asset.name} ${asset.symbol}`.toLowerCase() };
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
    const total = assets.length;
    const fragment = document.createDocumentFragment();

    /** @type {Row[]} */
    const rows = [];

    for (const asset of sortAssets(assets)) {
      const row = buildRow(asset);
      rows.push(row);
      fragment.append(row.element);
    }

    refs.body.replaceChildren(fragment);

    const logoTotal = refs.body.querySelectorAll(".table__logo").length;
    if (logoTotal !== total) {
      throw new Error(`The rows hold ${logoTotal} logos for ${total} assets.`);
    }

    /**
     * Show the rows that match the current query. Rows are toggled, not rebuilt,
     * so the browser never reloads a logo.
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

