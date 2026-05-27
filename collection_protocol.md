The goal of this repository is to gather public datasets to train a Data Compression Transformer.

The repository publishes scripts and metadata, not the dataset payloads themselves. Scripts should be runnable on a POSIX system and should let users download the same upstream data and rebuild the same output streams locally. Download and conversion steps should be deterministic where possible, with pinned source URLs or versions, documented parameters, and validation checks such as expected sizes or checksums.

Dataset payloads must not be committed to the repository. Downloaded upstream files, intermediate files, and generated output streams should be stored under a gitignored local data directory. Scripts may create and reuse that directory, but the committed repository should contain only scripts, metadata, documentation, and small test fixtures when explicitly approved.

The current priority is numeric series. A stream may contain any homogeneous fixed-width numeric type: signed integer, unsigned integer, or floating point, with values encoded as 8-bit, 16-bit, 32-bit, or 64-bit elements.

For any multi-byte element width, the byte order must be explicitly defined. For now, generated streams should use little-endian encoding. If the source data uses another byte order, the conversion script should either convert it to little-endian or clearly document the retained byte order.

Output streams are raw homogeneous arrays of numeric elements. The stream content must contain only the numeric element bytes, with no header, delimiter, timestamp, label, metadata block, compression wrapper, or bundled side data. Multi-byte elements should be encoded little-endian. No specific file extension is required.

To be eligible, a dataset must be :
- Public, with a clearly identified permissive license. Each dataset entry must document the source URL, license name, SPDX identifier when available, license URL or bundled license text, and any required citation or attribution. Datasets with missing, ambiguous, non-commercial, no-derivatives, or otherwise restrictive licenses are not eligible unless explicitly approved.
- Safe to redistribute and use for training. Datasets must not contain sensitive personal data, private user data, credentials, secrets, or data whose provenance is unclear. Public availability alone is not sufficient: datasets from mirrors, leaks, scraped personal content, or legally ambiguous sources are not eligible unless explicitly approved.
- Accessible, with a script to download it locally
- Contain one or several numeric series. It's allowed to process the input to reach and generate these numeric streams.
- Each source corresponds to some homogenous stream of the same data. If a dataset contains multiple columns of different nature, each column will be its own stream.
- To be accepted, a source must contain at least 5 samples, or alternatively at least 250 KB of data
- No source should be larger than 1 GB. Find ways to only download about ~1 GB of data. It's not allowed to blow up local storage
