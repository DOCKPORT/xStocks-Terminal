/**
 * @file Compute the headline totals from the asset snapshot.
 */

/**
 * The headline totals for the metric cards.
 * @typedef {object} Metrics
 * @property {number} totalMarketCap - Price times circulating supply, summed over the snapshot.
 * @property {number} assetCount - The number of assets in the snapshot.
 * @property {number | null} tokensPerShare - The circulating tokens divided by the reserve shares. Null when no asset holds a reserve row.
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
 * @property {MarketCapRow[]} assets - The assets in the sector, largest market cap first. An asset without a value comes last, in name order.
 * @property {number | null} marketCap - The sum of price times circulating supply over the sector. Null when no asset in the sector holds a value.
 */

/**
 * The snapshot summed by sector.
 * @typedef {object} SectorTotals
 * @property {SectorRow[]} rows - Every sector in the snapshot, largest market cap first. A sector without a value comes last, in name order.
 * @property {number} total - The market cap sum over the rows that hold a value.
 */

/**
 * One row of the region totals.
 * @typedef {object} RegionRow
 * @property {string} region - The listing country code from the snapshot, or "unknown".
 * @property {number} assetCount - The number of assets that list in the region.
 * @property {MarketCapRow[]} assets - The assets in the region, largest market cap first. An asset without a value comes last, in name order.
 * @property {number | null} marketCap - The sum of price times circulating supply over the region. Null when no asset in the region holds a value.
 */

/**
 * The snapshot summed by listing region.
 * @typedef {object} RegionTotals
 * @property {RegionRow[]} rows - Every region in the snapshot, largest market cap first. A region without a value comes last, in code order.
 * @property {number} total - The market cap sum over the rows that hold a value.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} MetricsNamespace
 * @property {(assets: Asset[]) => Metrics} [computeMetrics] - Compute the headline totals.
 * @property {(assets: Asset[]) => MarketCapRanking} [computeMarketCapRanks] - Rank the snapshot by market cap.
 * @property {(assets: Asset[]) => SectorTotals} [computeSectorTotals] - Sum the snapshot by sector.
 * @property {(assets: Asset[]) => RegionTotals} [computeRegionTotals] - Sum the snapshot by listing country.
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
   * Compare two market cap values. The larger value comes first. A missing value
   * comes last. An equal pair returns zero, so the caller can break the tie.
   * @param {number | null} a - The left value.
   * @param {number | null} b - The right value.
   * @returns {number} The sort result.
   */
  const compareMarketCap = (a, b) => {
    if (a === null) {
      return b === null ? 0 : 1;
    }
    if (b === null) {
      return -1;
    }
    return b - a;
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

    for (const asset of assets) {
      const price = toNumber(asset.price);
      const supply = toNumber(asset.circulatingSupply);
      const shares = toNumber(asset.sharesHeld);

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
    rows.sort((a, b) => compareMarketCap(a.marketCap, b.marketCap));

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

  /** The word that marks an asset without a listing country. The Python script writes null. */
  const UNKNOWN_REGION = "unknown";

  /**
   * Read the listing country from one asset. The country code goes to upper case,
   * because the API and the JSON may differ in case.
   * @param {Asset} asset - The asset.
   * @returns {string} The country code, or "unknown" when the asset holds none.
   */
  const regionName = (asset) => {
    const value = asset.listingCountry;
    if (typeof value !== "string" || value.trim() === "") {
      return UNKNOWN_REGION;
    }
    return value.trim().toUpperCase();
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
      row.assets.push({ asset, marketCap });

      if (marketCap !== null) {
        row.marketCap = (row.marketCap ?? 0) + marketCap;
      }

      bySector.set(name, row);
    }

    const rows = Array.from(bySector.values());

    /* The panel draws the assets under one sector, so the largest market cap
       reads first. A missing value comes last. The name breaks a tie, then the
       symbol, the same rule as the asset table. */
    for (const row of rows) {
      row.assets.sort(
        (a, b) =>
          compareMarketCap(a.marketCap, b.marketCap) ||
          a.asset.name.localeCompare(b.asset.name) ||
          a.asset.symbol.localeCompare(b.asset.symbol),
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
    rows.sort(
      (a, b) =>
        compareMarketCap(a.marketCap, b.marketCap) ||
        a.sector.localeCompare(b.sector),
    );

    return { rows, total };
  };

  /**
   * Sum the snapshot by listing region. Every country that the snapshot holds
   * gets one row, so the panel needs no fixed list. The value reads price times
   * circulating supply, the same rule as the market cap ranking.
   * @param {Asset[]} assets - The asset snapshot.
   * @returns {RegionTotals} The rows in market cap order and the total value.
   */
  const computeRegionTotals = (assets) => {
    /** @type {Map<string, RegionRow>} */
    const byRegion = new Map();

    for (const asset of assets) {
      const code = regionName(asset);
      const row = byRegion.get(code) ?? {
        region: code,
        assetCount: 0,
        assets: [],
        marketCap: null,
      };

      const price = toNumber(asset.price);
      const supply = toNumber(asset.circulatingSupply);
      const marketCap = price !== null && supply !== null ? price * supply : null;

      row.assetCount += 1;
      row.assets.push({ asset, marketCap });

      if (marketCap !== null) {
        row.marketCap = (row.marketCap ?? 0) + marketCap;
      }

      byRegion.set(code, row);
    }

    const rows = Array.from(byRegion.values());

    /* The panel draws the assets under one region, so the largest market cap
       reads first. A missing value comes last. The name breaks a tie, then the
       symbol, the same rule as the asset table. */
    for (const row of rows) {
      row.assets.sort(
        (a, b) =>
          compareMarketCap(a.marketCap, b.marketCap) ||
          a.asset.name.localeCompare(b.asset.name) ||
          a.asset.symbol.localeCompare(b.asset.symbol),
      );
    }

    let total = 0;

    for (const row of rows) {
      if (row.marketCap !== null) {
        total += row.marketCap;
      }
    }

    /* The largest region comes first. A region without a value comes last, in
       code order. The code breaks a tie, so every run draws the same order. */
    rows.sort(
      (a, b) =>
        compareMarketCap(a.marketCap, b.marketCap) ||
        a.region.localeCompare(b.region),
    );

    return { rows, total };
  };

  ns.computeMetrics = computeMetrics;
  ns.computeMarketCapRanks = computeMarketCapRanks;
  ns.computeSectorTotals = computeSectorTotals;
  ns.computeRegionTotals = computeRegionTotals;
})();
