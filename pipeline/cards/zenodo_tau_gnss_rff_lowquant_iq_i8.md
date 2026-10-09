# Tampere University GNSS RF-Fingerprinting Raw I/Q Snapshots, 'Low Quantization' 8-bit Category (25 MHz, clean sky), Int8 ADC Codes (Zenodo 13846381)

- Candidate id: `zenodo_tau_gnss_rff_lowquant_iq_i8`
- Width: int8
- Quantity: Raw GNSS front-end complex baseband I/Q samples quantized at 8 bits per real component (documented category 4 'Low Quantization; sampling rate 25 MHz, 8-bit per real (I/Q) sample quantization'), as integer ADC codes recovered exactly from the stored k/127 doubles.
- Source: https://zenodo.org/records/13846381
- Resources: https://zenodo.org/api/records/13846381/files/Data.zip/content, https://zenodo.org/api/records/13846381/files/readme.txt/content
- License: CC-BY-4.0
- License evidence: https://zenodo.org/records/13846381
- License quote: Zenodo record license: cc-by-4.0 ('Raw I/Q measurement data and software for GNSS RFF fingerprinting', W. Wang, J. Sankari, E.S. Lohan, M. Valkama, 10.5281/zenodo.13846381). The record description gives the archive password: 'You can unzip the files with TAUWireless'.
- Natural record: One .mat snapshot file data/oct_1{8,9}/S4_<n>.mat: one 4 ms capture of 100,000 complex samples at 25 MHz, stored as variable 'data' (100000×1 complex double) → 200,000 int8 values interleaved I,Q. 1,000 S4 files per day for 2 days (2,000 clean captures). The 1,000 spoofed SS4 captures are left out to keep one regime.
- Estimated samples: 2,000
- Estimated primary values: 400,000,000
- Estimated download bytes: 544,809,000
- Estimated primary bytes: 400,000,000
- Decode path: Two curl byte ranges of Data.zip (6,358,035,306 B) cover the contiguous S4 members exactly: oct_18 bytes 1306451528–1577931698 (271.5 MB) and oct_19 bytes 4419963079–4693291216 (273.3 MB). Walk the local headers (flag bit 0 = traditional PKWARE ZipCrypto, method 8), decrypt with password b'TAUWireless' (verify byte = CRC high byte), raw-inflate with zlib (wbits -15), and check CRC32. Parse MAT v5: 128-B header, then miCOMPRESSED (type 15), zlib-decompress, miMATRIX class 6 complex, dims 100000×1, name 'data', miDOUBLE real and imag parts. code = round(v*127), asserting |v*127 - code| < 1e-9 for every value; interleave I,Q as int8. Pure stdlib (zlib, struct, ZipCrypto in Python, which takes ~10–30 min over 545 MB).
- Novelty kind: new_source
- Measurement type: rf_iq_baseband
- Instrument line: tau_gnss_rff_25mhz_8bit_frontend
- Archive collection: zenodo
- Novelty evidence: No 8-bit rf_iq_baseband family exists locally or downstream (only ci16 and cf32 at 16/32 bits). GNSS material in the corpus is all 64-bit observables (CORS RINEX, COSMIC RO excess phase, clock bias), never raw front-end baseband samples. novelty.py --url matched the Zenodo host only. GNSS term hits are unrelated 64-bit recipes. No registry or ledger history.
- Homogeneity: Single receiver setup, single category (S4: clean signal, 25 MHz, 8-bit per real sample), two consecutive days (2022-10-18/19), fixed 100,000-sample snapshot length. Spoofed (SS4), 16-bit (S1–S3, SS1–SS3) and 'Fully' files are excluded. Probes on one file per day show the identical k/127 lattice, 0 off-lattice values in 200k, codes -37..32 with sd 6.88.
- Risks: (1) Values are stored as float64 multiples of 1/127. Recovering int8 codes is the exact inverse of the documented 8-bit quantization (verified lossless), but a judge could call it a derived remap; the manifest should mark it as recovering native ADC codes, with the lattice assertion in verify. (2) The archive is password-protected with a publicly published password: no account or credential, but unusual. (3) Codes use only ~6 bits (sd ~7), near-Gaussian noise with GNSS signals below the noise floor, so it may be byte-close to the ATA ci8 candidate or to SHARAD EDR i8 (pending). If both IQ candidates are built, the second may be WEAK. Prefer ATA if only one is taken. (4) Receiver hardware is not named in the record.
- Probe evidence: Data.zip central directory (13,367 entries, cdoff 6,356,587,012) read via range GET. Per category: S4 has 1,000 members per day of ~277 KB each, contiguous at the byte spans above. Local header of data/oct_18/S4_10011.mat shows flag 0x0001 and method 8. A 271,409-byte member decrypted with 'TAUWireless' (check byte matched CRC high byte 0xe7) inflated to a 277,152-B 'MATLAB 5.0 MAT-file, Platform: GLNXA64, Created on: Wed Nov 2 18:48:36 2022'. miCOMPRESSED → class 6 complex, dims (100000,1), name 'data', real and imag miDOUBLE 800,000 B each, 61 distinct values, all k/127. A second member (first oct_19 S4) gave 200,000 values, 0 non-integer after ×127, min -37, max 32, sd 6.88.

Proposed by the autocollect scout on 2026-10-09 (transcript `.data/pipeline/logs/scout_8bit/scout.20261009_010257.jsonl`).
