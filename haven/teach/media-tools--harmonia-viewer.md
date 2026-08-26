# One pane over the studios - HARMONIA viewer
keywords: harmonia viewer normalized studios ports 43908 43906
HARMONIA (repo `harmonia\`) is the fleet's normalized studio viewer - one surface over sibling-studio output instead of opening each SPA separately. Binds 127.0.0.1:43908; that port was re-based specifically because :43907 collides with the live RILEY studio.

Port map to trust: aphrodite 43904, riley 43907, harmonia 43908, haven 43910, persephone 43909. The listener on :43906 is an unrelated local python process - never treat it as fleet surface.

Use HARMONIA when you want a single comparative pane over what APHRODITE and RILEY hold; use APHRODITE directly when you want full lightbox/rating power on `D:\new`.
