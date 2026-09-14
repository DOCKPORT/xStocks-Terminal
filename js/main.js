/**
 * @file Page bootstrap. Reads the asset snapshot and starts the table.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} AppNamespace
 * @property {() => Promise<Asset[]>} [loadAssets] - Read the local asset snapshot.
 * @property {(assets: Asset[]) => Metrics} [computeMetrics] - Compute the headline totals.
 * @property {(metrics: Metrics, refs: MetricRefs) => void} [renderMetrics] - Draw the metric cards.
 * @property {(refs: MetricRefs) => void} [renderMetricsFailure] - Report that the totals did not load.
 * @property {(assets: Asset[], refs: ListRefs) => () => void} [renderList] - Draw the table.
 */

/** @typedef {"loading" | "ready" | "error"} AppState */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: AppNamespace }} */
  const page = window;

  /**
   * Write the app state onto the document root.
   * @param {AppState} state - The next application state.
   * @returns {void}
   */
  const setAppState = (state) => {
    document.documentElement.dataset.appState = state;
  };

  /**
   * Write the current year into the footer.
   * @returns {void}
   */
  const stampYear = () => {
    const slot = document.querySelector("#footer-year");
    if (slot instanceof HTMLElement) {
      slot.textContent = `\u00A9 ${new Date().getFullYear()}`;
    }
  };

  /**
   * Find a required element by id.
   * @param {string} id - The element id.
   * @returns {HTMLElement} The element.
   */
  const requireElement = (id) => {
    const node = document.getElementById(id);
    if (!(node instanceof HTMLElement)) {
      throw new Error(`Missing element #${id}.`);
    }
    return node;
  };

  /**
   * Find a required input by id.
   * @param {string} id - The element id.
   * @returns {HTMLInputElement} The input.
   */
  const requireInput = (id) => {
    const node = document.getElementById(id);
    if (!(node instanceof HTMLInputElement)) {
      throw new Error(`Missing input #${id}.`);
    }
    return node;
  };

  /**
   * Find every slot that the metric cards write to.
   * @returns {MetricRefs} The metric card elements.
   */
  const requireMetricRefs = () => ({
    marketCap: requireElement("metric-market-cap"),
    marketCapHint: requireElement("metric-market-cap-hint"),
    assets: requireElement("metric-assets"),
    assetsHint: requireElement("metric-assets-hint"),
    ratio: requireElement("metric-ratio"),
    ratioPercent: requireElement("metric-ratio-percent"),
    ratioHint: requireElement("metric-ratio-hint"),
  });

  /**
   * Read the data and start the page.
   * @returns {Promise<void>} Resolves when the page is ready or has failed.
   */
  const init = async () => {
    stampYear();

    const status = requireElement("asset-status");
    const ns = page.XSTOCKS;

    /** @type {MetricRefs | null} */
    let metricRefs = null;

    try {
      if (
        !ns ||
        typeof ns.loadAssets !== "function" ||
        typeof ns.computeMetrics !== "function" ||
        typeof ns.renderMetrics !== "function" ||
        typeof ns.renderList !== "function"
      ) {
        throw new Error("The page scripts did not load in order.");
      }

      setAppState("loading");

      metricRefs = requireMetricRefs();

      const assets = await ns.loadAssets();

      ns.renderMetrics(ns.computeMetrics(assets), metricRefs);

      ns.renderList(assets, {
        body: requireElement("asset-rows"),
        count: requireElement("assets-count"),
        status,
        input: requireInput("asset-search"),
      });

      setAppState("ready");
    } catch (error) {
      setAppState("error");

      if (metricRefs !== null && ns && typeof ns.renderMetricsFailure === "function") {
        ns.renderMetricsFailure(metricRefs);
      }

      status.textContent =
        error instanceof Error ? error.message : "The asset snapshot did not load.";
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

