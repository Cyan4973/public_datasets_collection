The goal of this repository is to gather public datasets to train a Data Compression Transformer.

The current priority is numeric series. A stream may contain any homogeneous fixed-width numeric type: signed integer, unsigned integer, or floating point, with values encoded as 8-bit, 16-bit, 32-bit, or 64-bit elements.

For any multi-byte element width, the byte order must be explicitly defined. For now, generated streams should use little-endian encoding. If the source data uses another byte order, the conversion script should either convert it to little-endian or clearly document the retained byte order.

To be eligible, a dataset must be :
- Public, with a permissive license
- Accessible, with a script to download it locally
- Contain one or several numeric series. It's allowed to process the input to reach and generate these numeric streams.
- Each source corresponds to some homogenous stream of the same data. If a dataset contains multiple columns of different nature, each column will be its own stream.
- To be accepted, a source must contain at least 5 samples, or alternatively at least 250 KB of data
- No source should be larger than 1 GB. Find ways to only download about ~1 GB of data. It's not allowed to blow up local storage
