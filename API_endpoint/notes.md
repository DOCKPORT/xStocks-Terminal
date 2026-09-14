# xStocks API Notes

Base: `https://api.backed.fi/api/v2/public`. No authentication for the public endpoints below.

## Endpoint: Public Assets
- **Method**: GET
- **URL**: `https://api.backed.fi/api/v2/public/assets`
- **Query**: `?page=N` (1-based).
- **Purpose**: Returns the xStocks asset catalog.

### Pagination (confirmed 2026-09-12)
- Each page holds 100 assets in `nodes`.
- The `page` object holds `currentPage` and `hasNextPage`. There is no total count.
- Pages 1 to 7 hold 100 assets. Page 8 holds 32. Page 9 and later are empty.
- The catalog holds 732 assets. All symbols are unique. Pages do not overlap.

### Node Fields
- `id`, `name`, `symbol`, `isin`, `underlyingSymbol`, `underlyingIsin`
- `underlying` — object with `symbol`, `isin`, `type`, `listingCountry`
- `description`, `logo`, `isTradingHalted`
- `trading` — trading hours and order limits
- `deployments` — array of chains. Each has `address`, `network`, optional `wrapperAddressV2`, `supportsAtomicSwaps`, `stablecoins`

## Endpoint: Proof of Reserves
- **Method**: GET
- **URL**: `https://api.backed.fi/api/v2/public/proof-of-reserves`
- **Query**: `?page=N` (1-based).
- **Purpose**: Returns shares held and circulating supply per symbol.

### Pagination (confirmed 2026-09-12)
- Each page holds 100 items in `nodes`.
- The `page` object holds `currentPage`, `pageSize`, `totalPages`, `totalNodes`, `hasNextPage`, `hasPreviousPage`.
- The `totalNodes` value reports 830. The real total is 730. Use `hasNextPage`, not `totalNodes`.
- Pages 1 to 7 hold 100 items. Page 8 holds 30. The set holds 730 unique symbols and no duplicates.

### Node Fields
- `symbol` — the xStock symbol.
- `timestamp` — the snapshot time in ISO format.
- `sharesHeld` — a string. Example `"4082"`.
- `circulatingSupply` — a string with many decimals. Example `"3880.3515380051873531"`.
- `holdings` — array of `{ provider, quantity, symbol }`.

### Coverage
- All 730 reserve symbols exist in the asset catalog.
- Two assets have no reserve entry: `FGDLx` and `NWGx`.
- 9 assets have a `sharesHeld` of `"0"`. The script drops these.

## Endpoint: Asset Logo
- **Method**: GET
- **URL**: `https://xstocks-metadata.backed.fi/logos/tokens/{symbol}.png`
- **Purpose**: Returns the logo image for one asset.
- **Response**: `200` with `content-type: image/png`. Each image is 400 x 400 RGBA, about 15 KB.

### Confirmed 2026-09-12
- The assets API `logo` field holds this exact URL for every catalog entry. Zero entries differ.
- The URL is derived from the symbol. No asset call is needed.
- Edge cases work: `BRK.Bx`, `Ox`, `Ax`, and `Vx` all return `image/png`.
- A bad symbol returns `403` with `content-type: application/xml`, not `404`. Check the content type, not only the status code.

## Fetch Scripts

### scripts/fetch_logos.py
- `scripts/fetch_logos.py` downloads the logo for every symbol in `data/xstocks-assets.json`.
- Output: `data/logos/{symbol}.png`. The folder holds 723 files and about 18 MB.
- Existing files are skipped. Pass `--force` to overwrite them.
- A wrong content type is rejected, so an error page never lands in the folder.
- A failed write is removed. A partial file never stays behind.
- The script prints a counts block: downloaded, changed, unchanged, skipped, and failed.
- The exit code is non-zero when one or more downloads fail.
- Run from anywhere: `./scripts/fetch_logos.py`. Python 3 only. No third-party packages.

#### Logo Change Check
- Pass `--check-changes` to compare every saved logo with the server.
- The request carries the fingerprint of the saved file. When the image did not change, the server matches the fingerprint and answers `304` with no body. No image bytes cross the wire.
- A `200` answer with new bytes replaces the file and prints `CHANGED {symbol}`.
- A `200` answer with the saved bytes keeps the file. This guards against a foreign fingerprint scheme.
- A missing file takes the plain download path and prints `OK {symbol}`.
- A change prints the symbol list and a note to commit the replaced files. The logos are tracked in git.
- The check costs 723 small requests, about one minute. `--force` overrides the check and downloads every file.
- `--check-changes` on its own downloads a missing logo too. The flag does not skip a new symbol.

