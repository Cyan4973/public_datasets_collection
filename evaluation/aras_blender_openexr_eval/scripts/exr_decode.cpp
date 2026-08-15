#include <zlib.h>
#define TINYEXR_IMPLEMENTATION
#include "tinyexr.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
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
                      (ch >= '0' && ch <= '9') || ch == '_' || ch == '-';
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

static float half_to_float(std::uint16_t half) {
  const std::uint32_t sign = static_cast<std::uint32_t>(half & 0x8000u) << 16;
  int exponent = (half >> 10) & 0x1fu;
  std::uint32_t mantissa = half & 0x03ffu;
  std::uint32_t bits;
  if (exponent == 0) {
    if (mantissa == 0) {
      bits = sign;
    } else {
      exponent = 1;
      while ((mantissa & 0x0400u) == 0) {
        mantissa <<= 1;
        --exponent;
      }
      mantissa &= 0x03ffu;
      bits = sign | (static_cast<std::uint32_t>(exponent + 112) << 23) | (mantissa << 13);
    }
  } else if (exponent == 31) {
    bits = sign | 0x7f800000u | (mantissa << 13);
  } else {
    bits = sign | (static_cast<std::uint32_t>(exponent + 112) << 23) | (mantissa << 13);
  }
  float value;
  std::memcpy(&value, &bits, sizeof(value));
  return value;
}

static bool write_le(const std::string& path, const unsigned char* bytes,
                     std::size_t count, std::size_t word_size) {
  std::FILE* output = std::fopen(path.c_str(), "wb");
  if (!output) return false;
#if TINYEXR_LITTLE_ENDIAN
  bool ok = std::fwrite(bytes, word_size, count, output) == count;
#else
  bool ok = true;
  for (std::size_t i = 0; i < count; ++i) {
    const unsigned char* word = bytes + i * word_size;
    for (std::size_t j = 0; j < word_size; ++j) {
      if (std::fputc(word[word_size - 1 - j], output) == EOF) { ok = false; break; }
    }
    if (!ok) break;
  }
#endif
  if (std::fclose(output) != 0) ok = false;
  return ok;
}

int main(int argc, char** argv) {
  if (argc != 4) {
    std::fprintf(stderr, "usage: %s INPUT.exr OUTPUT_ROOT STATS.tsv\n", argv[0]);
    return 2;
  }
  const std::string input = argv[1];
  const std::string output_root = argv[2];
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
      std::string(compression_name(header.compression_type)) != "zip") {
    std::fprintf(stderr, "unsupported EXR header: %s\n", input.c_str());
    FreeEXRHeader(&header);
    return 1;
  }
  for (int c = 0; c < header.num_channels; ++c) {
    const int type = header.pixel_types[c];
    if ((type != TINYEXR_PIXELTYPE_HALF && type != TINYEXR_PIXELTYPE_FLOAT) ||
        header.channels[c].x_sampling != 1 || header.channels[c].y_sampling != 1) {
      std::fprintf(stderr, "unsupported channel: %s channel=%s\n", input.c_str(), header.channels[c].name);
      FreeEXRHeader(&header);
      return 1;
    }
    header.requested_pixel_types[c] = type;
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
  stats << "source_file\tchannel_index\tchannel\tpixel_type\toutput_file\twidth\theight"
           "\tvalue_count\tsample_size_bytes\tcompression\tfinite_count\tnonfinite_count"
           "\tzero_count\tis_constant\tmin_value\tmax_value\n";
  stats << std::setprecision(17);
  const std::size_t count = static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
  for (int c = 0; c < image.num_channels; ++c) {
    const bool is_half = header.pixel_types[c] == TINYEXR_PIXELTYPE_HALF;
    const std::size_t word_size = is_half ? 2 : 4;
    const unsigned char* bytes = image.images[c];
    std::uint64_t finite = 0, nonfinite = 0, zeros = 0;
    double minimum = std::numeric_limits<double>::infinity();
    double maximum = -std::numeric_limits<double>::infinity();
    std::uint32_t first_bits = 0;
    bool nonconstant = false;
    for (std::size_t i = 0; i < count; ++i) {
      std::uint32_t bits = 0;
      double value;
      if (is_half) {
        std::uint16_t half;
        std::memcpy(&half, bytes + i * 2, 2);
        bits = half;
        value = half_to_float(half);
        if ((half & 0x7fffu) == 0) ++zeros;
      } else {
        float number;
        std::memcpy(&bits, bytes + i * 4, 4);
        std::memcpy(&number, bytes + i * 4, 4);
        value = number;
        if ((bits & 0x7fffffffu) == 0) ++zeros;
      }
      if (i == 0) first_bits = bits;
      else if (bits != first_bits) nonconstant = true;
      if (std::isfinite(value)) {
        ++finite;
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
      } else {
        ++nonfinite;
      }
    }
    char index_text[16];
    std::snprintf(index_text, sizeof(index_text), "c%03d", c);
    const char* pixel_type = is_half ? "HALF" : "FLOAT";
    const char* series = is_half ? "blender_exr_channel_plane_f16" : "blender_exr_channel_plane_f32";
    const std::string output_name = stem_of(input) + "_" + index_text + "_" +
                                    clean(header.channels[c].name) + ".bin";
    const std::string output_path = output_root + "/" + series + "/" + output_name;
    if (!write_le(output_path, bytes, count, word_size)) {
      std::fprintf(stderr, "output write failed: %s\n", output_path.c_str());
      FreeEXRImage(&image); FreeEXRHeader(&header); return 1;
    }
    stats << basename_of(input) << '\t' << c << '\t' << header.channels[c].name << '\t'
          << pixel_type << '\t' << series << "/" << output_name << '\t'
          << width << '\t' << height << '\t' << count << '\t' << count * word_size << '\t'
          << compression_name(header.compression_type) << '\t' << finite << '\t' << nonfinite
          << '\t' << zeros << '\t' << (nonconstant ? "false" : "true") << '\t';
    if (finite) stats << minimum;
    stats << '\t';
    if (finite) stats << maximum;
    stats << '\n';
  }
  FreeEXRImage(&image);
  FreeEXRHeader(&header);
  return stats ? 0 : 1;
}
