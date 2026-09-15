#!/bin/bash
# Fetches the histogram-quantile ClickHouse UDF used by SigNoz and installs it
# into the shared user_scripts volume mounted at /var/lib/clickhouse/user_scripts.
set -euo pipefail

version="v0.0.1"
node_os=$(uname -s | tr '[:upper:]' '[:lower:]')
node_arch=$(uname -m | sed s/aarch64/arm64/ | sed s/x86_64/amd64/)
echo "Fetching histogram-quantile for ${node_os}/${node_arch}"
cd /tmp
wget -O histogram-quantile.tar.gz "https://github.com/SigNoz/signoz/releases/download/histogram-quantile%2F${version}/histogram-quantile_${node_os}_${node_arch}.tar.gz"
tar -xvzf histogram-quantile.tar.gz
mv histogram-quantile /var/lib/clickhouse/user_scripts/histogramQuantile
