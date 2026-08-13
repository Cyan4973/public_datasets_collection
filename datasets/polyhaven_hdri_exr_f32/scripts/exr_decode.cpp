#include <zlib.h>
#define TINYEXR_IMPLEMENTATION
#include "tinyexr.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <limits>
#include <string>

static std::string basename_of(const std::string& path) {
  const std::size_t pos = path.find_last_of("/\\");
  return pos == std::string::npos ? path : path.substr(pos + 1);
}

static std::string stem_of(const std::string& path) {
  std::string value = basename_of(path);
  if (value.size() >= 4 && value.substr(value.size() - 4) == ".exr") value.resize(value.size() - 4);
  return value;
}

static std::string clean(const char* text) {
  std::string result;
  for (unsigned char ch : std::string(text)) {
    const bool keep = (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
                      (ch >= '0' && ch <= '9') || ch == '_' || ch == '-' || ch == '.';
    result.push_back(keep ? static_cast<char>(ch) : '_');
  }
  return result.empty() ? "channel" : result;
}

static const char* compression_name(int value) {
  switch (value) {
    case TINYEXR_COMPRESSIONTYPE_NONE: return "none";
    case TINYEXR_COMPRESSIONTYPE_RLE: return "rle";
    case TINYEXR_COMPRESSIONTYPE_ZIPS: return "zips";
    case TINYEXR_COMPRESSIONTYPE_ZIP: return "zip";
    case TINYEXR_COMPRESSIONTYPE_PIZ: return "piz";
    default: return "unsupported";
  }
}

static bool write_f32_le(const std::string& path, const unsigned char* bytes, std::size_t count) {
  std::FILE* output = std::fopen(path.c_str(), "wb");
  if (!output) return false;
#if TINYEXR_LITTLE_ENDIAN
  bool ok = std::fwrite(bytes, sizeof(float), count, output) == count;
#else
  bool ok = true;
  for (std::size_t i = 0; i < count; ++i) {
    const unsigned char* word = bytes + i * 4;
    const unsigned char swapped[4] = {word[3], word[2], word[1], word[0]};
    if (std::fwrite(swapped, 4, 1, output) != 1) { ok = false; break; }
  }
#endif
  if (std::fclose(output) != 0) ok = false;
  return ok;
}

int main(int argc, char** argv) {
  if (argc != 4) {
    std::fprintf(stderr, "usage: %s INPUT.exr OUTPUT_DIR STATS.tsv\n", argv[0]);
    return 2;
  }
  const std::string input = argv[1];
  const std::string output_dir = argv[2];
  EXRVersion version;
  if (ParseEXRVersionFromFile(&version, input.c_str()) != TINYEXR_SUCCESS ||
      version.version != 2 || version.tiled || version.non_image || version.multipart) {
    std::fprintf(stderr, "unsupported EXR version/structure: %s\n", input.c_str());
    return 1;
  }

  EXRHeader header;
  InitEXRHeader(&header);
  const char* error = nullptr;
  if (ParseEXRHeaderFromFile(&header, &version, input.c_str(), &error) != TINYEXR_SUCCESS) {
    std::fprintf(stderr, "header error: %s: %s\n", input.c_str(), error ? error : "unknown");
    if (error) FreeEXRErrorMessage(error);
    FreeEXRHeader(&header);
    return 1;
  }
  if (header.tiled || header.non_image || header.multipart || header.num_channels <= 0 ||
      std::string(compression_name(header.compression_type)) == "unsupported") {
    std::fprintf(stderr, "unsupported EXR header: %s\n", input.c_str());
    FreeEXRHeader(&header);
    return 1;
  }
  for (int c = 0; c < header.num_channels; ++c) {
    if (header.pixel_types[c] != TINYEXR_PIXELTYPE_FLOAT ||
        header.requested_pixel_types[c] != TINYEXR_PIXELTYPE_FLOAT ||
        header.channels[c].x_sampling != 1 || header.channels[c].y_sampling != 1) {
      std::fprintf(stderr, "non-FLOAT or subsampled channel: %s channel=%s\n",
                   input.c_str(), header.channels[c].name);
      FreeEXRHeader(&header);
      return 1;
    }
  }

  EXRImage image;
  InitEXRImage(&image);
  if (LoadEXRImageFromFile(&image, &header, input.c_str(), &error) != TINYEXR_SUCCESS) {
    std::fprintf(stderr, "decode error: %s: %s\n", input.c_str(), error ? error : "unknown");
    if (error) FreeEXRErrorMessage(error);
    FreeEXRImage(&image);
    FreeEXRHeader(&header);
    return 1;
  }
  const int width = header.data_window.max_x - header.data_window.min_x + 1;
  const int height = header.data_window.max_y - header.data_window.min_y + 1;
  if (!image.images || image.tiles || image.width != width || image.height != height ||
      image.num_channels != header.num_channels || width <= 0 || height <= 0) {
    std::fprintf(stderr, "decoded geometry mismatch: %s\n", input.c_str());
    FreeEXRImage(&image); FreeEXRHeader(&header); return 1;
  }

  std::ofstream stats(argv[3], std::ios::out | std::ios::trunc);
  stats << "source_file\tchannel\toutput_file\twidth\theight\tvalue_count\tcompression"
           "\tfinite_count\tzero_count\tmin_value\tmax_value\n";
  const std::size_t count = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
  int written = 0;
  for (int c = 0; c < image.num_channels; ++c) {
    const unsigned char* bytes = image.images[c];
    std::uint64_t finite = 0, zeros = 0;
    float minimum = std::numeric_limits<float>::infinity();
    float maximum = -std::numeric_limits<float>::infinity();
    std::uint32_t first_bits = 0;
    bool nonconstant = false;
    for (std::size_t i = 0; i < count; ++i) {
      std::uint32_t bits;
      float value;
      std::memcpy(&bits, bytes + i * 4, 4);
      std::memcpy(&value, bytes + i * 4, 4);
      if (i == 0) first_bits = bits;
      else if (bits != first_bits) nonconstant = true;
      if (std::isfinite(value)) {
        ++finite;
        if (value == 0.0f) ++zeros;
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
      }
    }
    if (finite != count) {
      std::fprintf(stderr, "non-finite values: %s channel=%s\n", input.c_str(), header.channels[c].name);
      FreeEXRImage(&image); FreeEXRHeader(&header); return 1;
    }
    if (!nonconstant) {
      std::fprintf(stderr, "skip constant channel: %s channel=%s values=%zu\n",
                   input.c_str(), header.channels[c].name, count);
      continue;
    }
    const std::string output_name = stem_of(input) + "_" + clean(header.channels[c].name) + ".bin";
    if (!write_f32_le(output_dir + "/" + output_name, bytes, count)) {
      std::fprintf(stderr, "output write failed: %s\n", output_name.c_str());
      FreeEXRImage(&image); FreeEXRHeader(&header); return 1;
    }
    stats << basename_of(input) << '\t' << header.channels[c].name << '\t' << output_name << '\t'
          << width << '\t' << height << '\t' << count << '\t' << compression_name(header.compression_type)
          << '\t' << finite << '\t' << zeros << '\t' << minimum << '\t' << maximum << '\n';
    ++written;
  }
  FreeEXRImage(&image);
  FreeEXRHeader(&header);
  if (!stats || written == 0) return 1;
  return 0;
}
