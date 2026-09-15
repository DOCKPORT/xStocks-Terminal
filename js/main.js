/**
 * @file Page bootstrap. Wires the view buttons, reads the asset snapshot, and
 * starts the table.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} AppNamespace
 * @property {() => Promise<Asset[]>} [loadAssets] - Read the local asset snapshot.
 * @property {(assets: Asset[]) => Metrics} [computeMetrics] - Compute the headline totals.
 * @property {(metrics: Metrics, refs: MetricRefs) => void} [renderMetrics] - Draw the metric cards.
 * @property {(refs: MetricRefs) => void} [renderMetricsFailure] - Report that the totals did not load.
 * @property {(assets: Asset[]) => MarketCapRanking} [computeMarketCapRanks] - Rank the snapshot by market cap.
 * @property {(assets: Asset[], refs: ListRefs) => () => void} [renderList] - Draw the table.
 * @property {(ranking: MarketCapRanking, refs: MarketCapRefs) => void} [renderMarketCap] - Draw the market cap ranking.
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
   * Move the pressed state onto one button of a group.
   * @param {HTMLButtonElement} picked - The button that the user pressed.
   * @param {HTMLButtonElement[]} group - Every button in the group.
   * @returns {void}
   */
  const selectView = (picked, group) => {
    group.forEach((button) => {
      button.setAttribute("aria-pressed", button === picked ? "true" : "false");
    });
  };

  /**
   * Show the panel that pairs with one view. Every other panel hides. When the
   * markup holds no pair, the current panel stays, so the section never goes
   * blank.
   * @param {string} view - The view name from the picked button.
   * @returns {void}
   */
  const showPanel = (view) => {
    /** @type {HTMLElement[]} */
    const panels = [];

    document.querySelectorAll("[data-view-panel]").forEach((node) => {
      if (node instanceof HTMLElement) {
        panels.push(node);
      }
    });

    const match = panels.find((panel) => panel.dataset.viewPanel === view);

    if (!match) {
      return;
    }

    panels.forEach((panel) => {
      panel.hidden = panel !== match;
    });
  };

  /**
   * Wire the view buttons. One click moves the pressed state. The stylesheet
   * draws the purple and grey borders from that state.
   * @returns {void}
   */
  const bindViewToggle = () => {
    /** @type {HTMLButtonElement[]} */
    const group = [];

    document.querySelectorAll("[data-view]").forEach((node) => {
      if (node instanceof HTMLButtonElement) {
        group.push(node);
      }
    });

    if (group.length === 0) {
      return;
    }

    document.addEventListener("click", (event) => {
      const target = event.target;

      if (!(target instanceof HTMLElement)) {
        return;
      }

      const picked = target.closest("[data-view]");

      if (!(picked instanceof HTMLButtonElement)) {
        return;
      }

      const view = picked.dataset.view;

      if (view) {
        selectView(picked, group);
        showPanel(view);
      }
    });
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
   * Find the slot that the market cap table writes to.
   * @returns {MarketCapRefs} The ranking element.
   */
  const requireMarketCapRefs = () => ({
    body: requireElement("market-cap-rows"),
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

    /** @type {MarketCapRefs | null} */
    let marketCapRefs = null;

    try {
      if (
        !ns ||
        typeof ns.loadAssets !== "function" ||
        typeof ns.computeMetrics !== "function" ||
        typeof ns.renderMetrics !== "function" ||
        typeof ns.renderList !== "function" ||
        typeof ns.computeMarketCapRanks !== "function" ||
        typeof ns.renderMarketCap !== "function"
      ) {
        throw new Error("The page scripts did not load in order.");
      }

      setAppState("loading");

      metricRefs = requireMetricRefs();
      marketCapRefs = requireMarketCapRefs();

      const assets = await ns.loadAssets();

      ns.renderMetrics(ns.computeMetrics(assets), metricRefs);

      ns.renderList(assets, {
        body: requireElement("asset-rows"),
        status,
        input: requireInput("asset-search"),
      });

      ns.renderMarketCap(ns.computeMarketCapRanks(assets), marketCapRefs);

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

  /* The toggle binds at load time, so it works when the data fails. */
  bindViewToggle();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

