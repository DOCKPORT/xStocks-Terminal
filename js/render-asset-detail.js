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

  /* The price takes the cent: a round value reads "$28.72", and a value with
     more decimals rounds to the nearest cent, so "$335.515" reads "$335.52". */
  const PRICE = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const COUNT = new Intl.NumberFormat("en-US");

  /* The reserve ratio takes three places, so two assets that both sit near one
     still read apart. */
  const RATIO = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  });

  /** The shape of an ISO stamp: "2026-09-18T17:57:27+00:00". */
  const ISO_STAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/;

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
   * Turn an ISO stamp into a readable UTC value. The stored text is read, not
   * parsed, so the time stays exactly as the snapshot holds it.
   * @param {string} value - The stored stamp.
   * @returns {string} The value as "09/18/26 17:57 UTC". An odd value returns unchanged.
   */
  const readStamp = (value) => {
    const match = ISO_STAMP.exec(value.trim());
    if (match === null) {
      return value.trim();
    }

    const [, year, month, day, time] = match;
    return `${month}/${day}/${year.slice(2)} ${time} UTC`;
  };

  /**
   * Read a stored value as a number. The snapshot keeps the supply and the share
   * values as strings, because those values have many decimals.
   * @param {unknown} value - The stored value.
   * @returns {number | null} The number, or null when the value is absent.
   */
  const toNumber = (value) => {
    if (typeof value === "number") {
      return Number.isFinite(value) ? value : null;
    }
    if (typeof value !== "string" || value.trim() === "") {
      return null;
    }

    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  /**
   * Work out the circulating tokens that stand behind one share held.
   * @param {Asset} asset - The asset for the panel.
   * @returns {number | null} The ratio, or null when the pair cannot give one.
   */
  const tokensPerShare = (asset) => {
    const supply = toNumber(asset.circulatingSupply);
    const shares = toNumber(asset.sharesHeld);

    if (supply === null || shares === null || shares <= 0) {
      return null;
    }
    return supply / shares;
  };

  /**
   * Build the field list for one asset. The order reads price first, then the
   * place of the asset, then the reserve pair, then the age of the data.
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
      "Circulating supply",
      typeof asset.circulatingSupply === "string"
        ? groupNumber(asset.circulatingSupply)
        : "",
    );

    const ratio = tokensPerShare(asset);
    add("Tokens per share", ratio === null ? "" : `${RATIO.format(ratio)} : 1`);

    /* The multiplier shows the stored value in full. Every money formatter
       rounds, so a value like 1.0157573238042787 would lose its tail. */
    add(
      "Multiplier",
      typeof asset.multiplier === "number" ? String(asset.multiplier) : "",
    );

    add(
      "Updated",
      typeof asset.priceUpdatedAt === "string"
        ? readStamp(asset.priceUpdatedAt)
        : "",
    );

    return list;
  };

  ns.buildAssetDetailBody = buildAssetDetailBody;
})();
