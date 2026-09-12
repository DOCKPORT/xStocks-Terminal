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

### scripts/fetch-assets.sh
- `scripts/fetch-assets.sh` downloads both endpoints and writes one merged JSON.
- Output `data/xstocks-assets.json`: array of `{ name, symbol, sharesHeld, circulatingSupply }`.
- Assets with `sharesHeld` of `"0"` are dropped. The last run dropped 9.
- 723 assets remain. 721 have reserves. Two have null reserve values. File size is about 100 KB.
- Values stay as strings, exactly as the API returns them. A null means no reserve entry.
- Run from anywhere: `./scripts/fetch-assets.sh`. Needs `curl` and `jq`.

### scripts/fetch-logos.sh
- `scripts/fetch-logos.sh` downloads the logo for every symbol in `data/xstocks-assets.json`.
- Output: `data/logos/{symbol}.png`. The folder holds 723 files and about 18 MB.
- Existing files are skipped. Pass `--force` to overwrite them.
- A wrong content type is rejected, so an error page never lands in the folder.
- The script prints a resolved count and a missed-symbol list. The exit code is non-zero when a download fails.
- Run from anywhere: `./scripts/fetch-logos.sh`. Needs `curl` and `jq`.

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

### Open Items
- Capture the `quote` object fields on a trading day.
- Confirm the latency on a trading day. A slow call may be a closed-market timeout.
- 723 calls at 21 seconds each is too slow. Use batching if this holds.

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
