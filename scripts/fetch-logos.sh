#!/usr/bin/env bash
#
# Download the logo image for every xStock symbol in data/xstocks-assets.json.
#
# One endpoint is used:
#   GET https://xstocks-metadata.backed.fi/logos/tokens/{symbol}.png
#
# The logo URL is derived from the symbol. The public assets endpoint returns
# this exact pattern for every catalog entry, so no asset call is needed.
#
# Output: data/logos/{symbol}.png
#
# Behaviour:
#   - Existing files are skipped. Pass --force to overwrite them.
#   - Each file is written to a temp path first. A wrong content type is
#     rejected, so a partial or an error page never lands in the folder.
#   - The script reports a resolved count and a missed-symbol list.
#   - The exit code is non-zero when one or more downloads fail.
#
# Requires: curl, jq

set -euo pipefail

api_logo_base="https://xstocks-metadata.backed.fi/logos/tokens"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(dirname "$script_dir")"
in_file="$repo_root/data/xstocks-assets.json"
out_dir="$repo_root/data/logos"

force=false
if [ "${1:-}" = "--force" ]; then
    force=true
fi

if [ ! -f "$in_file" ]; then
    echo "Error: input file not found: $in_file" >&2
    exit 1
fi

mkdir -p "$out_dir"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

total=0
downloaded=0
skipped=0
failed=0
missed_symbols=""

while IFS= read -r symbol; do
    [ -z "$symbol" ] && continue
    total=$((total + 1))

    out_path="$out_dir/$symbol.png"

    if [ -f "$out_path" ] && [ "$force" != true ]; then
        skipped=$((skipped + 1))
        continue
    fi

    url="$api_logo_base/$symbol.png"
    tmp_path="$tmp_dir/$symbol.png"

    content_type=""
    if ! content_type="$(curl -sS --fail --location \
        --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 60 \
        -o "$tmp_path" -w '%{content_type}' "$url" 2>/dev/null)"; then
        echo "  MISS  $symbol (download failed)"
        failed=$((failed + 1))
        missed_symbols="$missed_symbols $symbol"
        rm -f "$tmp_path"
        continue
    fi

    if [ "$content_type" != "image/png" ]; then
        echo "  MISS  $symbol (unexpected content type: $content_type)"
        failed=$((failed + 1))
        missed_symbols="$missed_symbols $symbol"
        rm -f "$tmp_path"
        continue
    fi

    mv "$tmp_path" "$out_path"
    downloaded=$((downloaded + 1))
    echo "  OK    $symbol"
done < <(jq -r '.[].symbol' "$in_file")

echo ""
echo "Logos: $total symbols in input"
echo "  downloaded: $downloaded"
echo "  skipped:    $skipped"
echo "  failed:     $failed"
echo "Saved to $out_dir"

if [ "$failed" -gt 0 ]; then
    echo "Missed symbols:$missed_symbols"
    exit 1
fi
