/**
 * @file The release version of the app. This file is the single source of truth.
 * Edit the value below at each release, then add a git tag with the same value.
 */

/**
 * The shared page namespace. The page has no build step and no module loader, so
 * the files share one global object instead of ES module imports.
 * @typedef {object} VersionNamespace
 * @property {string} [version] - The release version, for example "v0.1.0".
 */

(() => {
  "use strict";

  /** @type {Window & { XSTOCKS?: VersionNamespace }} */
  const page = window;
  const ns = page.XSTOCKS || (page.XSTOCKS = {});

  /** The current release version. Bump this value and the git tag together. */
  const VERSION = "v1.1.0";

  ns.version = VERSION;
})();
