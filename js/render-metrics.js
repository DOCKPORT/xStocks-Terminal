/**
 * @file Draw the headline metric cards: market cap, asset count, and reserve ratio.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} MetricNamespace
 * @property {(metrics: Metrics, refs: MetricRefs) => void} [renderMetrics] - Draw the metric cards.
 * @property {(refs: MetricRefs) => void} [renderMetricsFailure] - Report that the totals did not load.
 */

/**
 * The elements that the metric cards write to.
 * @typedef {object} MetricRefs
 * @property {HTMLElement} marketCap - The total market cap value.
 * @property {HTMLElement} marketCapHint - The market cap note.
 * @property {HTMLElement} assets - The asset count value.
 * @property {HTMLElement} assetsHint - The asset count note.
 * @property {HTMLElement} ratio - The reserve ratio value.
 * @property {HTMLElement} ratioHint - The reserve ratio note.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: MetricNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  const COMPACT_USD = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 2,
  });

  const COUNT = new Intl.NumberFormat("en-US");

  const RATIO = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  /** The note for the market cap card. */
  const MARKET_CAP_NOTE = "Token circulating supply \u00d7 quote price.";

  /** The note for the asset count card. */
  const ASSETS_NOTE = "Stocks, ETFs and Funds.";

  /** The note for the tokens-per-share card. */
  const RATIO_NOTE = "Circulating tokens per share held.";

  /**
   * Draw the three metric cards.
   * @param {Metrics} metrics - The headline totals.
   * @param {MetricRefs} refs - The elements that the cards write to.
   * @returns {void}
   */
  const renderMetrics = (metrics, refs) => {
    refs.marketCap.textContent = COMPACT_USD.format(metrics.totalMarketCap);
    refs.marketCapHint.textContent = MARKET_CAP_NOTE;

    refs.assets.textContent = COUNT.format(metrics.assetCount);
    refs.assetsHint.textContent = ASSETS_NOTE;

    if (metrics.tokensPerShare === null) {
      refs.ratio.textContent = "n/a";
      refs.ratioHint.textContent = "No row in the snapshot holds a reserve row.";
      return;
    }

    /* The pair reads tokens first, then shares, so the colon matches the note:
       the token count against one share held. */
    refs.ratio.textContent = `${RATIO.format(metrics.tokensPerShare)} : 1`;
    refs.ratioHint.textContent = RATIO_NOTE;
  };

  /**
   * Clear the cards when the snapshot does not load. A dash tells the reader that
   * the value is absent, not zero.
   * @param {MetricRefs} refs - The elements that the cards write to.
   * @returns {void}
   */
  const renderMetricsFailure = (refs) => {
    for (const slot of [refs.marketCap, refs.assets, refs.ratio]) {
      slot.textContent = "\u2014";
    }

    refs.marketCapHint.textContent = "The snapshot did not load.";
    refs.assetsHint.textContent = "The snapshot did not load.";
    refs.ratioHint.textContent = "The snapshot did not load.";
  };

  ns.renderMetrics = renderMetrics;
  ns.renderMetricsFailure = renderMetricsFailure;
})();
