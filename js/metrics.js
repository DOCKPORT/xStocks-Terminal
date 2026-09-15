/**
 * @file Compute the headline totals from the asset snapshot.
 */

/**
 * The headline totals for the metric cards.
 * @typedef {object} Metrics
 * @property {number} totalMarketCap - Price times circulating supply, summed over the snapshot.
 * @property {number} assetCount - The number of assets in the snapshot.
 * @property {number | null} tokensPerShare - The circulating tokens divided by the reserve shares. Null when no asset holds a reserve row.
 * @property {string | null} quoteUpdatedAt - The newest quote stamp in the snapshot.
 */

/**
 * One row of the market cap ranking.
 * @typedef {object} MarketCapRow
 * @property {Asset} asset - The asset for the row.
 * @property {number | null} marketCap - Price times circulating supply. Null when a value is absent.
 */

/**
 * The snapshot in market cap order.
 * @typedef {object} MarketCapRanking
 * @property {MarketCapRow[]} rows - Every asset, largest market cap first. A row without a value comes last.
 * @property {number} total - The market cap sum over the rows that hold a value.
 */

/**
 * One row of the sector totals.
 * @typedef {object} SectorRow
 * @property {string} sector - The sector name from the snapshot.
 * @property {number} assetCount - The number of assets in the sector.
 * @property {Asset[]} assets - The assets in the sector, in name order.
 * @property {number | null} marketCap - The sum of price times circulating supply over the sector. Null when no asset in the sector holds a value.
 */

