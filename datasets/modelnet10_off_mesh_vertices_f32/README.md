# ModelNet10 OFF Mesh Vertices Float32

Candidate recipe for 3D object mesh vertex coordinates from the Princeton
ModelNet10 shape dataset.

The target source is the ModelNet10 ZIP archive of OFF meshes. Natural samples
are one mesh's vertex coordinate array, preserving source vertex order and
writing interleaved `x, y, z` float32 values. Face indices and class labels are
not emitted.

Run:

```bash
bash staging/modelnet10_off_mesh_vertices_f32/download.sh
```

Then build and verify locally:

```bash
bash staging/modelnet10_off_mesh_vertices_f32/build.sh
bash staging/modelnet10_off_mesh_vertices_f32/verify.sh
```
