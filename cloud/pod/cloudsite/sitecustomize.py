# Cloud pod only (opt-in via PYTHONPATH=/workspace/edge/cloud/pod/cloudsite:...): the container sees 96 CPUs but has a
# ~7.6-CPU quota; onnxruntime sizes its pool to 96 spinning threads. Cap and stop spinning for every session. Tried on the
# Axis edge Oct 24: no measurable change (the cause was the camera's 12 s GOP), kept for the record.
try:
    import onnxruntime as _ort
    _Orig = _ort.InferenceSession
    class _Capped(_Orig):
        def __init__(self, path, sess_options=None, *a, **k):
            so = sess_options or _ort.SessionOptions()
            so.intra_op_num_threads = 2; so.inter_op_num_threads = 1
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")
            super().__init__(path, so, *a, **k)
    _ort.InferenceSession = _Capped
except Exception:
    pass
