# Third-party licenses

License texts of the third-party files shipped with the web portal
(`app/web_hub/static/`). One folder per component. Each file is copied
**verbatim** from the upstream release, at the exact version listed in
[`../NOTICE.md`](../NOTICE.md) and pinned in [`../vendor.lock`](../vendor.lock).
The file names are the upstream ones.

`*.LICENSE.txt` files are the notices that a bundle points to (for example
`/*! For license information please see redoc.standalone.js.LICENSE.txt */`).
They list the modules embedded in that bundle.

## Updating a component

1. Vendor the new file (`tools/forge_vendor_asset.py`).
2. Update its entry in `VENDORED` (`tools/forge_release_assets.py`): version,
   source, SPDX license, license texts.
3. Copy the upstream license text of that version into this folder.
4. Regenerate the lock: `tools/forge_release_assets.py --vendor-lock-only`.
5. Check: `tools/forge_license_guard.py --embarques`. It refuses an
   undeclared file, a bundle replaced without updating the lock, and a
   missing license text.
