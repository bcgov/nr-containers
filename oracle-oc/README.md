# oracle-oc

MOF tools database image for [bcgov-c/nr-mof-db](https://github.com/bcgov-c/nr-mof-db): `oracle-free` plus the nr-mof-db sandbox init (`db_init/`) and startup (`startup/`) scripts.

Public image, deployed by nr-mof-db Oracle Promote (Main).

Image: `ghcr.io/bcgov/nr-containers/oracle-oc:23.26.3-faststart`

`db_init/` and `startup/` are vendored from nr-mof-db `oracle_config/`; when they change there, copy them here and open a PR.
