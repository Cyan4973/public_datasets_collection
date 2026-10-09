# DTU DeepDFT QM9 VASP (PBE) Molecular Charge-Density Volumes: CHGCAR Real-Space Grid rho*V Float64

- Candidate id: `dtu_deepdft_qm9_vasp_chgcar_density_f64`
- Width: float64
- Quantity: VASP PBE total valence charge density on the real-space FFT grid (CHGCAR first block, rho times cell volume, electrons), one 3-D volume per QM9 molecule, Fortran x-fastest order
- Source: https://data.dtu.dk/articles/dataset/QM9_Charge_Densities_and_Energies_Calculated_with_VASP/16794500
- Resources: https://api.figshare.com/v2/articles/16794500, https://ndownloader.figshare.com/files/31062047
- License: CC BY 4.0
- License evidence: https://api.figshare.com/v2/articles/16794500
- License quote: "license": {"value": 1, "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"} (figshare/DTU Data article metadata for 'QM9 Charge Densities and Energies Calculated with VASP')
- Natural record: One molecule's CHGCAR = one float64 3-D volume (NGX*NGY*NGZ values from the header line after the atom positions, e.g. 56x56x56 = 175,616 values for methane, roughly 0.2-1M values for 9-heavy-atom molecules). Augmentation-occupancy blocks after the grid are not primary.
- Estimated samples: 120
- Estimated primary values: 55,000,000
- Estimated download bytes: 600,000,000
- Estimated primary bytes: 440,000,000
- Decode path: download.sh: curl a single contiguous byte-range prefix (for example the first ~600 MB) of one uncompressed tar (e.g. 000xxx.tar, figshare file 31062047, 5.53 GB, md5 00f306464d76c206ce00781415d405ca; or a mid tar for typical 9-heavy-atom molecules). Ranges are honoured (206 verified). build: walk the 512-byte ustar headers in pure Python and keep only complete members (NNNNNN.CHGCAR.lz4). Decompress each with the system lz4 CLI (/usr/bin/lz4 is present) or a ~60-line pure-Python LZ4-frame decoder (magic 04224d18 verified). Parse the POSCAR header: line 7 holds the species counts, then 'Direct' plus N position lines, a blank line, then the 'NGX NGY NGZ' line. Read NGX*NGY*NGZ E-format tokens (11 significant digits, e.g. 0.19764510556E-03) as float64 and write little-endian f64. Verified on 000001 (methane): 56^3 grid, 175,616 distinct values, min -0.0524, max 366.5.
- Novelty kind: new_source
- Measurement type: electron_density_volume
- Instrument line: VASP PBE plane-wave DFT (ASE driver), Gamma-point, encut 400 eV
- Archive collection: dtu_data_figshare
- Novelty evidence: novelty.py --url/--terms (CHGCAR, charge density, QM9, DeepDFT) finds no URL, recipe, registry or downstream match. The only hit is the ledger card materialsproject_chgcar_total_density_f64, which was screened out solely for unverifiable rights, and this source resolves that with an explicit per-article CC BY 4.0. No electron-density volume exists at any width (measurement_type electron_density_volume and archive dtu_data_figshare both return 0 members). Statistically this is a 3-D field spanning ~6 orders of magnitude, with sharp nuclear cusps, a smooth vacuum tail and small negative values, unlike the corpus's f64 time series and point clouds.
- Homogeneity: One code (VASP 'Normal' algo, PBE, encut 400 eV, Gamma-only, ISPIN=1), one quantity and unit (rho*V on the FFT grid) and one molecule class (QM9 organics in vacuum boxes). Grid dimensions vary per molecule, but the generation process and lattice are identical. Use only the first (total) density block.
- Risks: Sample sizes vary (methane 1.4 MB up to several MB per molecule); fine for collect-at-natural-boundary. The tar order puts the smallest QM9 molecules first in 000xxx.tar, so a later tar may be more representative; either way take a single contiguous prefix. Decimal text has 11 significant digits, so the f64 mantissas are not fully random. That is still well beyond f32 precision (VASP computes in double), so f64 is the honest width. figshare ndownloader redirects to S3 signed URLs; download.sh needs curl -L with resume. lz4 ratio is ~1.4x, so the transfer is close to the text size.
- Probe evidence: figshare API: 141 files, CC BY 4.0, 000xxx.tar = 5,526,958,080 bytes. A range GET of bytes 0-4194303 returned 206. tar members 000001.CHGCAR.lz4 (2,236,655 B), 000002 (1,918,290), 000003 (1,369,854); lz4 -dc of 000001 gave a 3.2 MB CHGCAR, C1H4, grid 56x56x56, values parsed.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_64bit/scout.20261009_095410.jsonl`).
