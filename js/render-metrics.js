/**
 * @file Draw the headline metric cards: market cap, asset count, and mint ratio.
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
 * @property {HTMLElement} ratio - The mint ratio value.
 * @property {HTMLElement} ratioPercent - The mint ratio as a percent.
 * @property {HTMLElement} ratioHint - The mint ratio note.
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

  const EXACT_USD = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });

  const COUNT = new Intl.NumberFormat("en-US");

  const RATIO = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const PERCENT = new Intl.NumberFormat("en-US", {
    style: "percent",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const STAMP = new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  });

  /**
   * Write one readable stamp for a quote time.
   * @param {string | null} iso - The stored quote stamp.
   * @returns {string | null} The readable stamp in UTC, or null when the stamp is unusable.
   */
  const formatStamp = (iso) => {
    if (typeof iso !== "string") {
      return null;
    }
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? null : `${STAMP.format(date)} UTC`;
  };

  /**
   * Report the market cap basis and its coverage.
   * @param {Metrics} metrics - The headline totals.
   * @returns {string} The note for the market cap card.
   */
  const marketCapNote = (metrics) => {
    const parts = [`Exact figure ${EXACT_USD.format(metrics.totalMarketCap)}.`];

    // A row with no price or no supply lowers the total. State the shortfall only then.
    if (metrics.pricedCount < metrics.assetCount) {
      parts.push(
        `${COUNT.format(metrics.pricedCount)} of ${COUNT.format(metrics.assetCount)} rows hold a price and a supply.`,
      );
    }

    const stamp = formatStamp(metrics.quoteUpdatedAt);
    if (stamp !== null) {
      parts.push(`Newest quote ${stamp}.`);
    }

    return parts.join(" ");
  };

  /** The note for the asset count card. */
  const ASSETS_NOTE = "One row for each token in the local snapshot.";

  /**
   * Report the basis of the mint ratio.
   * @param {Metrics} metrics - The headline totals.
   * @returns {string} The note for the mint ratio card.
   */
  const ratioNote = (metrics) =>
    `Tokens minted over shares held, across all ${COUNT.format(metrics.assetCount)} rows.`;

  /**
   * Draw the three metric cards.
   * @param {Metrics} metrics - The headline totals.
   * @param {MetricRefs} refs - The elements that the cards write to.
   * @returns {void}
   */
  const renderMetrics = (metrics, refs) => {
    refs.marketCap.textContent = COMPACT_USD.format(metrics.totalMarketCap);
    refs.marketCapHint.textContent = marketCapNote(metrics);

    refs.assets.textContent = COUNT.format(metrics.assetCount);
    refs.assetsHint.textContent = ASSETS_NOTE;

    if (metrics.mintRatio === null) {
      refs.ratio.textContent = "n/a";
      refs.ratioPercent.textContent = "n/a";
      refs.ratioHint.textContent = "No row in the snapshot holds a reserve row.";
      return;
    }

    refs.ratio.textContent = `${RATIO.format(metrics.mintRatio)} : 1`;
    refs.ratioPercent.textContent = PERCENT.format(metrics.mintRatio);
    refs.ratioHint.textContent = ratioNote(metrics);
  };

  /**
   * Clear the cards when the snapshot does not load. A dash tells the reader that
   * the value is absent, not zero.
   * @param {MetricRefs} refs - The elements that the cards write to.
   * @returns {void}
   */
  const renderMetricsFailure = (refs) => {
    for (const slot of [
      refs.marketCap,
      refs.assets,
      refs.ratio,
      refs.ratioPercent,
    ]) {
      slot.textContent = "\u2014";
    }

    refs.marketCapHint.textContent = "The snapshot did not load.";
    refs.assetsHint.textContent = "The snapshot did not load.";
    refs.ratioHint.textContent = "The snapshot did not load.";
  };

  ns.renderMetrics = renderMetrics;
  ns.renderMetricsFailure = renderMetricsFailure;
})();
