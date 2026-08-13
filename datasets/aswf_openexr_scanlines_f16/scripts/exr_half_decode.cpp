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

static std::string base_name(const std::string& path) {
  const std::size_t pos=path.find_last_of("/\\");
  return pos==std::string::npos ? path : path.substr(pos+1);
}
static std::string stem_name(const std::string& path) {
  std::string value=base_name(path);
  if(value.size()>=4 && value.substr(value.size()-4)==".exr")value.resize(value.size()-4);
  return value;
}
static const char* compression_name(int value) {
  switch(value) {
    case TINYEXR_COMPRESSIONTYPE_NONE:return "none";
    case TINYEXR_COMPRESSIONTYPE_RLE:return "rle";
    case TINYEXR_COMPRESSIONTYPE_ZIPS:return "zips";
    case TINYEXR_COMPRESSIONTYPE_ZIP:return "zip";
    case TINYEXR_COMPRESSIONTYPE_PIZ:return "piz";
    default:return "unsupported";
  }
}
static float half_value(std::uint16_t bits) {
  const float sign=(bits&0x8000u)?-1.0f:1.0f;
  const unsigned exponent=(bits>>10)&0x1fu,mantissa=bits&0x3ffu;
  if(exponent==0)return sign*std::ldexp(static_cast<float>(mantissa),-24);
  return sign*std::ldexp(static_cast<float>(1024u+mantissa),static_cast<int>(exponent)-25);
}
static bool write_half_le(const std::string& path,const unsigned char* bytes,std::size_t count) {
  std::FILE* output=std::fopen(path.c_str(),"wb");if(!output)return false;
#if TINYEXR_LITTLE_ENDIAN
  bool ok=std::fwrite(bytes,2,count,output)==count;
#else
  bool ok=true;
  for(std::size_t i=0;i<count;++i){const unsigned char swapped[2]={bytes[i*2+1],bytes[i*2]};if(std::fwrite(swapped,2,1,output)!=1){ok=false;break;}}
#endif
  if(std::fclose(output)!=0)ok=false;
  return ok;
}

int main(int argc,char** argv) {
  if(argc!=4){std::fprintf(stderr,"usage: %s INPUT.exr OUTPUT_DIR STATS.tsv\n",argv[0]);return 2;}
  const std::string input=argv[1],output_dir=argv[2];EXRVersion version;
  if(ParseEXRVersionFromFile(&version,input.c_str())!=TINYEXR_SUCCESS || version.version!=2 ||
     version.tiled || version.non_image || version.multipart){std::fprintf(stderr,"unsupported structure: %s\n",input.c_str());return 1;}
  EXRHeader header;InitEXRHeader(&header);const char* error=nullptr;
  if(ParseEXRHeaderFromFile(&header,&version,input.c_str(),&error)!=TINYEXR_SUCCESS){
    std::fprintf(stderr,"header error: %s: %s\n",input.c_str(),error?error:"unknown");
    if(error)FreeEXRErrorMessage(error);
    FreeEXRHeader(&header);
    return 1;
  }
  if(std::string(compression_name(header.compression_type))=="unsupported"){
    std::fprintf(stderr,"unsupported compression: %s\n",input.c_str());FreeEXRHeader(&header);return 1;}
  for(int c=0;c<header.num_channels;++c)if(header.channels[c].x_sampling!=1 || header.channels[c].y_sampling!=1 ||
      header.requested_pixel_types[c]!=header.pixel_types[c]){
    std::fprintf(stderr,"subsampled/converted channel: %s channel=%s\n",input.c_str(),header.channels[c].name);FreeEXRHeader(&header);return 1;}
  EXRImage image;InitEXRImage(&image);
  if(LoadEXRImageFromFile(&image,&header,input.c_str(),&error)!=TINYEXR_SUCCESS){
    std::fprintf(stderr,"decode error: %s: %s\n",input.c_str(),error?error:"unknown");
    if(error)FreeEXRErrorMessage(error);
    FreeEXRImage(&image);
    FreeEXRHeader(&header);
    return 1;
  }
  const int width=header.data_window.max_x-header.data_window.min_x+1,height=header.data_window.max_y-header.data_window.min_y+1;
  if(!image.images || image.tiles || image.width!=width || image.height!=height || image.num_channels!=header.num_channels){
    std::fprintf(stderr,"geometry mismatch: %s\n",input.c_str());FreeEXRImage(&image);FreeEXRHeader(&header);return 1;}
  std::ofstream stats(argv[3],std::ios::out|std::ios::trunc);
  stats<<"source_file\tchannel\tpixel_type\tstatus\toutput_file\twidth\theight\tvalue_count\tcompression\tfinite_count\tzero_count\tmin_value\tmax_value\n";
  const std::size_t count=static_cast<std::size_t>(width)*static_cast<std::size_t>(height);int written=0;
  for(int c=0;c<header.num_channels;++c){
    if(header.pixel_types[c]!=TINYEXR_PIXELTYPE_HALF){
      stats<<base_name(input)<<'\t'<<header.channels[c].name<<"\tFLOAT\tskipped_non_half\t-\t"<<width<<'\t'<<height<<'\t'<<count<<'\t'<<compression_name(header.compression_type)<<"\t0\t0\t0\t0\n";continue;}
    const unsigned char* bytes=image.images[c];std::uint64_t finite=0,zeros=0;std::uint16_t first=0;bool nonconstant=false;
    float minimum=std::numeric_limits<float>::infinity(),maximum=-std::numeric_limits<float>::infinity();
    for(std::size_t i=0;i<count;++i){std::uint16_t bits;std::memcpy(&bits,bytes+i*2,2);if(i==0)first=bits;else if(bits!=first)nonconstant=true;
      if(((bits>>10)&0x1fu)==0x1fu)continue;
      ++finite;
      if((bits&0x7fffu)==0)++zeros;
      const float value=half_value(bits);
      minimum=std::min(minimum,value);
      maximum=std::max(maximum,value);
    }
    if(finite!=count){std::fprintf(stderr,"non-finite HALF values: %s channel=%s\n",input.c_str(),header.channels[c].name);FreeEXRImage(&image);FreeEXRHeader(&header);return 1;}
    if(!nonconstant){stats<<base_name(input)<<'\t'<<header.channels[c].name<<"\tHALF\tskipped_constant\t-\t"<<width<<'\t'<<height<<'\t'<<count<<'\t'<<compression_name(header.compression_type)<<'\t'<<finite<<'\t'<<zeros<<'\t'<<minimum<<'\t'<<maximum<<'\n';continue;}
    const std::string output_name=stem_name(input)+"_"+header.channels[c].name+".bin";
    if(!write_half_le(output_dir+"/"+output_name,bytes,count)){std::fprintf(stderr,"write failed: %s\n",output_name.c_str());FreeEXRImage(&image);FreeEXRHeader(&header);return 1;}
    stats<<base_name(input)<<'\t'<<header.channels[c].name<<"\tHALF\tretained\t"<<output_name<<'\t'<<width<<'\t'<<height<<'\t'<<count<<'\t'<<compression_name(header.compression_type)<<'\t'<<finite<<'\t'<<zeros<<'\t'<<minimum<<'\t'<<maximum<<'\n';++written;
  }
  FreeEXRImage(&image);FreeEXRHeader(&header);return(!stats||written==0)?1:0;
}
