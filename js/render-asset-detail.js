/**
 * @file Build the field list for one asset detail panel. Each field is a label
 * and a value. A field that the snapshot does not hold leaves no label behind.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} AssetDetailBodyNamespace
 * @property {(asset: Asset) => HTMLElement} [buildAssetDetailBody] - Build the label and value list for one asset.
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: AssetDetailBodyNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /* The price keeps the precision of the snapshot: a round value reads
     "$28.72", and a long one reads "$335.515". */
  const PRICE = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });

  const COUNT = new Intl.NumberFormat("en-US");

  /** The shape of an ISO stamp: "2026-09-18T17:57:27+00:00". */
  const ISO_STAMP = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/;

  /**
   * Group the digits of a stored number string. The snapshot keeps those values
   * as strings, so the fraction stays exact and no precision is lost.
   * @param {string} value - The stored value.
   * @returns {string} The grouped value. A value that is not a plain number returns unchanged.
   */
  const groupNumber = (value) => {
    const text = value.trim();
    const whole = text.split(".")[0];

    /* The round trip must match, so a leading zero or an odd shape keeps the
       stored text as it stands. */
    if (!/^\d+$/.test(whole) || String(Number(whole)) !== whole) {
      return text;
    }

    const grouped = COUNT.format(Number(whole));
    const fraction = text.slice(whole.length);

    return `${grouped}${fraction}`;
  };

  /**
   * Turn an ISO stamp into a readable UTC value.
   * @param {string} value - The stored stamp.
   * @returns {string} The value as "2026-09-18 17:57 UTC". An odd value returns unchanged.
   */
  const readStamp = (value) => {
    const match = ISO_STAMP.exec(value.trim());
    if (match === null) {
      return value.trim();
    }
    return `${match[1]} ${match[2]} UTC`;
  };

  /**
   * Build the field list for one asset. The order reads price first, then the
   * place of the asset, then its reserve and its quote age.
   * @param {Asset} asset - The asset for the panel.
   * @returns {HTMLElement} The list of label and value pairs.
   */
  const buildAssetDetailBody = (asset) => {
    const list = document.createElement("dl");
    list.className = "asset__fields";

    /**
     * Add one label and value pair. An empty value adds nothing.
     * @param {string} label - The field name.
     * @param {string} value - The field value.
     * @returns {void}
     */
    const add = (label, value) => {
      if (value === "") {
        return;
      }

      const term = document.createElement("dt");
      term.className = "asset__label";
      term.textContent = label;

      const detail = document.createElement("dd");
      detail.className = "asset__value";
      detail.textContent = value;

      list.append(term, detail);
    };

    add(
      "Price",
      typeof asset.price === "number" ? PRICE.format(asset.price) : "",
    );
    add("Sector", asset.sector ?? "");
    add("Industry", asset.industry ?? "");
    add("Exchange", asset.exchange ?? "");
    add("Listing country", asset.listingCountry ?? "");
    add(
      "Shares held",
      typeof asset.sharesHeld === "string" ? groupNumber(asset.sharesHeld) : "",
    );
    add(
      "Quote updated",
      typeof asset.priceUpdatedAt === "string"
        ? readStamp(asset.priceUpdatedAt)
        : "",
    );

    return list;
  };

  ns.buildAssetDetailBody = buildAssetDetailBody;
})();
