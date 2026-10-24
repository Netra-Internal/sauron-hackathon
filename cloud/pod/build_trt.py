"""Build the SigLIP vision TensorRT engine on the pod (fp16, dynamic batch 1..32), the same shape as the Jetson's
siglip-vision.engine, so netra-edge's unmodified SiglipTRT path loads it.  usage: build_trt.py in.onnx out.engine"""
import sys

import tensorrt as trt

src, dst = sys.argv[1], sys.argv[2]
log = trt.Logger(trt.Logger.WARNING)
b = trt.Builder(log)
net = b.create_network(0)
p = trt.OnnxParser(net, log)
if not p.parse_from_file(src):
    sys.exit("\n".join(str(p.get_error(i)) for i in range(p.num_errors)))
cfg = b.create_builder_config()
if hasattr(trt.BuilderFlag, "FP16"):        # gone from newer TensorRT wheels; fp32 then (the A5000 has room)
    cfg.set_flag(trt.BuilderFlag.FP16)
inp = net.get_input(0)
prof = b.create_optimization_profile()
c, h, w = inp.shape[1:]
prof.set_shape(inp.name, (1, c, h, w), (8, c, h, w), (32, c, h, w))
cfg.add_optimization_profile(prof)
eng = b.build_serialized_network(net, cfg)
if eng is None:
    sys.exit("build failed")
open(dst, "wb").write(eng)
print("built", dst, inp.name, tuple(inp.shape), "fp16" if hasattr(trt.BuilderFlag, "FP16") else "fp32", trt.__version__)
