/**
 * @file Draw the region table: the market cap and the weight of every listing
 * country that the snapshot holds. A region row toggles the list of its assets.
 * The markup comes from the shared grouped table in js/render-list.js.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} RegionsNamespace
 * @property {(config: GroupTableConfig) => (totals: RegionTotals, refs: RegionRefs) => void} [createGroupTable] - Build the shared table renderer from js/render-list.js.
 */

/**
 * The element that the region table writes to.
 * @typedef {object} RegionRefs
 * @property {HTMLElement} body - The table body that holds the rows.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: RegionsNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** The table name drives every class name and every detail id. */
  const TABLE_NAME = "region";

  /** The word that marks an asset without a listing country. js/metrics.js writes the same word. */
  const UNKNOWN_REGION = "unknown";

  /* The country names come from the browser, so no list goes stale when the API
     adds a country. A browser without the API shows the code itself. */
  const REGION_NAMES =
    typeof Intl.DisplayNames === "function"
      ? new Intl.DisplayNames(["en"], { type: "region" })
      : null;

  /**
   * Turn one country code into a display name.
   * @param {string} code - The country code from the snapshot, or "unknown".
   * @returns {string} The country name. A code that the browser does not know stays as it stands.
   */
  const regionLabel = (code) => {
    if (REGION_NAMES === null || code === UNKNOWN_REGION) {
      return code;
    }

    try {
      return REGION_NAMES.of(code) || code;
    } catch {
      /* The API holds a code that the browser rejects. Show the code. */
      return code;
    }
  };

  /**
   * Read the label of one region row.
   * @param {RegionRow} row - The region row.
   * @returns {string} The country name, or "unknown".
   */
  const labelOf = (row) => regionLabel(row.region);

  /**
   * Draw the region table. One row holds the country, the market cap of the
   * region, and the part of the snapshot total that the region takes. A click on
   * the row, or on its button, opens the assets of the region below the row.
   * @param {RegionTotals} totals - The rows in market cap order and the total value.
   * @param {RegionRefs} refs - The element that the table writes to.
   * @returns {void}
   */
  const renderRegion = (totals, refs) => {
    const createGroupTable = ns.createGroupTable;

    if (typeof createGroupTable !== "function") {
      throw new Error(
        "The grouped table builder from js/render-list.js did not load.",
      );
    }

    createGroupTable({ name: TABLE_NAME, labelOf })(totals, refs);
  };

  ns.renderRegion = renderRegion;
})();
