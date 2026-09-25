/**
 * @file Draw the sector table: the market cap and the weight of every sector
 * that the snapshot holds. A sector row toggles the list of its assets. The
 * markup comes from the shared grouped table in js/render-list.js.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} SectorsNamespace
 * @property {(config: GroupTableConfig) => (totals: SectorTotals, refs: SectorRefs) => void} [createGroupTable] - Build the shared table renderer from js/render-list.js.
 */

/**
 * The element that the sector table writes to.
 * @typedef {object} SectorRefs
 * @property {HTMLElement} body - The table body that holds the rows.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: SectorsNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** The table name drives every class name and every detail id. */
  const TABLE_NAME = "sector";

  /**
   * Read the label of one sector row.
   * @param {SectorRow} row - The sector row.
   * @returns {string} The sector name.
   */
  const labelOf = (row) => row.sector;

  /**
   * Draw the sector table. One row holds the sector name, the market cap of the
   * sector, and the part of the snapshot total that the sector takes. A click on
   * the row, or on its button, opens the assets of the sector below the row.
   * @param {SectorTotals} totals - The rows in market cap order and the total value.
   * @param {SectorRefs} refs - The element that the table writes to.
   * @returns {void}
   */
  const renderSectors = (totals, refs) => {
    const createGroupTable = ns.createGroupTable;

    if (typeof createGroupTable !== "function") {
      throw new Error(
        "The grouped table builder from js/render-list.js did not load.",
      );
    }

    createGroupTable({ name: TABLE_NAME, labelOf })(totals, refs);
  };

  ns.renderSectors = renderSectors;
})();
