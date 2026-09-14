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
 * @property {number | null} price - The last known quote.
 * @property {string | null} priceUpdatedAt - When that quote was written.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} DataNamespace
 * @property {() => Promise<Asset[]>} [loadAssets] - Read the local asset snapshot.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: DataNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** The snapshot path, relative to index.html. */
  const SNAPSHOT_URL = "data/xstocks-assets.json";

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
   * @returns {Promise<Asset[]>} The asset list in file order.
   */
  const loadAssets = async () => {
    const response = await fetch(SNAPSHOT_URL);
    if (!response.ok) {
      throw new Error(
        `The asset snapshot did not load. HTTP ${response.status} from ${SNAPSHOT_URL}.`,
      );
    }

    /** @type {unknown} */
    const rows = await response.json();
    if (!Array.isArray(rows)) {
      throw new Error(
        `The asset snapshot did not load. ${SNAPSHOT_URL} does not hold an array.`,
      );
    }

    return rows.filter(isAsset);
  };

  ns.loadAssets = loadAssets;
})();

