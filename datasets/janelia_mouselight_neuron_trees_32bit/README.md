# Janelia MouseLight neuron trees — 32-bit

This candidate targets complete mouse-neuron reconstructions from Janelia's
MouseLight project. The recipe emits two kinds of homogeneous 32-bit series:

- float32 X, Y, and Z coordinate fields; and
- int32 parent-node references encoding rooted-tree topology.

Each field would remain separate, with one complete neuron as one sample.
Coordinates, radii, node types, identifiers, and parent references must never
be interleaved. All emitted words must use canonical little-endian order.

The dataset adds a genuinely new numerical shape: irregular branching
trees with long locally smooth segments, discontinuities at branch traversal
boundaries, and parent-pointer topology. That is
different from point clouds, linear trajectories, images, and ordinary graph
edge lists.

The AWS Open Data Registry explicitly licenses the MouseLight imagery and
neuron-annotation bucket under CC BY 4.0. Metadata-only inventory found 3,264
canonical SWCs totaling 530,172,425 source bytes: 1,638 consensus axons and
1,626 dendrites.

The probe validated four trees containing 1,363 to 77,521 nodes, each with one
root and no missing, self, or forward parent references. Coordinates are
nonconstant; radius is constant or nearly binary and is excluded, along with
sequential node IDs and low-cardinality node types.

The bounded selection contains 256 consensus axons and 64 dendrites chosen at
even size-rank intervals from canonical SWCs of at least 50,000 source bytes.
It spans the full eligible size range while limiting acquisition to 320 files
and 108,215,773 bytes. Download the pinned selection with:

```bash
bash datasets/janelia_mouselight_neuron_trees_32bit/download.sh
```

The complete local build emits 1,280 homogeneous samples from 320 source
trees: 7,788,200 values and 31,152,800 bytes. Sample lengths range from 944 to
77,521 nodes, with a median of 3,465.5. Build and verify with:

```bash
bash datasets/janelia_mouselight_neuron_trees_32bit/build.sh
bash datasets/janelia_mouselight_neuron_trees_32bit/verify.sh
```

The aggregate decoded-byte SHA-256 is
`13735f2ceb37b9a0b72e6c98b92961b06b47b7c76485b79fb839ae38d631b9b9`.
