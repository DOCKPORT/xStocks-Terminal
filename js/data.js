/**
 * @file Read the local asset snapshot.
 */

/**
 * One normalised asset record.
 * @typedef {object} Asset
 * @property {string} name - The company or fund name.
 * @property {string} symbol - The xStock symbol.
 * @property {string | null} sharesHeld - The reserve shares, kept as a string.
 * @property {string | null} circulatingSupply - The token supply, kept as a string.
 */

/**
 * The shared page namespace. The page has no build step and no server, so the
 * files share one global object instead of ES module imports.
 * @typedef {object} DataNamespace
 * @property {unknown} [XSTOCKS_ASSETS] - The raw snapshot, written by the fetch script.
 * @property {() => Asset[]} [loadAssets] - Read the local asset snapshot.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: DataNamespace; XSTOCKS_ASSETS?: unknown }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /**
   * Check one raw row from the snapshot.
   * @param {unknown} row - One raw row.
   * @returns {row is Asset} True when the row holds a name and a symbol.
   */
  const isAsset = (row) => {
    if (typeof row !== "object" || row === null) {
      return false;
    }
    const candidate = /** @type {Record<string, unknown>} */ (row);
    return (
      typeof candidate.name === "string" && typeof candidate.symbol === "string"
    );
  };

  /**
   * Read every asset from the local snapshot.
   * @returns {Asset[]} The asset list in file order.
   */
  const loadAssets = () => {
    if (!Array.isArray(page.XSTOCKS_ASSETS)) {
      throw new Error(
        "The asset snapshot did not load. Check data/xstocks-assets.js.",
      );
    }
    return page.XSTOCKS_ASSETS.filter(isAsset);
  };

  ns.loadAssets = loadAssets;
})();

