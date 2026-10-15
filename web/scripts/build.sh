#!/bin/sh
# Buduje gotowy program: dist/Sejf.html (pełny dokument z blokadą sieci CSP) i plik uruchamiający dla Windows.
set -e
cd "$(dirname "$0")/.."
mkdir -p dist
{
  printf '%s\n' '<!doctype html>' '<html lang="pl">' '<head>' '<meta charset="utf-8">' '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
  printf '%s\n' "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'\">"
  printf '%s\n' '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}[hidden]{display:none!important}</style>'
  printf '%s\n' '</head>' '<body>'
  cat src/app.html
  printf '%s\n' '</body>' '</html>'
} > dist/Sejf.html
echo "Zbudowano dist/Sejf.html"
