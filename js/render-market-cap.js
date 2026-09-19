/**
 * @file Rank the snapshot by market cap and draw the ranking table.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} MarketCapNamespace
 * @property {(ranking: MarketCapRanking, refs: MarketCapRefs) => void} [renderMarketCap] - Draw the ranking.
 */

/**
 * The element that the ranking table writes to.
 * @typedef {object} MarketCapRefs
 * @property {HTMLElement} body - The table body that holds the rows.
 * @property {HTMLElement} status - The live region that reports the filter result.
 * @property {HTMLInputElement} input - The search field.
 */

/**
 * One ranking row and its search text.
 * @typedef {object} RankRow
 * @property {HTMLTableRowElement} element - The table row.
 * @property {AssetDetail} detail - The collapsible detail that pairs with the row.
 * @property {string} haystack - The lower-case name and symbol.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: MarketCapNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  const LOGO_DIR = "data/logos";
  const LOGO_SIZE = 40;

  /** The ranked table holds four columns: the rank, the asset, the cap, and the share. */
  const COLUMN_COUNT = 4;

  /** A dash marks a value that the snapshot does not hold, so a reader sees a gap and not a zero. */
  const NO_VALUE = "\u2014";

  /* The column drops trailing zeros, so a round value reads "$5K" and not
     "$5.00K". A long value keeps two decimals, for example "$143.99M". */
  const CAP = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });

  const SHARE = new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

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
   * Build the content of one row: the logo, the name, and the symbol, so the two
   * tables look alike.
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
   * Build one ranking row and its detail panel. The rank holds the true market
   * cap position, so a filter never renumbers the column. The whole row toggles
   * the panel below it.
   * @param {MarketCapRow} row - The asset and its market cap.
   * @param {number} rank - The one-based market cap rank.
   * @param {number} total - The market cap of the whole snapshot.
   * @param {(trigger: HTMLElement, options?: AssetDetailOptions) => AssetDetail} createDetail - The shared detail builder.
   * @returns {RankRow} The row, its detail, and its search text.
   */
  const buildRow = (row, rank, total, createDetail) => {
    const element = document.createElement("tr");
    element.className = "asset-row";

    const detail = createDetail(element, {
      columns: COLUMN_COUNT,
      asset: row.asset,
    });

    const rankCell = document.createElement("td");
    rankCell.className = "col-rank table__rank";
    rankCell.textContent = String(rank);

    const assetCell = document.createElement("td");
    assetCell.className = "col-asset";
    detail.toggle.append(buildAssetContent(row.asset));
    assetCell.append(detail.toggle);

    const capText = row.marketCap === null ? NO_VALUE : CAP.format(row.marketCap);
    const shareText =
      row.marketCap === null || total === 0
        ? NO_VALUE
        : SHARE.format(row.marketCap / total);

    element.append(
      rankCell,
      assetCell,
      buildNumberCell("is-numeric table__cap", capText),
      buildNumberCell("is-numeric table__share", shareText),
    );

    return {
      element,
      detail,
      haystack: `${row.asset.name} ${row.asset.symbol}`.toLowerCase(),
    };
  };

  /**
   * Draw the ranking table and wire the search field. One row holds the rank,
   * the asset, the market cap, and the share of the snapshot total.
   * @param {MarketCapRanking} ranking - The rows in rank order and the total value.
   * @param {MarketCapRefs} refs - The elements that the table writes to.
   * @returns {void}
   */
  const renderMarketCap = (ranking, refs) => {
    const createDetail = ns.createAssetDetail;

    if (typeof createDetail !== "function") {
      throw new Error(
        "The asset detail builder from js/asset-detail.js did not load.",
      );
    }

    const total = ranking.rows.length;
    const fragment = document.createDocumentFragment();

    /** @type {RankRow[]} */
    const rows = [];

    ranking.rows.forEach((row, index) => {
      const entry = buildRow(row, index + 1, ranking.total, createDetail);
      rows.push(entry);
      fragment.append(entry.element, entry.detail.element);
    });

    refs.body.replaceChildren(fragment);

    const built = refs.body.querySelectorAll("tr.asset-row").length;
    if (built !== total) {
      throw new Error(`The ranking holds ${built} rows for ${total} assets.`);
    }

    const details = refs.body.querySelectorAll("tr.asset__detail").length;
    if (details !== total) {
      throw new Error(
        `The ranking holds ${details} details for ${total} assets.`,
      );
    }

    /**
     * Show the rows that match the current query. Rows are toggled, not rebuilt,
     * so the browser never reloads a logo and the rank column stays true. A row
     * that leaves the list closes its detail, so no panel stays open on its own.
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
  };

  ns.renderMarketCap = renderMarketCap;
})();