/**
 * The snapshot summed by sector.
 * @typedef {object} SectorTotals
 * @property {SectorRow[]} rows - Every sector in the snapshot, largest market cap first. A sector without a value comes last, in name order.
 * @property {number} total - The market cap sum over the rows that hold a value.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} MetricsNamespace
 * @property {(assets: Asset[]) => Metrics} [computeMetrics] - Compute the headline totals.
 * @property {(assets: Asset[]) => MarketCapRanking} [computeMarketCapRanks] - Rank the snapshot by market cap.
 * @property {(assets: Asset[]) => SectorTotals} [computeSectorTotals] - Sum the snapshot by sector.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: MetricsNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /**
   * Read one stored value as a number. The snapshot holds supply and shares as
   * strings, because those values have many decimals.
   * @param {unknown} value - The stored value.
   * @returns {number | null} The number, or null when the value is absent.
   */
  const toNumber = (value) => {
    if (typeof value === "number") {
      return Number.isFinite(value) ? value : null;
    }
    if (typeof value !== "string" || value.trim() === "") {
      return null;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  /**
   * Keep the later of two quote stamps.
   * @param {string | null} current - The newest stamp so far.
   * @param {unknown} candidate - The next stamp.
   * @returns {string | null} The newer stamp.
   */
  const newerStamp = (current, candidate) => {
    if (typeof candidate !== "string" || candidate === "") {
      return current;
    }
    if (current === null || candidate > current) {
      return candidate;
    }
    return current;
  };

  /**
   * Compute the headline totals. The market cap sum reads the circulating supply,
   * so it is the value of the public float and not a fully diluted value.
   * @param {Asset[]} assets - The asset snapshot.
   * @returns {Metrics} The totals.
   */
  const computeMetrics = (assets) => {
    let totalMarketCap = 0;
    let circulatingTotal = 0;
    let sharesTotal = 0;

    /** @type {string | null} */
    let quoteUpdatedAt = null;

    for (const asset of assets) {
      const price = toNumber(asset.price);
      const supply = toNumber(asset.circulatingSupply);
      const shares = toNumber(asset.sharesHeld);

      quoteUpdatedAt = newerStamp(quoteUpdatedAt, asset.priceUpdatedAt);

      if (price !== null && supply !== null) {
        totalMarketCap += price * supply;
      }

      if (supply !== null && shares !== null && shares > 0) {
        circulatingTotal += supply;
        sharesTotal += shares;
      }
    }

    return {
      totalMarketCap,
      assetCount: assets.length,
      tokensPerShare: sharesTotal > 0 ? circulatingTotal / sharesTotal : null,
      quoteUpdatedAt,
    };
  };

  /**
   * Rank the snapshot by market cap. The value reads price times circulating
   * supply, so it is the value of the public float and not a fully diluted
   * value. A row without a price or a supply keeps no value and sorts last.
   * @param {Asset[]} assets - The asset snapshot.
   * @returns {MarketCapRanking} The rows in rank order and the total value.
   */
  const computeMarketCapRanks = (assets) => {
    /** @type {MarketCapRow[]} */
    const rows = [];
    let total = 0;

    for (const asset of assets) {
      const price = toNumber(asset.price);
      const supply = toNumber(asset.circulatingSupply);
      const marketCap = price !== null && supply !== null ? price * supply : null;

      if (marketCap !== null) {
        total += marketCap;
      }

      rows.push({ asset, marketCap });
    }

    /* The sort keeps the file order for equal values, because it is stable. */
    rows.sort((a, b) => {
      if (a.marketCap === null) {
        return b.marketCap === null ? 0 : 1;
      }
      if (b.marketCap === null) {
        return -1;
      }
      return b.marketCap - a.marketCap;
    });

    return { rows, total };
  };

  /** The word that marks an asset without a sector. The Python backfill writes the same word. */
  const UNKNOWN_SECTOR = "unknown";

  /**
   * Read the sector name from one asset.
   * @param {Asset} asset - The asset.
   * @returns {string} The sector name, or "unknown" when the asset holds none.
   */
  const sectorName = (asset) => {
    const value = asset.sector;
    if (typeof value !== "string" || value.trim() === "") {
      return UNKNOWN_SECTOR;
    }
    return value.trim();
  };

  /**
   * Sum the snapshot by sector. Every sector that the snapshot holds gets one
   * row, so the panel needs no fixed list. The value reads price times
   * circulating supply, the same rule as the market cap ranking.
   * @param {Asset[]} assets - The asset snapshot.
   * @returns {SectorTotals} The rows in market cap order and the total value.
   */
  const computeSectorTotals = (assets) => {
    /** @type {Map<string, SectorRow>} */
    const bySector = new Map();

    for (const asset of assets) {
      const name = sectorName(asset);
      const row = bySector.get(name) ?? {
        sector: name,
        assetCount: 0,
        assets: [],
        marketCap: null,
      };

      const price = toNumber(asset.price);
      const supply = toNumber(asset.circulatingSupply);
      const marketCap = price !== null && supply !== null ? price * supply : null;

      row.assetCount += 1;
      row.assets.push(asset);

      if (marketCap !== null) {
        row.marketCap = (row.marketCap ?? 0) + marketCap;
      }

      bySector.set(name, row);
    }

    const rows = Array.from(bySector.values());

    /* The panel draws the assets under one sector, so the list reads in name
       order. The symbol breaks a tie, the same rule as the asset table. */
    for (const row of rows) {
      row.assets.sort(
        (a, b) =>
          a.name.localeCompare(b.name) || a.symbol.localeCompare(b.symbol),
      );
    }

    let total = 0;

    for (const row of rows) {
      if (row.marketCap !== null) {
        total += row.marketCap;
      }
    }

    /* The largest sector comes first. A sector without a value comes last, in
       name order. The name breaks a tie, so every run draws the same order. */
    rows.sort((a, b) => {
      if (a.marketCap === null) {
        return b.marketCap === null ? a.sector.localeCompare(b.sector) : 1;
      }
      if (b.marketCap === null) {
        return -1;
      }
      if (b.marketCap !== a.marketCap) {
        return b.marketCap - a.marketCap;
      }
      return a.sector.localeCompare(b.sector);
    });

    return { rows, total };
  };

  ns.computeMetrics = computeMetrics;
  ns.computeMarketCapRanks = computeMarketCapRanks;
  ns.computeSectorTotals = computeSectorTotals;
})();
