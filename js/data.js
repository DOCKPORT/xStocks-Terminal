/**
 * @file Read the local asset snapshot.
 */

/**
 * One normalised asset record.
 * @typedef {object} Asset
 * @property {string} name - The company or fund name.
 * @property {string} symbol - The xStock symbol.
 * @property {string | null} listingCountry - The two-letter country code of the listing market from the xStock catalog. The value is null when the catalog holds none.
 * @property {string | null} sector - The sector name from the universe snapshot. A value of "unknown" marks an asset that no rule matched.
 * @property {string | null} industry - The industry from the ticker universe. The value is null when the universe holds none.
 * @property {string | null} exchange - The listing exchange from the ticker universe. The value is null when the universe holds none.
 * @property {string | null} sharesHeld - The reserve shares, kept as a string.
 * @property {string | null} circulatingSupply - The supply that the public holds, kept as a string.
 * @property {number | null} price - The last known quote.
 * @property {string | null} priceUpdatedAt - When that quote was written.
 * @property {number | null} multiplier - The current token multiplier for one share. The value is null when no run holds it.
 * @property {string | null} [filingUrl] - The SEC EDGAR company page of this asset. js/main.js joins the value from data/sec_edgar.json. The value is null when the asset holds no CIK, and absent on a row that no join touched.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} DataNamespace
 * @property {() => Promise<Asset[]>} [loadAssets] - Read the local asset snapshot.
 * @property {() => Promise<Map<string, string>>} [loadFilingLinks] - Read the SEC EDGAR link of every asset that holds a CIK.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: DataNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** The snapshot path, relative to index.html. */
  const SNAPSHOT_URL = "data/xstocks-assets.json";

  /** The EDGAR link path, relative to index.html. */
  const FILINGS_URL = "data/sec_edgar.json";

  /**
   * The read mode for both data files. The browser checks each file with the
   * server before use, so a rewritten file never shows stale rows. A 304 answer
   * reuses the stored body, so the download stays small.
   * @type {RequestInit}
   */
  const REVALIDATE = { cache: "no-cache" };

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
   * Read every asset from the local snapshot. The browser revalidates the file,
   * so a snapshot that a script rewrote never shows stale rows.
   * @returns {Promise<Asset[]>} The asset list in file order.
   */
  const loadAssets = async () => {
    const response = await fetch(SNAPSHOT_URL, REVALIDATE);
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

  /**
   * Read the link of every asset from the EDGAR link file.
   *
   * The link is optional to the page, so a file that does not load gives an
   * empty map and a console warning. The field list then holds no link, and the
   * rest of the page stands.
   * @returns {Promise<Map<string, string>>} The link per symbol.
   */
  const loadFilingLinks = async () => {
    /** @type {Map<string, string>} */
    const links = new Map();

    /** @type {Response} */
    let response;
    try {
      response = await fetch(FILINGS_URL, REVALIDATE);
    } catch (error) {
      console.warn(`The EDGAR link file did not load. ${FILINGS_URL}.`, error);
      return links;
    }

    if (!response.ok) {
      console.warn(
        `The EDGAR link file did not load. HTTP ${response.status} from ${FILINGS_URL}.`,
      );
      return links;
    }

    /** @type {unknown} */
    let rows;
    try {
      rows = await response.json();
    } catch (error) {
      console.warn(
        `The EDGAR link file does not hold JSON. ${FILINGS_URL}.`,
        error,
      );
      return links;
    }

    if (!Array.isArray(rows)) {
      console.warn(`The EDGAR link file does not hold an array. ${FILINGS_URL}.`);
      return links;
    }

    for (const row of rows) {
      if (typeof row !== "object" || row === null) {
        continue;
      }

      const candidate = /** @type {Record<string, unknown>} */ (row);
      const symbol = candidate.symbol;
      const url = candidate.url;

      if (
        typeof symbol === "string" &&
        symbol !== "" &&
        typeof url === "string" &&
        url !== ""
      ) {
        links.set(symbol, url);
      }
    }

    return links;
  };

  ns.loadFilingLinks = loadFilingLinks;
})();

