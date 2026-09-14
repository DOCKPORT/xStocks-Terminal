/**
 * @file Compute the headline totals from the asset snapshot.
 */

/**
 * The headline totals for the metric cards.
 * @typedef {object} Metrics
 * @property {number} totalMarketCap - Price times circulating supply, summed over the snapshot.
 * @property {number} assetCount - The number of assets in the snapshot.
 * @property {number} pricedCount - The assets that hold both a price and a supply.
 * @property {number | null} mintRatio - Tokens minted divided by shares held. Null when no asset holds a reserve row.
 * @property {string | null} quoteUpdatedAt - The newest quote stamp in the snapshot.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} MetricsNamespace
 * @property {(assets: Asset[]) => Metrics} [computeMetrics] - Compute the headline totals.
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
   * Compute the headline totals. An asset with no reserve row leaves the supply
   * sums, so the ratio reads on full data alone.
   * @param {Asset[]} assets - The asset snapshot.
   * @returns {Metrics} The totals.
   */
  const computeMetrics = (assets) => {
    let totalMarketCap = 0;
    let pricedCount = 0;
    let mintedTotal = 0;
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
        pricedCount += 1;
      }

      if (supply !== null && shares !== null && shares > 0) {
        mintedTotal += supply;
        sharesTotal += shares;
      }
    }

    return {
      totalMarketCap,
      assetCount: assets.length,
      pricedCount,
      mintRatio: sharesTotal > 0 ? mintedTotal / sharesTotal : null,
      quoteUpdatedAt,
    };
  };

  ns.computeMetrics = computeMetrics;
})();
