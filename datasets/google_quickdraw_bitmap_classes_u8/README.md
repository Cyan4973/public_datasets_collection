# Google Quick, Draw! Bitmap Classes UInt8

This staging recipe collects six public Google Quick, Draw! full bitmap class arrays and emits each class as a raw uint8 sketch-bitmap sample.

The domain is crowdsourced human sketch/doodle raster data. Each source `.npy` file contains many `28 x 28` grayscale drawings for one prompt class. The build strips the NumPy container and writes the source uint8 pixel payload unchanged, one sample per class.

Run:

```bash
bash staging/google_quickdraw_bitmap_classes_u8/download.sh
bash staging/google_quickdraw_bitmap_classes_u8/build.sh
bash staging/google_quickdraw_bitmap_classes_u8/verify.sh
```

The default class set is `airplane`, `cat`, `dog`, `car`, `house`, and `tree`. The combined source download is expected to be several hundred MB and is capped below 1 GB.
