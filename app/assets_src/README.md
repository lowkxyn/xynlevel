# Logo sources

`xl-mark.svg` is the XL mark (the L's upright is the level-up arrow). The app masks it over the theme
colours, so it's white on transparent.

To rebuild the PNGs: serve this folder (`python -m http.server 4200 --directory app/assets_src`), then
screenshot `mark_png.html` at 512x512 into `src/assets/logo.png` and `icon_png.html` at 1024x1024 into
`src-tauri/icons/icon_src.png` with headless Edge (`--default-background-color=00000000` keeps the
transparency). Then run `bun run tauri icon src-tauri/icons/icon_src.png -o src-tauri/icons`.
