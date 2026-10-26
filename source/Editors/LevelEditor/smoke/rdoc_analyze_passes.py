# Run inside qrenderdoc: qrenderdoc.exe --python rdoc_analyze.py   (env RDOC_IN: the .rdc, RDOC_OUT: the report)
import os, collections
import renderdoc as rd

out = open(os.environ["RDOC_OUT"], "w")
def P(*a): out.write(" ".join(str(x) for x in a) + "\n"); out.flush()

try:
    cap = rd.OpenCaptureFile()
    st = cap.OpenFile(os.environ["RDOC_IN"], "", None)
    P("open", st)
    st, ctrl = cap.OpenCapture(rd.ReplayOptions(), None)
    P("replay", st)

    durations = {}
    for r in ctrl.FetchCounters([rd.GPUCounter.EventGPUDuration]):
        durations[r.eventId] = r.value.d
    sdf = ctrl.GetStructuredFile()

    # Walk the actions: a pass is a BeginPass..EndPass span; inside it, draws (direct or indirect)
    passes = []
    cur = None
    def walk(actions, depth=0):
        global cur
        for a in actions:
            name = a.GetName(sdf)
            if a.flags & rd.ActionFlags.BeginPass:
                cur = {"name": name, "eid": a.eventId, "draws": [], "dispatches": 0}
                passes.append(cur)
            if (a.flags & rd.ActionFlags.Drawcall) and cur is not None and depth == 0 or ((a.flags & rd.ActionFlags.Drawcall) and cur is not None and not a.children):
                cur["draws"].append(a)
            if a.children:
                walk(a.children, depth + 1)
            if a.flags & rd.ActionFlags.EndPass:
                cur = None
    walk(ctrl.GetRootActions())

    total = sum(v for v in durations.values())
    P("frame GPU sum of events (ms): %.3f" % (total * 1000))
    for i, p in enumerate(passes):
        d = sum(durations.get(a.eventId, 0.0) for a in p["draws"])
        P("pass %d eid %d %-40s draws %5d  GPU %.3f ms" % (i, p["eid"], p["name"][:40], len(p["draws"]), d * 1000))

    # The biggest pass (the scene pass): split by the draw's depth/colour state (prepass: no colour writes), per pipeline
    big = max(passes, key=lambda p: sum(durations.get(a.eventId, 0.0) for a in p["draws"]))
    groups = collections.OrderedDict()
    for a in big["draws"]:
        ctrl.SetFrameEvent(a.eventId, False)
        s = ctrl.GetVulkanPipelineState()
        cb = s.colorBlend.blends[0].writeMask if s.colorBlend.blends else 0
        ds = s.depthStencil
        key = ("prepass" if cb == 0 else "shade", int(s.graphics.pipelineResourceId), ds.depthFunction, ds.depthWriteEnable, ds.depthTestEnable)
        g = groups.setdefault(key, [0, 0.0, 0])
        g[0] += 1; g[1] += durations.get(a.eventId, 0.0); g[2] += a.numIndices * max(1, a.numInstances)
    P("scene pass (eid %d) by kind / pipeline / depth func / depth write / depth test:" % big["eid"])
    sums = collections.defaultdict(lambda: [0, 0.0, 0])
    for k, g in groups.items():
        P("  %-8s pipe %-12s %-22s write %d test %d: draws %5d  GPU %.3f ms  indices %d" % (k[0], k[1], k[2], k[3], k[4], g[0], g[1] * 1000, g[2]))
        s2 = sums[k[0]]; s2[0] += g[0]; s2[1] += g[1]; s2[2] += g[2]
    for k, s2 in sums.items():
        P("TOTAL %-8s draws %5d GPU %.3f ms indices %d" % (k, s2[0], s2[1] * 1000, s2[2]))
except Exception as e:
    import traceback
    P("ERROR", traceback.format_exc())
out.close()
os._exit(0)