### scripts/fetch_assets.py
- Python 3 script for the assets, the reserves, and the quotes. No third-party packages.
- Output: `data/xstocks-assets.json`: array of `{ name, symbol, sharesHeld, circulatingSupply, price, priceUpdatedAt }`.
- The page reads that file with `fetch`, so no wrapper file is written.
- Two different groups. Do not mix them:
  - The drop rule removes an asset when the reserve row reports `sharesHeld` of `"0"`. The last run dropped 9.
  - An asset with no reserve row stays, with null values. The last run kept 2: `FGDLx` and `NWGx`.
- 723 assets remain. 721 have reserves. File size is about 100 KB.
- Values stay as strings, exactly as the API returns them.
- The script prints both groups. The first line holds the dropped count. The second line holds the dropped symbols.
- Adds a `price` field and a `priceUpdatedAt` field per asset.
- Quotes download only during US trading hours: 4:00 to 20:00 ET, Monday to Friday. Market holidays are excluded.
- Outside that window the script skips every quote call and keeps the last known price.
- Quote calls run in a thread pool. The default is 32 workers. Set `--workers N` to change it.
- The quote step costs about 23 rounds at 32 workers. At about 1 second per call the step takes about 23 seconds.
- `--force-quotes` fetches quotes while the market is closed.
- The script runs `scripts/fetch_logos.py` after the write. The logo script skips every saved file, so only a new logo downloads. The child also receives `--check-changes`, so every saved logo is compared with the server.
- `--no-logo-check` skips the compare and the extra requests. A new logo still downloads.
- A child failure prints a warning. The snapshot stays valid, so the parent keeps exit code 0.
- The API rejects the default urllib User-Agent with `403`. The script sends its own User-Agent.
- Run from anywhere: `./scripts/fetch_assets.py`.

## Endpoint: Asset Price Data
- **Method**: GET
- **URL**: `https://api.backed.fi/api/v2/public/assets/{symbol}/price-data`
- **Purpose**: Returns the current quote for one asset.
- **Response**: `{"quote": ...}`. The value is null when the market is closed.
- **Coverage**: One symbol per call. There is no bulk variant.
- **Missing symbol**: `ZZZZx` returns HTTP 404.

### Confirmed 2026-09-12
- Every tested symbol returned `{"quote":null}`. The market was closed (Saturday).
- Latency was about 21 seconds per symbol while the market was closed.
- Both hosts work: `api.backed.fi` and `api.xstocks.fi`.

### Confirmed 2026-09-13
- The OpenAPI spec states the response is `{ "quote": number | null }`.
- There is no bulk or multi-symbol quote endpoint. One call covers one symbol.
- The endpoint needs a User-Agent header. The default urllib agent gets `403`.
- A closed-market call answers in about 21 seconds with `{"quote": null}`.
- 32 concurrent calls all answered in about 21 seconds with zero errors.

### Open Items
- Capture the `quote` object fields on a trading day.
- Measure the latency on a trading day. The 21-second wait is a closed-market behavior. The server waits on the price lookup, then returns null.
- Inside market hours a healthy call must answer in seconds. Do not size the run with the closed-market number. The gate skips those calls, so the slow case does not occur.
- If a call answers in about 1 second, 723 calls at 32 workers take about 23 rounds, so about 23 seconds. If a call answers in about 3 seconds, the step takes about 70 seconds.

## Endpoint: Sibling Asset Paths
Documented on the same page. Not fetched yet.
- `GET /public/assets/{symbol}/multiplier`
- `GET /public/assets/{symbol}/multiplier/history`
- `GET /public/assets/{symbol}/circulating-supply`
- `GET /public/assets/{symbol}/total-supply`

## Still Missing
- **Price values**: the endpoint exists, but it returns null while the market is closed. Confirm the schema and the latency on a trading day.

## Docs
- API reference: `https://docs.xstocks.fi/apis/openapi`
- Version: v2. Base path: `/api/v2/*`.
