# Student Palace Uploads

This folder holds user-uploaded images served by Flask’s `/static` route.

## Important
- Render persistent disk is mounted at:
  `/opt/render/project/src/static/uploads/houses`
- The app writes JPEGs into `static/uploads/houses/`.
- Keep the `.gitkeep` files so these directories always exist in the repo.
  If they’re missing, the disk mount may fail and the service can crash.

## Paths
- Public URL example:
  `/static/uploads/houses/house2_20250829082157_c7b538.jpg`
- DB `file_path` values are **relative** (no leading slash), e.g.:
  `uploads/houses/house2_20250829082157_c7b538.jpg`

## Do not commit real uploads
- Actual images are written at runtime and should **not** be committed to Git.
