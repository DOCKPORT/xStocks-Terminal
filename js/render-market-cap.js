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
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: MarketCapNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  const LOGO_DIR = "data/logos";
  const LOGO_SIZE = 40;

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
   * Build the asset cell. The cell holds the logo, the name, and the symbol, so
   * the two tables look alike.
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
   * Draw the ranking table. One row holds the rank, the asset, the market cap,
   * and the share of the snapshot total.
   * @param {MarketCapRanking} ranking - The rows in rank order and the total value.
   * @param {MarketCapRefs} refs - The element that the table writes to.
   * @returns {void}
   */
  const renderMarketCap = (ranking, refs) => {
    const fragment = document.createDocumentFragment();

    ranking.rows.forEach((row, index) => {
      const element = document.createElement("tr");

      const rankCell = document.createElement("td");
      rankCell.className = "col-rank table__rank";
      rankCell.textContent = String(index + 1);

      const capText = row.marketCap === null ? NO_VALUE : CAP.format(row.marketCap);
      const shareText =
        row.marketCap === null || ranking.total === 0
          ? NO_VALUE
          : SHARE.format(row.marketCap / ranking.total);

      element.append(
        rankCell,
        buildAssetCell(row.asset),
        buildNumberCell("is-numeric table__cap", capText),
        buildNumberCell("is-numeric table__share", shareText),
      );

      fragment.append(element);
    });

    refs.body.replaceChildren(fragment);

    const built = refs.body.childElementCount;
    if (built !== ranking.rows.length) {
      throw new Error(
        `The ranking holds ${built} rows for ${ranking.rows.length} assets.`,
      );
    }
  };

  ns.renderMarketCap = renderMarketCap;
})();
