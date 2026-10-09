# Shared pins for build.sh and verify.sh (sourced). name|bytes|sha256
INPUTS=(
  "part-00000-of-00500.csv.gz|91723415|841254d3bc4199c26c82890dcd6bc87fcfb1ff23d75be8e39f0337f0ed1c6e28"
  "part-00001-of-00500.csv.gz|87188987|1fa83e39536baac92a1646dbe750541c6504e4c26a85b7f45d9259fd16d3919c"
  "part-00002-of-00500.csv.gz|90861131|7d217e976b9d380635f7330e1c75719858daa636efb2f35b8507823476c7b235"
  "part-00003-of-00500.csv.gz|85937819|4145a0bbd4cce2effc376f6e1204019bfeca49e635dfd358c2ead4be9e7c6416"
  "part-00004-of-00500.csv.gz|91924797|7b05867afe28b7b829a1fe17b8ed052ac67f4d9242c2714e41fe7046b73fbffd"
  "part-00005-of-00500.head-0-262143.gz|262144|fd0faf8889ac93caf308e3627f036de4d15801ab9c41d8f4e60510625f05ba59"
)
PART_NAMES=(
  part-00000-of-00500.csv.gz
  part-00001-of-00500.csv.gz
  part-00002-of-00500.csv.gz
  part-00003-of-00500.csv.gz
  part-00004-of-00500.csv.gz
)
NEXT_HEAD_NAME="part-00005-of-00500.head-0-262143.gz"
NEXT_FIRST_START_US=25656000000
# Trace start is 600 s (ClusterData2011_2.md); part 0 begins exactly there.
# Complete windows 600 s .. 25,200 s; window 25,500 s continues into part 5.
FIRST_WINDOW_S=600
WINDOWS=83
